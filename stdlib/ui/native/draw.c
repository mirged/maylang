/* CPU raster surface, font metrics and PNG output. No widget/layout policy. 
 * Optimized: Glyph caching, fast-path solid fills, zero-division alpha blending.
 */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

#define STB_TRUETYPE_IMPLEMENTATION
#include "vendor/stb_truetype.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

static unsigned char *pixels, *font_data;
static stbtt_fontinfo font;
static long width, height, left, top, right, bottom;
static int ready;

extern void mui_window_present(const unsigned char *, long, long);

/* --- GLYPH CACHE SYSTEM --- */
#define CACHE_MIN_PX 6
#define CACHE_MAX_PX 96
#define CACHE_CHARS  128

typedef struct {
    unsigned char *mask;
    int w, h, ox, oy;
    int advance, bearing;
    unsigned char ready;
} CachedGlyph;

static CachedGlyph glyph_cache[CACHE_MAX_PX + 1][CACHE_CHARS];

static void clear_glyph_cache(void) {
    for (int p = CACHE_MIN_PX; p <= CACHE_MAX_PX; p++) {
        for (int c = 0; c < CACHE_CHARS; c++) {
            if (glyph_cache[p][c].ready) {
                if (glyph_cache[p][c].mask) {
                    stbtt_FreeBitmap(glyph_cache[p][c].mask, NULL);
                    glyph_cache[p][c].mask = NULL;
                }
                glyph_cache[p][c].ready = 0;
            }
        }
    }
}

static inline CachedGlyph *get_glyph(unsigned int c, long px, float scale) {
    if (px < CACHE_MIN_PX || px > CACHE_MAX_PX || c >= CACHE_CHARS) return NULL;
    CachedGlyph *g = &glyph_cache[px][c];
    if (!g->ready) {
        stbtt_GetCodepointHMetrics(&font, (int)c, &g->advance, &g->bearing);
        g->mask = stbtt_GetCodepointBitmap(&font, 0, scale, (int)c, &g->w, &g->h, &g->ox, &g->oy);
        g->ready = 1;
    }
    return g;
}

/* --- FAST BITWISE ALPHA BLENDING (ZERO INTEGER DIVISION) --- */
static inline void blend_fast(unsigned char *p, unsigned char r, unsigned char g, unsigned char b, unsigned int a) {
    if (a == 255) {
        p[0] = r; p[1] = g; p[2] = b;
    } else if (a > 0) {
        unsigned int inv = 255 - a;
        p[0] = (unsigned char)((p[0] * inv + r * a + 128) >> 8);
        p[1] = (unsigned char)((p[1] * inv + g * a + 128) >> 8);
        p[2] = (unsigned char)((p[2] * inv + b * a + 128) >> 8);
    }
}

static int init_font(void) {
    if (ready) return 1;
    const char *paths[] = {
        getenv("MAYUI_FONT"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf"
    };
    for (size_t i = 0; i < sizeof(paths)/sizeof(paths[0]); ++i) {
        if (!paths[i]) continue;
        FILE *f = fopen(paths[i], "rb"); 
        if (!f) continue;
        if (fseek(f, 0, SEEK_END) || ftell(f) <= 0 || ftell(f) > 16000000) { fclose(f); continue; }
        long n = ftell(f); 
        rewind(f); 
        font_data = malloc(n);
        if (!font_data || fread(font_data, 1, n, f) != (size_t)n) { 
            free(font_data); font_data = NULL; fclose(f); continue; 
        }
        fclose(f);
        if (stbtt_InitFont(&font, font_data, stbtt_GetFontOffsetForIndex(font_data, 0))) { 
            ready = 1; 
            return 1; 
        }
        free(font_data); font_data = NULL;
    }
    return 0;
}

long mui_surface(long w, long h) {
    if (w < 1 || h < 1 || w > 8192 || h > 8192 || !init_font()) return 0;
    if (w != width || h != height || !pixels) {
        unsigned char *next = calloc((size_t)w * h, 3); 
        if (!next) return 0;
        free(pixels); 
        pixels = next; 
        width = w; 
        height = h;
    }
    left = top = 0; 
    right = width; 
    bottom = height; 
    return 1;
}

void mui_release(void) { 
    clear_glyph_cache();
    free(pixels); pixels = NULL; 
    free(font_data); font_data = NULL; 
    ready = 0; 
    width = height = 0; 
}

void mui_clip(long x, long y, long w, long h) {
    left   = x > 0 ? x : 0; 
    top    = y > 0 ? y : 0; 
    right  = x + w < width ? x + w : width; 
    bottom = y + h < height ? y + h : height;
}

void mui_rect(long x, long y, long w, long h, long radius, long color) {
    if (!pixels || w <= 0 || h <= 0) return;
    if (radius < 0) radius = 0;
    if (radius > w / 2) radius = w / 2;
    if (radius > h / 2) radius = h / 2;

    long x0 = x > left ? x : left;
    long y0 = y > top ? y : top;
    long x1 = x + w < right ? x + w : right;
    long y1 = y + h < bottom ? y + h : bottom;
    if (x0 >= x1 || y0 >= y1) return;

    unsigned char r = (unsigned char)((color >> 16) & 0xFF);
    unsigned char g = (unsigned char)((color >> 8) & 0xFF);
    unsigned char b = (unsigned char)(color & 0xFF);

    /* --- FAST PATH: Solid Rectangle (No Corners) --- */
    if (radius == 0) {
        for (long py = y0; py < y1; py++) {
            unsigned char *p = pixels + (py * width + x0) * 3;
            for (long px = x0; px < x1; px++) {
                *p++ = r;
                *p++ = g;
                *p++ = b;
            }
        }
        return;
    }

    /* --- Rounded Rectangle --- */
    long r2 = radius * radius;
    long inner_left   = x + radius;
    long inner_right  = x + w - radius;
    long inner_top    = y + radius;
    long inner_bottom = y + h - radius;

    for (long py = y0; py < y1; py++) {
        unsigned char *p = pixels + (py * width + x0) * 3;
        for (long px = x0; px < x1; px++, p += 3) {
            long dx = px < inner_left ? inner_left - px : (px >= inner_right ? px - (inner_right - 1) : 0);
            long dy = py < inner_top  ? inner_top  - py : (py >= inner_bottom ? py - (inner_bottom - 1) : 0);
            if (!dx || !dy || (dx * dx + dy * dy <= r2)) {
                p[0] = r;
                p[1] = g;
                p[2] = b;
            }
        }
    }
}

static unsigned codepoint(const unsigned char **s) {
    unsigned a = *(*s)++; 
    if (a < 128) return a;
    int n = a >= 240 ? 3 : (a >= 224 ? 2 : (a >= 192 ? 1 : 0)); 
    unsigned c = a & ((1u << (6 - n)) - 1);
    if (!n) return 0xfffd;
    for (int i = 0; i < n; i++) { 
        if ((**s & 192) != 128) return 0xfffd; 
        c = (c << 6) | (*(*s)++ & 63); 
    }
    return c;
}

long mui_measure(const char *text, long px) {
    if (!init_font() || px < CACHE_MIN_PX || px > CACHE_MAX_PX) return 0;
    float scale = stbtt_ScaleForPixelHeight(&font, (float)px), result = 0;
    const unsigned char *s = (const unsigned char*)text;
    while (*s) { 
        unsigned c = codepoint(&s);
        int advance = 0, bearing = 0;
        CachedGlyph *g = get_glyph(c, px, scale);
        if (g) {
            advance = g->advance;
        } else {
            stbtt_GetCodepointHMetrics(&font, (int)c, &advance, &bearing);
        }
        result += (float)advance * scale;
        if (*s) { 
            const unsigned char *next = s; 
            result += (float)stbtt_GetCodepointKernAdvance(&font, (int)c, (int)codepoint(&next)) * scale; 
        }
    }
    return (long)(result + 0.5f);
}

void mui_text(long x, long y, const char *text, long px, long color) {
    if (!pixels || !init_font() || px < CACHE_MIN_PX || px > CACHE_MAX_PX) return;
    float scale = stbtt_ScaleForPixelHeight(&font, (float)px), pen = (float)x; 
    int ascent, descent, gap;
    stbtt_GetFontVMetrics(&font, &ascent, &descent, &gap); 
    int baseline = (int)y + (int)((float)ascent * scale);

    unsigned char r = (unsigned char)((color >> 16) & 0xFF);
    unsigned char g = (unsigned char)((color >> 8) & 0xFF);
    unsigned char b = (unsigned char)(color & 0xFF);

    const unsigned char *s = (const unsigned char*)text;
    while (*s) { 
        unsigned c = codepoint(&s); 
        int w = 0, h = 0, ox = 0, oy = 0, advance = 0, bearing = 0;
        unsigned char *mask = NULL;
        int is_cached = 0;

        CachedGlyph *cg = get_glyph(c, px, scale);
        if (cg) {
            w = cg->w; h = cg->h; ox = cg->ox; oy = cg->oy;
            advance = cg->advance;
            mask = cg->mask;
            is_cached = 1;
        } else {
            mask = stbtt_GetCodepointBitmap(&font, 0, scale, (int)c, &w, &h, &ox, &oy);
            stbtt_GetCodepointHMetrics(&font, (int)c, &advance, &bearing);
        }

        if (mask && w > 0 && h > 0) { 
            long gx = (long)pen + ox;
            long gy = baseline + oy;
            for (int j = 0; j < h; j++) {
                long py = gy + j;
                if (py < top || py >= bottom) continue;
                for (int i = 0; i < w; i++) {
                    long px_pos = gx + i;
                    if (px_pos < left || px_pos >= right) continue;
                    unsigned char alpha = mask[j * w + i];
                    if (alpha) {
                        blend_fast(pixels + (py * width + px_pos) * 3, r, g, b, alpha);
                    }
                }
            }
            if (!is_cached) {
                stbtt_FreeBitmap(mask, NULL);
            }
        }

        pen += (float)advance * scale;
        if (*s) { 
            const unsigned char *next = s; 
            pen += (float)stbtt_GetCodepointKernAdvance(&font, (int)c, (int)codepoint(&next)) * scale; 
        }
        if (pen >= (float)right) break;
    }
}

void mui_present(void) { 
    if (pixels) mui_window_present(pixels, width, height); 
}

long mui_snapshot(const char *path) { 
    return pixels && stbi_write_png(path, (int)width, (int)height, 3, pixels, (int)(width * 3)); 
}

long mui_pixel(long x, long y) { 
    if (!pixels || x < 0 || y < 0 || x >= width || y >= height) return -1; 
    unsigned char *p = pixels + (y * width + x) * 3; 
    return (p[0] << 16) | (p[1] << 8) | p[2]; 
}