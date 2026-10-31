/* Retained draw packets, analytical antialiasing and a shared Unicode glyph atlas.
 * Native windows submit geometry to Sokol. Software pixels are materialized only
 * for snapshots/pixel inspection; both paths evaluate the same distance fields.
 */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <limits.h>
#include "render.h"
#define STB_TRUETYPE_IMPLEMENTATION
#include "vendor/stb_truetype.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

#define GLYPHS 8192
#define MEASURES 512
#define ATLAS_WIDTH 2048
#define ATLAS_MAX_HEIGHT 8192
#define OVERSAMPLE 2

typedef struct {
    unsigned codepoint;
    int px, used, rasterized, advance, atlas_x, atlas_y, w, h, ox, oy;
} Glyph;
typedef struct { char *text; int px; long width; uint64_t hash; } Measure;
typedef struct {
    float x0, y0, x1, y1, cx, cy, hx, hy, radius, stroke, blur, kind;
    float basis_x, basis_y, u0, v0, u1, v1, color[4];
} Command;
static unsigned char *pixels, *font_data, *atlas;
static stbtt_fontinfo font;
static Glyph glyphs[GLYPHS];
static Measure measures[MEASURES];
static Command *commands;
static MuiVertex *vertices;
static size_t command_count, command_capacity, vertex_count, vertex_capacity;
static int width, height, left, top, right, bottom, ready, cache_reset;
static int atlas_height, atlas_x, atlas_y, atlas_row;
static uint64_t atlas_revision, revision, materialized;
static long cache_hits, cache_misses;
/* One dynamic RGBA framebuffer per surface, copied on the application thread. */
static unsigned char *bitmap;
static int bitmap_width, bitmap_height;
static uint64_t bitmap_revision;
void mui_window_bitmap(const unsigned char *, int, int, uint64_t);

static void *reserve(void *data, size_t *capacity, size_t count, size_t size) {
    if (count <= *capacity) return data;
    size_t next = *capacity ? *capacity : 256;
    while (next < count) next *= 2;
    if (next > SIZE_MAX / size) abort();
    void *result = realloc(data, next * size);
    if (!result) { fprintf(stderr, "mayui: cannot allocate draw packet\n"); abort(); }
    *capacity = next;
    return result;
}
static float clamp01(float value) { return fminf(1, fmaxf(0, value)); }
static void color(float out[4], long rgb, long opacity) {
    out[0] = (float)((rgb >> 16) & 255) / 255;
    out[1] = (float)((rgb >> 8) & 255) / 255;
    out[2] = (float)(rgb & 255) / 255;
    out[3] = clamp01((float)opacity / 255);
}
static size_t big32(const unsigned char *p) {
    return (size_t)p[0] << 24 | (size_t)p[1] << 16 | (size_t)p[2] << 8 | p[3];
}
/* stb_truetype trusts its input. Check the sfnt header and table directory
 * first, so a truncated or corrupt MAYUI_FONT is skipped instead of being read
 * out of bounds. Offsets inside individual tables are still stb's to trust. */
static int font_offset(const unsigned char *data, size_t size) {
    size_t offset = 0;
    if (size >= 16 && !memcmp(data, "ttcf", 4)) offset = big32(data + 12);
    if (offset > size || size - offset < 12) return -1;
    const unsigned char *header = data + offset;
    if (memcmp(header, "\0\1\0\0", 4) && memcmp(header, "true", 4) && memcmp(header, "OTTO", 4) &&
        memcmp(header, "typ1", 4) && memcmp(header, "1\0\0\0", 4)) return -1;
    size_t tables = (size_t)header[4] << 8 | header[5];
    if (tables > (size - offset - 12) / 16) return -1;
    for (size_t i = 0; i < tables; i++) {
        size_t start = big32(header + 12 + 16 * i + 8), length = big32(header + 12 + 16 * i + 12);
        if (start > size || length > size - start) return -1;
    }
    return (int)offset;
}
static int init_font(void) {
    if (ready) return 1;
    const char *paths[] = {getenv("MAYUI_FONT"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf"};
    for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
        if (!paths[i]) continue;
        FILE *file = fopen(paths[i], "rb");
        if (!file) continue;
        if (fseek(file, 0, SEEK_END)) { fclose(file); continue; }
        long size = ftell(file);
        if (size < 1 || size > 16000000) { fclose(file); continue; }
        rewind(file);
        font_data = malloc((size_t)size);
        if (!font_data || fread(font_data, 1, (size_t)size, file) != (size_t)size) {
            free(font_data); font_data = NULL; fclose(file); continue;
        }
        fclose(file);
        int offset = font_offset(font_data, (size_t)size);
        if (offset >= 0 && stbtt_InitFont(&font, font_data, offset)) { ready = 1; return 1; }
        free(font_data); font_data = NULL;
    }
    return 0;
}
static void reset_atlas(void) {
    memset(glyphs, 0, sizeof(glyphs));
    if (atlas) memset(atlas, 0, (size_t)ATLAS_WIDTH * atlas_height);
    atlas_x = atlas_y = 1; atlas_row = 0; cache_reset = 0;
    atlas_revision++;
}
static int grow_atlas(void) {
    int next = atlas_height ? atlas_height * 2 : 2048;
    if (next > ATLAS_MAX_HEIGHT) return 0;
    unsigned char *data = realloc(atlas, (size_t)ATLAS_WIDTH * next);
    if (!data) return 0;
    memset(data + (size_t)ATLAS_WIDTH * atlas_height, 0, (size_t)ATLAS_WIDTH * (next - atlas_height));
    atlas = data; atlas_height = next; atlas_revision++;
    return 1;
}
static unsigned codepoint(const unsigned char **text) {
    const unsigned char *s = *text;
    unsigned a = *s++;
    if (a < 128) { *text = s; return a; }
    int n = a >= 0xf0 && a <= 0xf4 ? 3 : a >= 0xe0 && a <= 0xef ? 2 : a >= 0xc2 && a <= 0xdf ? 1 : 0;
    if (!n) { *text = s; return 0xfffd; }
    unsigned c = a & ((1u << (6 - n)) - 1);
    for (int i = 0; i < n; i++) {
        if ((s[i] & 192) != 128) { *text = s; return 0xfffd; }
        c = (c << 6) | (s[i] & 63);
    }
    *text = s + n;
    if ((n == 1 && c < 0x80) || (n == 2 && c < 0x800) || (n == 3 && c < 0x10000) ||
        c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff)) return 0xfffd;
    return c;
}
static Glyph *glyph(unsigned c, int px, int rasterize) {
    unsigned slot = (c * 2654435761u + (unsigned)px * 97u) % GLYPHS;
    Glyph *g = NULL;
    for (unsigned i = 0; i < GLYPHS; i++) {
        Glyph *candidate = &glyphs[(slot + i) % GLYPHS];
        if (!candidate->used) {
            int bearing;
            *candidate = (Glyph){.used = 1, .codepoint = c, .px = px, .atlas_x = -1};
            stbtt_GetCodepointHMetrics(&font, (int)c, &candidate->advance, &bearing);
            g = candidate; break;
        }
        if (candidate->codepoint == c && candidate->px == px) { g = candidate; break; }
    }
    if (!g) { cache_reset = 1; return NULL; }
    if (!rasterize || g->rasterized) { cache_hits++; return g; }
    cache_misses++;
    float scale = stbtt_ScaleForPixelHeight(&font, (float)px * OVERSAMPLE);
    int x1, y1;
    stbtt_GetCodepointBitmapBox(&font, (int)c, scale, scale, &g->ox, &g->oy, &x1, &y1);
    g->w = x1 - g->ox; g->h = y1 - g->oy; g->rasterized = 1;
    if (g->w <= 0 || g->h <= 0) return g;
    if (g->w + 2 >= ATLAS_WIDTH) { cache_reset = 1; return g; }
    if (!atlas && !grow_atlas()) { cache_reset = 1; return g; }
    if (atlas_x + g->w + 1 >= ATLAS_WIDTH) { atlas_y += atlas_row + 2; atlas_x = 1; atlas_row = 0; }
    while (atlas_y + g->h + 1 >= atlas_height) {
        if (!grow_atlas()) { cache_reset = 1; return g; }
    }
    g->atlas_x = atlas_x; g->atlas_y = atlas_y;
    stbtt_MakeCodepointBitmap(&font, atlas + (size_t)atlas_y * ATLAS_WIDTH + atlas_x,
                             g->w, g->h, ATLAS_WIDTH, scale, scale, (int)c);
    atlas_x += g->w + 2;
    if (g->h > atlas_row) atlas_row = g->h;
    atlas_revision++;
    return g;
}

/* UVs are either local distance-field coordinates or unnormalized atlas pixels. */
static void coordinates(const Command *c, float x, float y, float *u, float *v) {
    if (c->kind == 4) {
        *u = (x - c->cx) * c->basis_x;
        *v = (y - c->cy) * c->basis_y;
    } else if (c->kind == 1) {
        *u = c->u0 + (x - c->cx) * OVERSAMPLE;
        *v = c->v0 + (y - c->cy) * OVERSAMPLE;
    } else {
        float dx = x - c->cx, dy = y - c->cy;
        *u = dx * c->basis_x + dy * c->basis_y;
        *v = -dx * c->basis_y + dy * c->basis_x;
    }
}
static void append(Command c) {
    c.x0 = fmaxf(c.x0, (float)left); c.y0 = fmaxf(c.y0, (float)top);
    c.x1 = fminf(c.x1, (float)right); c.y1 = fminf(c.y1, (float)bottom);
    if (c.x1 <= c.x0 || c.y1 <= c.y0 || c.color[3] <= 0) return;
    commands = reserve(commands, &command_capacity, command_count + 1, sizeof(*commands));
    commands[command_count++] = c;
    vertices = reserve(vertices, &vertex_capacity, vertex_count + 6, sizeof(*vertices));
    const int corners[] = {0, 1, 2, 0, 2, 3};
    for (int i = 0; i < 6; i++) {
        int corner = corners[i];
        float x = corner == 1 || corner == 2 ? c.x1 : c.x0;
        float y = corner >= 2 ? c.y1 : c.y0;
        MuiVertex *v = &vertices[vertex_count++];
        *v = (MuiVertex){.position = {x, y}, .shape = {c.hx, c.hy, c.radius, c.kind}, .style = {c.stroke, c.blur}};
        coordinates(&c, x, y, &v->uv[0], &v->uv[1]);
        memcpy(v->color, c.color, sizeof(v->color));
    }
    revision++;
}
long mui_surface(long w, long h) {
    if (w < 1 || h < 1 || w > 8192 || h > 8192 || !init_font()) return 0;
    if (w != width || h != height) { free(pixels); pixels = NULL; }
    width = (int)w; height = (int)h;
    left = top = 0; right = width; bottom = height;
    command_count = vertex_count = 0; revision++;
    if (cache_reset) reset_atlas();
    return 1;
}
long mui_bitmap_upload(const unsigned char *rgba, long w, long h) {
    if (!rgba || w < 1 || h < 1 || w > 4096 || h > 4096) return 0;
    if (w != bitmap_width || h != bitmap_height) {
        unsigned char *next = realloc(bitmap, (size_t)w * h * 4);
        if (!next) return 0;
        bitmap = next; bitmap_width = (int)w; bitmap_height = (int)h;
    }
    memcpy(bitmap, rgba, (size_t)w * h * 4);
    bitmap_revision++; revision++;
    return 1;
}
void mui_bitmap(long x, long y, long w, long h) {
    if (!bitmap || w < 1 || h < 1) return;
    Command c = {.x0=(float)x, .y0=(float)y, .x1=(float)((double)x+w), .y1=(float)((double)y+h), .cx=(float)x, .cy=(float)y,
        .basis_x=(float)bitmap_width/w, .basis_y=(float)bitmap_height/h, .kind=4};
    color(c.color, 16777215, 255); append(c);
}
void mui_release(void) {
    free(bitmap); bitmap = NULL; bitmap_width = bitmap_height = 0; bitmap_revision++;
    free(pixels); pixels = NULL; free(font_data); font_data = NULL; free(atlas); atlas = NULL;
    free(commands); commands = NULL; free(vertices); vertices = NULL;
    for (int i = 0; i < MEASURES; i++) { free(measures[i].text); measures[i] = (Measure){0}; }
    command_count = command_capacity = vertex_count = vertex_capacity = 0;
    ready = width = height = atlas_height = 0; cache_hits = cache_misses = 0;
    materialized = 0; reset_atlas();
}
void mui_clip(long x, long y, long w, long h) {
    left = (int)fmax(0, fmin(width, x)); top = (int)fmax(0, fmin(height, y));
    right = (int)fmax(left, fmin(width, (double)x + fmax(0, w)));
    bottom = (int)fmax(top, fmin(height, (double)y + fmax(0, h)));
}
static void rectangle(float x, float y, float w, float h, float radius, float stroke, float blur, long rgb, long opacity) {
    if (w <= 0 || h <= 0 || !width) return;
    radius = fmaxf(0, fminf(radius, fminf(w, h) * .5f));
    float expand = blur > 0 ? blur * 3 : 0;
    Command c = {.x0 = x - expand, .y0 = y - expand, .x1 = x + w + expand, .y1 = y + h + expand,
        .cx = x + w * .5f, .cy = y + h * .5f, .hx = w * .5f, .hy = h * .5f,
        .radius = radius, .stroke = stroke, .blur = blur, .kind = blur > 0 ? 2 : 0, .basis_x = 1};
    color(c.color, rgb, opacity); append(c);
}
void mui_rect(long x, long y, long w, long h, long radius, long rgb) { rectangle(x, y, w, h, radius, 0, 0, rgb, 255); }
void mui_fill(long x, long y, long w, long h, long radius, long rgb, long opacity) { rectangle(x, y, w, h, radius, 0, 0, rgb, opacity); }
void mui_stroke(long x, long y, long w, long h, long radius, long thickness, long rgb, long opacity) {
    if (thickness > 0) rectangle(x, y, w, h, radius, (float)thickness, 0, rgb, opacity);
}
void mui_shadow(long x, long y, long w, long h, long radius, long blur, long rgb, long opacity) {
    if (blur > 0 && blur <= 64) rectangle(x, y, w, h, radius, 0, (float)blur, rgb, opacity);
}
void mui_line(long ax, long ay, long bx, long by, long thickness, long rgb, long opacity) {
    if (thickness < 1 || thickness > 256) return;
    /* Endpoints may be any long, so differences and midpoints use doubles. */
    double dx = (double)bx - (double)ax, dy = (double)by - (double)ay, length = sqrt(dx * dx + dy * dy);
    float r = thickness * .5f;
    Command c = {.x0 = fminf(ax, bx) - r - 1, .y0 = fminf(ay, by) - r - 1,
        .x1 = fmaxf(ax, bx) + r + 1, .y1 = fmaxf(ay, by) + r + 1,
        .cx = (float)(((double)ax + bx) * .5), .cy = (float)(((double)ay + by) * .5), .hx = (float)(length * .5) + r, .hy = r,
        .radius = r, .basis_x = length > 0 ? (float)(dx / length) : 1, .basis_y = length > 0 ? (float)(dy / length) : 0};
    color(c.color, rgb, opacity); append(c);
}
long mui_measure(const char *text, long px) {
    if (!text || !init_font() || px < 6 || px > 96) return 0;
    uint64_t hash = 1469598103934665603ull ^ (uint64_t)px;
    for (const unsigned char *s = (const unsigned char *)text; *s; s++) hash = (hash ^ *s) * 1099511628211ull;
    Measure *cached = &measures[hash % MEASURES];
    if (cached->text && cached->hash == hash && cached->px == px && !strcmp(cached->text, text)) return cached->width;
    float scale = stbtt_ScaleForPixelHeight(&font, (float)px), result = 0;
    const unsigned char *s = (const unsigned char *)text;
    while (*s) {
        unsigned c = codepoint(&s); Glyph *g = glyph(c, (int)px, 0);
        int advance, bearing;
        if (g) advance = g->advance; else stbtt_GetCodepointHMetrics(&font, (int)c, &advance, &bearing);
        result += advance * scale;
        if (*s) { const unsigned char *next = s; result += stbtt_GetCodepointKernAdvance(&font, (int)c, (int)codepoint(&next)) * scale; }
    }
    long measured = (long)(result + .5f);
    if (strlen(text) <= 2048) {
        char *copy = strdup(text);
        if (copy) { free(cached->text); *cached = (Measure){copy, (int)px, measured, hash}; }
    }
    return measured;
}
void mui_text(long x, long y, const char *text, long px, long rgb) {
    if (!text || !init_font() || px < 6 || px > 96 || !width) return;
    float scale = stbtt_ScaleForPixelHeight(&font, (float)px), pen = (float)x;
    int ascent, descent, gap;
    stbtt_GetFontVMetrics(&font, &ascent, &descent, &gap);
    float baseline = y + ascent * scale;
    const unsigned char *s = (const unsigned char *)text;
    while (*s) {
        unsigned c = codepoint(&s); Glyph *g = glyph(c, (int)px, 1);
        if (g && g->w > 0 && g->h > 0 && g->atlas_x >= 0) {
            float gx = pen + (float)g->ox / OVERSAMPLE, gy = baseline + (float)g->oy / OVERSAMPLE;
            Command cmd = {.x0 = gx, .y0 = gy, .x1 = gx + (float)g->w / OVERSAMPLE, .y1 = gy + (float)g->h / OVERSAMPLE,
                .cx = gx, .cy = gy, .u0 = (float)g->atlas_x, .v0 = (float)g->atlas_y, .kind = 1};
            color(cmd.color, rgb, 255); append(cmd);
        } else if (!g || (g->w > 0 && g->atlas_x < 0)) {
            rectangle(pen + 1, (float)y + 2, px / 2, px - 4, 1, 1, 0, rgb, 255);
        }
        int advance, bearing;
        if (g) advance = g->advance; else stbtt_GetCodepointHMetrics(&font, (int)c, &advance, &bearing);
        pen += advance * scale;
        if (*s) { const unsigned char *next = s; pen += stbtt_GetCodepointKernAdvance(&font, (int)c, (int)codepoint(&next)) * scale; }
        if (pen >= right) break;
    }
}
static float distance_field(float x, float y, float hx, float hy, float radius) {
    float dx = fabsf(x) - hx + radius, dy = fabsf(y) - hy + radius;
    return sqrtf(fmaxf(dx, 0) * fmaxf(dx, 0) + fmaxf(dy, 0) * fmaxf(dy, 0)) + fminf(fmaxf(dx, dy), 0) - radius;
}
static float atlas_sample(float u, float v) {
    float x = u - .5f, y = v - .5f;
    int x0 = (int)floorf(x), y0 = (int)floorf(y);
    float fx = x - x0, fy = y - y0, result = 0;
    for (int j = 0; j < 2; j++) for (int i = 0; i < 2; i++) {
        int sx = x0 + i, sy = y0 + j;
        if (sx >= 0 && sy >= 0 && sx < ATLAS_WIDTH && sy < atlas_height)
            result += atlas[(size_t)sy * ATLAS_WIDTH + sx] * (i ? fx : 1 - fx) * (j ? fy : 1 - fy);
    }
    return result / 255;
}
static void fill_span(int y, int begin, int end, const Command *c) {
    unsigned alpha = (unsigned)(c->color[3] * 255 + .5f);
    const unsigned source[] = {(unsigned)(c->color[0] * 255 + .5f), (unsigned)(c->color[1] * 255 + .5f), (unsigned)(c->color[2] * 255 + .5f)};
    unsigned char *p = pixels + ((size_t)y * width + begin) * 3;
    for (int x = begin; x < end; x++, p += 3) {
        for (int channel = 0; channel < 3; channel++)
            p[channel] = (unsigned char)((p[channel] * (255 - alpha) + source[channel] * alpha + 127) / 255);
    }
}
static int rasterize(void) {
    if (!width || !height) return 0;
    if (pixels && materialized == revision) return 1;
    if (!pixels) pixels = malloc((size_t)width * height * 3);
    if (!pixels) return 0;
    memset(pixels, 0, (size_t)width * height * 3);
    for (size_t i = 0; i < command_count; i++) {
        const Command *c = &commands[i];
        int x0 = (int)floorf(c->x0), y0 = (int)floorf(c->y0), x1 = (int)ceilf(c->x1), y1 = (int)ceilf(c->y1);
        for (int y = y0; y < y1; y++) {
            int span_begin = x0, span_end = x0;
            int skip = 0;
            if ((c->kind == 0 || c->kind == 2) && c->basis_x == 1 && c->basis_y == 0) {
                float hx = c->hx, hy = c->hy, radius = c->radius;
                if (c->stroke > 0) { hx -= c->stroke; hy -= c->stroke; radius = fmaxf(0, radius - c->stroke); skip = 1; }
                float margin = fabsf(y + .5f - c->cy) <= hy - radius - .5f ? 0 : radius;
                if (fabsf(y + .5f - c->cy) <= hy - .5f && hx > margin) {
                    span_begin = (int)fmaxf(x0, ceilf(c->cx - hx + margin));
                    span_end = (int)fminf(x1, floorf(c->cx + hx - margin));
                    if (span_end > span_begin && !skip) fill_span(y, span_begin, span_end, c);
                }
            }
            for (int x = x0; x < x1; x++) {
                if (span_end > span_begin && x >= span_begin && x < span_end) { x = span_end - 1; continue; }
                float u, v, coverage;
                coordinates(c, x + .5f, y + .5f, &u, &v);
                if (c->kind == 4) {
                    int sx = (int)fmaxf(0, fminf(bitmap_width-1, floorf(u)));
                    int sy = (int)fmaxf(0, fminf(bitmap_height-1, floorf(v)));
                    const unsigned char *src = bitmap + ((size_t)sy * bitmap_width + sx) * 4;
                    unsigned char *dst = pixels + ((size_t)y * width + x) * 3;
                    for (int ch=0; ch<3; ch++) dst[ch]=(dst[ch]*(255-src[3])+src[ch]*src[3]+127)/255;
                    continue;
                }
                if (c->kind == 1) coverage = atlas_sample(u, v);
                else {
                    float d = distance_field(u, v, c->hx, c->hy, c->radius);
                    if (c->kind == 2) { float t = fmaxf(d, 0) / c->blur; coverage = expf(-.5f * t * t); }
                    else {
                        coverage = clamp01(.5f - d);
                        if (c->stroke > 0 && c->hx > c->stroke && c->hy > c->stroke) {
                            float inner = distance_field(u, v, c->hx - c->stroke, c->hy - c->stroke, fmaxf(0, c->radius - c->stroke));
                            coverage *= 1 - clamp01(.5f - inner);
                        }
                    }
                }
                /* Fractional glyph bounds must cover partial edge pixels too. */
                coverage *= clamp01(fminf(x + 1, c->x1) - fmaxf(x, c->x0)) * clamp01(fminf(y + 1, c->y1) - fmaxf(y, c->y0));
                unsigned alpha = (unsigned)(clamp01(coverage * c->color[3]) * 255 + .5f);
                if (!alpha) continue;
                unsigned char *p = pixels + ((size_t)y * width + x) * 3;
                for (int channel = 0; channel < 3; channel++) {
                    unsigned source = (unsigned)(c->color[channel] * 255 + .5f);
                    p[channel] = (unsigned char)((p[channel] * (255 - alpha) + source * alpha + 127) / 255);
                }
            }
        }
    }
    materialized = revision;
    return 1;
}
void mui_present(void) {
    const char *mode = getenv("MAYUI_RENDERER");
    if (mode && !strcmp(mode, "cpu")) {
        if (rasterize()) mui_window_present(pixels, width, height);
        return;
    }
    mui_window_bitmap(bitmap, bitmap_width, bitmap_height, bitmap_revision);
    mui_window_submit(vertices, vertex_count, atlas, ATLAS_WIDTH, atlas_height, atlas_revision, width, height);
}
long mui_software_present(void) { return rasterize(); }
long mui_snapshot(const char *path) { return rasterize() && stbi_write_png(path, width, height, 3, pixels, width * 3); }
long mui_pixel(long x, long y) {
    if (x < 0 || y < 0 || x >= width || y >= height || !rasterize()) return -1;
    unsigned char *p = pixels + ((size_t)y * width + x) * 3;
    return (p[0] << 16) | (p[1] << 8) | p[2];
}
long mui_draw_stat(long index) {
    switch (index) {
        case 0: return (long)command_count;
        case 1: return (long)vertex_count;
        case 2: return cache_hits;
        case 3: return cache_misses;
        case 4: return (long)ATLAS_WIDTH * atlas_height;
        default: return 0;
    }
}
