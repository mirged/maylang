/* Malformed-input driver for stdlib/ui/native/draw.c, built with ASan/UBSan by
 * sanitize.py. Each case runs in its own process so the font, atlas and surface
 * state start fresh. Window entry points are stubbed: this covers the software
 * raster, glyph atlas, bitmap and font paths, not the Sokol/X11 window.
 */
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../stdlib/ui/native/render.h"

long mui_surface(long, long);
long mui_bitmap_upload(const unsigned char *, long, long);
void mui_bitmap(long, long, long, long);
void mui_release(void);
void mui_clip(long, long, long, long);
void mui_rect(long, long, long, long, long, long);
void mui_fill(long, long, long, long, long, long, long);
void mui_stroke(long, long, long, long, long, long, long, long);
void mui_shadow(long, long, long, long, long, long, long, long);
void mui_line(long, long, long, long, long, long, long);
long mui_measure(const char *, long);
void mui_text(long, long, const char *, long, long);
void mui_present(void);
long mui_software_present(void);
long mui_snapshot(const char *);
long mui_pixel(long, long);
long mui_draw_stat(long);

void mui_window_present(const unsigned char *p, long w, long h) { (void)p; (void)w; (void)h; }
void mui_window_submit(const MuiVertex *v, size_t n, const unsigned char *a, int aw, int ah, uint64_t r, int w, int h) {
    (void)v; (void)n; (void)a; (void)aw; (void)ah; (void)r; (void)w; (void)h;
}
void mui_window_bitmap(const unsigned char *p, int w, int h, uint64_t r) { (void)p; (void)w; (void)h; (void)r; }

static const long EXTREMES[] = {LONG_MIN, LONG_MIN + 1, -9000000000L, INT_MIN, -8193, -1, 0, 1, 7,
                                8192, 8193, INT_MAX, 9000000000L, LONG_MAX - 1, LONG_MAX};
#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static int fail(const char *message) { fprintf(stderr, "sanitize: %s\n", message); return 1; }

static void shapes(void) {
    for (size_t i = 0; i < COUNT(EXTREMES); i++) {
        for (size_t j = 0; j < COUNT(EXTREMES); j++) {
            long a = EXTREMES[i], b = EXTREMES[j];
            mui_rect(a, b, b, a, a, b);
            mui_fill(b, a, a, b, b, a, a);
            mui_stroke(a, a, b, b, a, b, a, b);
            mui_shadow(a, b, a, b, b, 64, a, b);
            mui_line(a, b, b, a, 1, a, 255);
            mui_line(a, a, b, b, 256, b, b);
            mui_bitmap(a, b, b, a);
            mui_clip(a, b, a, b);
            mui_pixel(a, b);
        }
    }
}

/* Extreme geometry, invalid surfaces and use after release. */
static int geometry(void) {
    for (size_t i = 0; i < COUNT(EXTREMES); i++)
        for (size_t j = 0; j < COUNT(EXTREMES); j++) {
            long w = EXTREMES[i], h = EXTREMES[j];
            int valid = w >= 1 && h >= 1 && w <= 8192 && h <= 8192;
            if (!valid && mui_surface(w, h)) return fail("accepted an invalid surface size");
        }
    shapes();                                   /* no surface yet */
    if (mui_software_present() || mui_snapshot("/nonexistent/x.png")) return fail("rasterized without a surface");
    if (!mui_surface(64, 48)) return 2;         /* no usable font: skip */
    shapes();
    mui_clip(0, 0, 64, 48);
    shapes();
    if (!mui_software_present()) return fail("cannot rasterize a valid surface");
    if (mui_snapshot("/nonexistent/directory/x.png")) return fail("snapshot to an unwritable path succeeded");
    if (mui_pixel(64, 0) != -1 || mui_pixel(0, 48) != -1 || mui_pixel(-1, -1) != -1) return fail("pixel outside the surface");
    mui_present();
    mui_release();
    shapes();                                   /* after release */
    mui_software_present();
    if (!mui_surface(1, 1)) return fail("cannot recreate the surface after release");
    shapes();
    mui_software_present();
    mui_release();
    return 0;
}

/* Invalid bitmap uploads, resizes and scaling into tiny or huge rectangles. */
static int bitmap(void) {
    static unsigned char rgba[4096 * 4];
    for (size_t i = 0; i < sizeof(rgba); i++) rgba[i] = (unsigned char)(i * 37);
    if (mui_bitmap_upload(NULL, 2, 2)) return fail("accepted a null bitmap");
    for (size_t i = 0; i < COUNT(EXTREMES); i++)
        for (size_t j = 0; j < COUNT(EXTREMES); j++) {
            long w = EXTREMES[i], h = EXTREMES[j];
            if ((w < 1 || h < 1 || w > 4096 || h > 4096) && mui_bitmap_upload(rgba, w, h))
                return fail("accepted an invalid bitmap size");
        }
    if (!mui_surface(32, 32)) return 2;
    const long sizes[][2] = {{3, 2}, {1, 1}, {4096, 1}, {1, 4096}, {2, 3}};
    for (size_t s = 0; s < COUNT(sizes); s++) {
        if (!mui_bitmap_upload(rgba, sizes[s][0], sizes[s][1])) return fail("rejected a valid bitmap");
        mui_bitmap(0, 0, 32, 32); mui_bitmap(-5, -5, 1, 1); mui_bitmap(31, 31, 100000, 3);
        shapes();
        if (!mui_software_present()) return fail("cannot rasterize a bitmap");
    }
    mui_release();
    mui_bitmap(0, 0, 4, 4);
    if (!mui_surface(8, 8)) return fail("cannot recreate the surface after release");
    mui_bitmap(0, 0, 8, 8);
    mui_software_present();
    mui_release();
    return 0;
}

/* Malformed UTF-8, out-of-range sizes and glyph-atlas pressure. */
static int text(void) {
    static const char *const samples[] = {
        "", "plain", "\xc3", "\xe2\x82", "\xf0\x9f\x98", "\xff\xfe\xfd", "\x80\x80\x80", "\xc0\xaf",
        "\xe0\x80\xaf", "\xed\xa0\x80", "\xf4\x90\x80\x80", "\xf8\x88\x80\x80\x80", "a\xc3", "\xe2\x82\xac\xe2",
        "\xf0\x9f\x98\x80 emoji", "\xd7\xa9\xd7\x9c\xd7\x95\xd7\x9d", "tab\tnewline\ncarriage\r"};
    const long sizes[] = {LONG_MIN, -1, 0, 5, 6, 13, 96, 97, LONG_MAX};
    if (!mui_surface(200, 100)) return 2;
    for (size_t i = 0; i < COUNT(samples); i++)
        for (size_t j = 0; j < COUNT(sizes); j++) {
            long measured = mui_measure(samples[i], sizes[j]);
            if ((sizes[j] < 6 || sizes[j] > 96) && measured) return fail("measured text at an invalid size");
            mui_text(5, 5, samples[i], sizes[j], 0x223344);
            mui_text(LONG_MIN, LONG_MAX, samples[i], sizes[j], -1);
        }
    if (mui_measure(NULL, 13)) return fail("measured a null string");
    mui_text(0, 0, NULL, 13, 0);
    size_t length = 100000;
    char *long_text = malloc(length + 1);
    if (!long_text) return fail("cannot allocate the long string");
    for (size_t i = 0; i < length; i++) long_text[i] = (char)(33 + i % 90);
    long_text[length] = 0;
    mui_measure(long_text, 13);
    mui_text(0, 50, long_text, 13, 0);
    free(long_text);
    /* Distinct codepoints at many sizes overflow the glyph table and the atlas. */
    char glyph[5];
    for (long px = 6; px <= 96; px += 3) {
        for (unsigned c = 0x20; c < 0x3000; c += 7) {
            if (c >= 0xd800 && c <= 0xdfff) continue;
            if (c < 0x80) { glyph[0] = (char)c; glyph[1] = 0; }
            else if (c < 0x800) { glyph[0] = (char)(0xc0 | c >> 6); glyph[1] = (char)(0x80 | (c & 63)); glyph[2] = 0; }
            else { glyph[0] = (char)(0xe0 | c >> 12); glyph[1] = (char)(0x80 | ((c >> 6) & 63)); glyph[2] = (char)(0x80 | (c & 63)); glyph[3] = 0; }
            mui_text((long)(c % 200), (long)(c % 100), glyph, px, (long)c);
        }
        mui_software_present();
        if (!mui_surface(200, 100)) return fail("cannot reset the surface");
    }
    mui_software_present();
    mui_release();
    return 0;
}

/* MAYUI_FONT points at a malformed file; the adapter must reject it without
 * reading out of bounds, then fall back to a system font if one exists. */
static int font(void) {
    long ok = mui_surface(64, 32);
    mui_measure("font", 13);
    mui_text(0, 0, "font \xe2\x82\xac", 13, 0);
    mui_software_present();
    mui_release();
    printf("fallback %s\n", ok ? "font" : "none");
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) return fail("usage: sanitize geometry|bitmap|text|font");
    if (!strcmp(argv[1], "geometry")) return geometry();
    if (!strcmp(argv[1], "bitmap")) return bitmap();
    if (!strcmp(argv[1], "text")) return text();
    if (!strcmp(argv[1], "font")) return font();
    return fail("unknown case");
}
