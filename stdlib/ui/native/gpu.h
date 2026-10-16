/* Sokol renderer: one alpha-blended triangle batch for shapes, lines and glyphs.
 * GLSL is kept here beside its explicit Sokol reflection/layout declarations.
 */
#ifndef MAYUI_GPU_H
#define MAYUI_GPU_H
#include "render.h"
static struct {
    sg_shader shader;
    sg_pipeline pipeline;
    sg_buffer buffer, staging;
    sg_image image;
    sg_view view, bitmap_view;
    sg_image bitmap;
    sg_buffer bitmap_staging;
    int bitmap_width, bitmap_height;
    uint64_t bitmap_revision;
    sg_sampler linear, nearest;
    size_t buffer_size;
    int image_width, image_height, channels;
    uint64_t revision, geometry_revision;
} gpu;

static void gpu_setup(void) {
    sg_shader_desc shader = {
        .vertex_func.source =
            "#version 430\n"
            "uniform vec4 viewport;\n"
            "in vec2 position; in vec2 uv; in vec4 color; in vec4 shape; in vec2 style;\n"
            "out vec2 v_uv; out vec4 v_color; flat out vec4 v_shape; flat out vec2 v_style;\n"
            "void main(){ gl_Position=vec4(position.x/viewport.x*2.0-1.0,1.0-position.y/viewport.y*2.0,0,1);"
            "v_uv=uv; v_color=color; v_shape=shape; v_style=style; }\n",
        .fragment_func.source =
            "#version 430\n"
            "uniform sampler2D atlas; uniform sampler2D framebuffer;\n"
            "in vec2 v_uv; in vec4 v_color; flat in vec4 v_shape; flat in vec2 v_style; out vec4 frag;\n"
            "float sd(vec2 p,vec2 h,float r){vec2 q=abs(p)-h+vec2(r);return length(max(q,vec2(0)))+min(max(q.x,q.y),0.0)-r;}\n"
            "void main(){float coverage;"
            "if(v_shape.w==4.0){frag=texture(framebuffer,v_uv/vec2(textureSize(framebuffer,0)));return;}"
            "if(v_shape.w==3.0){frag=texture(atlas,v_uv/vec2(textureSize(atlas,0)));return;}"
            "if(v_shape.w==1.0){coverage=texture(atlas,v_uv/vec2(textureSize(atlas,0))).r;}"
            "else{float d=sd(v_uv,v_shape.xy,v_shape.z);"
            "if(v_shape.w==2.0){float t=max(d,0.0)/v_style.y;coverage=exp(-0.5*t*t);}"
            "else{coverage=clamp(0.5-d,0.0,1.0);"
            "if(v_style.x>0.0 && min(v_shape.x,v_shape.y)>v_style.x){"
            "float inner=sd(v_uv,v_shape.xy-vec2(v_style.x),max(0.0,v_shape.z-v_style.x));"
            "coverage*=1.0-clamp(0.5-inner,0.0,1.0);}}}"
            "frag=vec4(v_color.rgb,v_color.a*coverage);}\n",
        .attrs = {
            {.glsl_name = "position", .base_type = SG_SHADERATTRBASETYPE_FLOAT},
            {.glsl_name = "uv", .base_type = SG_SHADERATTRBASETYPE_FLOAT},
            {.glsl_name = "color", .base_type = SG_SHADERATTRBASETYPE_FLOAT},
            {.glsl_name = "shape", .base_type = SG_SHADERATTRBASETYPE_FLOAT},
            {.glsl_name = "style", .base_type = SG_SHADERATTRBASETYPE_FLOAT}
        },
        .uniform_blocks[0] = {.stage = SG_SHADERSTAGE_VERTEX, .size = 16,
            .glsl_uniforms[0] = {.glsl_name = "viewport", .type = SG_UNIFORMTYPE_FLOAT4, .array_count = 1}},
        .views[0].texture = {.stage = SG_SHADERSTAGE_FRAGMENT, .image_type = SG_IMAGETYPE_2D, .sample_type = SG_IMAGESAMPLETYPE_FLOAT},
        .samplers[0] = {.stage = SG_SHADERSTAGE_FRAGMENT, .sampler_type = SG_SAMPLERTYPE_FILTERING},
        .texture_sampler_pairs[0] = {.stage = SG_SHADERSTAGE_FRAGMENT, .view_slot = 0, .sampler_slot = 0, .glsl_name = "atlas"},
        .views[1].texture = {.stage = SG_SHADERSTAGE_FRAGMENT, .image_type = SG_IMAGETYPE_2D, .sample_type = SG_IMAGESAMPLETYPE_FLOAT},
        .samplers[1] = {.stage = SG_SHADERSTAGE_FRAGMENT, .sampler_type = SG_SAMPLERTYPE_FILTERING},
        .texture_sampler_pairs[1] = {.stage = SG_SHADERSTAGE_FRAGMENT, .view_slot = 1, .sampler_slot = 1, .glsl_name = "framebuffer"},
        .label = "mayui-distance-field-shader"
    };
    gpu.shader = sg_make_shader(&shader);
    gpu.pipeline = sg_make_pipeline(&(sg_pipeline_desc){
        .shader = gpu.shader,
        .layout = {.buffers[0].stride = sizeof(MuiVertex), .attrs = {
            {.format = SG_VERTEXFORMAT_FLOAT2}, {.format = SG_VERTEXFORMAT_FLOAT2},
            {.format = SG_VERTEXFORMAT_FLOAT4}, {.format = SG_VERTEXFORMAT_FLOAT4}, {.format = SG_VERTEXFORMAT_FLOAT2}}},
        .colors[0].blend = {.enabled = true, .src_factor_rgb = SG_BLENDFACTOR_SRC_ALPHA,
            .dst_factor_rgb = SG_BLENDFACTOR_ONE_MINUS_SRC_ALPHA, .src_factor_alpha = SG_BLENDFACTOR_ONE,
            .dst_factor_alpha = SG_BLENDFACTOR_ONE_MINUS_SRC_ALPHA},
        .label = "mayui-shapes-text"
    });
    gpu.linear = sg_make_sampler(&(sg_sampler_desc){.min_filter = SG_FILTER_LINEAR, .mag_filter = SG_FILTER_LINEAR,
        .wrap_u = SG_WRAP_CLAMP_TO_EDGE, .wrap_v = SG_WRAP_CLAMP_TO_EDGE});
    gpu.nearest = sg_make_sampler(&(sg_sampler_desc){.min_filter = SG_FILTER_NEAREST, .mag_filter = SG_FILTER_NEAREST,
        .wrap_u = SG_WRAP_CLAMP_TO_EDGE, .wrap_v = SG_WRAP_CLAMP_TO_EDGE});
}
static void gpu_upload(const MuiVertex *vertices, size_t count, const unsigned char *image,
                       int w, int h, int channels, uint64_t revision, uint64_t geometry_revision) {
    size_t size = count * sizeof(*vertices);
    if (size > gpu.buffer_size) {
        sg_destroy_buffer(gpu.buffer); sg_destroy_buffer(gpu.staging);
        gpu.buffer_size = 65536;
        while (gpu.buffer_size < size) gpu.buffer_size *= 2;
        gpu.buffer = sg_make_buffer(&(sg_buffer_desc){.size = gpu.buffer_size,
            .usage = {.vertex_buffer = true, .copy_dst = true}, .label = "mayui-geometry"});
        gpu.staging = sg_make_buffer(&(sg_buffer_desc){.size = gpu.buffer_size,
            .usage = {.staging_buffer = true, .copy_src = true, .write_transient = true}, .label = "mayui-upload"});
    }
    if (size && gpu.geometry_revision != geometry_revision) {
        sg_write_buffer_transient(&(sg_write_buffer_desc){.dst.buffer = gpu.staging, .src.data = {vertices, size}});
        sg_copy_buffer_to_buffer(&(sg_copy_buffer_to_buffer_desc){.src.buffer = gpu.staging, .dst.buffer = gpu.buffer, .size = size});
        gpu.geometry_revision = geometry_revision;
    }
    static const unsigned char white = 255;
    if (!image || w < 1 || h < 1) { image = &white; w = h = channels = 1; }
    if (!gpu.image.id || gpu.revision != revision || gpu.channels != channels || gpu.image_width != w || gpu.image_height != h) {
        sg_destroy_view(gpu.view); sg_destroy_image(gpu.image);
        gpu.image = sg_make_image(&(sg_image_desc){.width = w, .height = h,
            .pixel_format = channels == 4 ? SG_PIXELFORMAT_RGBA8 : SG_PIXELFORMAT_R8,
            .data.mip_levels[0] = {image, (size_t)w * h * channels}, .label = "mayui-glyph-atlas"});
        gpu.view = sg_make_view(&(sg_view_desc){.texture.image = gpu.image});
        gpu.image_width = w; gpu.image_height = h; gpu.channels = channels; gpu.revision = revision;
    }
}
static void gpu_bitmap(const unsigned char *data, int w, int h, uint64_t revision) {
    static const unsigned char black[4] = {0,0,0,255};
    if (!data || w < 1 || h < 1) { data=black; w=h=1; }
    if (gpu.bitmap.id && gpu.bitmap_revision == revision) return;
    if (!gpu.bitmap.id || gpu.bitmap_width != w || gpu.bitmap_height != h) {
        sg_destroy_view(gpu.bitmap_view); sg_destroy_image(gpu.bitmap); sg_destroy_buffer(gpu.bitmap_staging);
        gpu.bitmap=sg_make_image(&(sg_image_desc){.width=w, .height=h, .pixel_format=SG_PIXELFORMAT_RGBA8,
            .usage.copy_dst=true, .label="mayui-framebuffer"});
        gpu.bitmap_view=sg_make_view(&(sg_view_desc){.texture.image=gpu.bitmap});
        gpu.bitmap_staging=sg_make_buffer(&(sg_buffer_desc){.size=(size_t)w*h*4,
            .usage={.staging_buffer=true,.copy_src=true,.write_transient=true}});
        gpu.bitmap_width=w; gpu.bitmap_height=h;
    }
    sg_write_buffer_transient(&(sg_write_buffer_desc){.dst.buffer=gpu.bitmap_staging, .src.data={data,(size_t)w*h*4}});
    sg_copy_buffer_to_image(&(sg_copy_buffer_to_image_desc){.src={.buffer=gpu.bitmap_staging,.bytes_per_row=w*4},
        .dst.image=gpu.bitmap, .size={.width=w,.height=h,.num_slices=1}});
    gpu.bitmap_revision=revision;
}
static void gpu_draw(size_t count, int width, int height) {
    if (!count || width < 1 || height < 1) return;
    const float viewport[] = {(float)width, (float)height, 0, 0};
    sg_apply_pipeline(gpu.pipeline);
    sg_apply_bindings(&(sg_bindings){.vertex_buffers[0] = gpu.buffer, .views[0] = gpu.view,
        .samplers[0] = gpu.channels == 4 ? gpu.nearest : gpu.linear,
        .views[1]=gpu.bitmap_view, .samplers[1]=gpu.nearest});
    sg_apply_uniforms(0, &(sg_range){viewport, sizeof(viewport)});
    sg_draw(0, (int)count, 1);
}
static void gpu_shutdown(void) {
    sg_destroy_buffer(gpu.buffer); sg_destroy_buffer(gpu.staging); sg_destroy_view(gpu.view); sg_destroy_image(gpu.image);
    sg_destroy_view(gpu.bitmap_view); sg_destroy_image(gpu.bitmap); sg_destroy_buffer(gpu.bitmap_staging);
    sg_destroy_sampler(gpu.linear); sg_destroy_sampler(gpu.nearest);
    sg_destroy_pipeline(gpu.pipeline); sg_destroy_shader(gpu.shader);
    memset(&gpu, 0, sizeof(gpu));
}
#endif
