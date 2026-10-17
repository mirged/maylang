/*
 * maybrowser native support shim.
 *
 * MayBrowser's HTML/CSS parsing, cascade, layout and painting are written in
 * Maylang.  A few pixel-level jobs are delegated to this small shared library
 * so that the Maylang side can stay free of fragile C struct layout:
 *
 *   - TrueType glyph rasterisation and metrics   (stb_truetype)
 *   - image decoding for <img>                    (stb_image)
 *   - PNG encoding of the rendered frame          (stb_image_write)
 *   - HTTP/HTTPS fetching of documents/images     (libcurl)
 *
 * Every function uses a flat, struct-free ABI: out-parameters are returned as
 * buffers with a small 32-bit header, so Maylang only needs load32/load64.
 *
 * The bundled stb headers are public domain / MIT (see vendor/).
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#define STB_TRUETYPE_IMPLEMENTATION
#include "vendor/stb_truetype.h"
#define STB_IMAGE_IMPLEMENTATION
#include "vendor/stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

#define MB_MAX_FONTS 64

typedef struct {
    stbtt_fontinfo info;
    unsigned char *data;
    int used;
} MBFont;

static MBFont g_fonts[MB_MAX_FONTS];

static float mb_scale(const MBFont *f, double px) {
    return stbtt_ScaleForPixelHeight(&f->info, (float)px);
}

int mb_font_load(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return -1;
    fseek(fp, 0, SEEK_END);
    long n = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    if (n <= 0) { fclose(fp); return -1; }
    unsigned char *buf = (unsigned char *)malloc((size_t)n);
    if (!buf) { fclose(fp); return -1; }
    if (fread(buf, 1, (size_t)n, fp) != (size_t)n) { fclose(fp); free(buf); return -1; }
    fclose(fp);
    int offset = stbtt_GetFontOffsetForIndex(buf, 0);
    if (offset < 0) { free(buf); return -1; }
    for (int i = 0; i < MB_MAX_FONTS; i++) {
        if (!g_fonts[i].used) {
            if (!stbtt_InitFont(&g_fonts[i].info, buf, offset)) { free(buf); return -1; }
            g_fonts[i].data = buf;
            g_fonts[i].used = 1;
            return i;
        }
    }
    free(buf);
    return -1;
}

void mb_font_free(int id) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return;
    free(g_fonts[id].data);
    g_fonts[id].data = NULL;
    g_fonts[id].used = 0;
}

double mb_font_ascent(int id, double px) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return 0.0;
    int a, d, g;
    stbtt_GetFontVMetrics(&g_fonts[id].info, &a, &d, &g);
    return a * (double)mb_scale(&g_fonts[id], px);
}

double mb_font_descent(int id, double px) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return 0.0;
    int a, d, g;
    stbtt_GetFontVMetrics(&g_fonts[id].info, &a, &d, &g);
    return (-d) * (double)mb_scale(&g_fonts[id], px);
}

double mb_font_line_gap(int id, double px) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return 0.0;
    int a, d, g;
    stbtt_GetFontVMetrics(&g_fonts[id].info, &a, &d, &g);
    return g * (double)mb_scale(&g_fonts[id], px);
}

double mb_glyph_advance(int id, double px, unsigned int cp) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return 0.0;
    int adv, lsb;
    stbtt_GetCodepointHMetrics(&g_fonts[id].info, (int)cp, &adv, &lsb);
    return adv * (double)mb_scale(&g_fonts[id], px);
}

double mb_glyph_kern(int id, double px, unsigned int a, unsigned int b) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return 0.0;
    int k = stbtt_GetCodepointKernAdvance(&g_fonts[id].info, (int)a, (int)b);
    return k * (double)mb_scale(&g_fonts[id], px);
}

/* Returns a buffer: int32 w, h, xoff, yoff, then w*h 8-bit coverage samples. */
void *mb_glyph_bitmap(int id, double px, unsigned int cp) {
    if (id < 0 || id >= MB_MAX_FONTS || !g_fonts[id].used) return NULL;
    MBFont *f = &g_fonts[id];
    float s = stbtt_ScaleForPixelHeight(&f->info, (float)px);
    int x0, y0, x1, y1;
    stbtt_GetCodepointBitmapBox(&f->info, (int)cp, s, s, &x0, &y0, &x1, &y1);
    int w = x1 - x0;
    int h = y1 - y0;
    if (w < 0) w = 0;
    if (h < 0) h = 0;
    unsigned char *out = (unsigned char *)malloc(16 + (size_t)w * (size_t)h);
    if (!out) return NULL;
    int *hdr = (int *)out;
    hdr[0] = w; hdr[1] = h; hdr[2] = x0; hdr[3] = y0;
    if (w > 0 && h > 0) {
        memset(out + 16, 0, (size_t)w * (size_t)h);
        stbtt_MakeCodepointBitmap(&f->info, out + 16, w, h, w, s, s, (int)cp);
    }
    return out;
}

/* Returns a buffer: int32 w, h, channels, 0, then w*h*4 RGBA bytes. */
void *mb_image_load(const char *path) {
    int w, h, comp;
    unsigned char *px = stbi_load(path, &w, &h, &comp, 4);
    if (!px) return NULL;
    unsigned char *out = (unsigned char *)malloc(16 + (size_t)w * (size_t)h * 4);
    if (!out) { stbi_image_free(px); return NULL; }
    int *hdr = (int *)out;
    hdr[0] = w; hdr[1] = h; hdr[2] = 4; hdr[3] = 0;
    memcpy(out + 16, px, (size_t)w * (size_t)h * 4);
    stbi_image_free(px);
    return out;
}

void *mb_image_load_mem(const void *data, int len) {
    int w, h, comp;
    unsigned char *px = stbi_load_from_memory((const stbi_uc *)data, len, &w, &h, &comp, 4);
    if (!px) return NULL;
    unsigned char *out = (unsigned char *)malloc(16 + (size_t)w * (size_t)h * 4);
    if (!out) { stbi_image_free(px); return NULL; }
    int *hdr = (int *)out;
    hdr[0] = w; hdr[1] = h; hdr[2] = 4; hdr[3] = 0;
    memcpy(out + 16, px, (size_t)w * (size_t)h * 4);
    stbi_image_free(px);
    return out;
}

int mb_png_write(const char *path, const void *data, int w, int h, int comp) {
    return stbi_write_png(path, w, h, comp, data, w * comp);
}

void mb_free(void *p) { free(p); }

void *mb_alloc(long n) { return calloc(1, (size_t)(n > 0 ? n : 1)); }

/*
 * libcurl is used through a hand-declared ABI (the development headers are not
 * present on the host).  The default write callback is used: setting only
 * CURLOPT_WRITEDATA makes libcurl fwrite() into the FILE* we supply.
 */
typedef void CURL;
typedef int CURLcode;
typedef int CURLoption;
extern CURL *curl_easy_init(void);
extern CURLcode curl_easy_setopt(CURL *, CURLoption, ...);
extern CURLcode curl_easy_perform(CURL *);
extern void curl_easy_cleanup(CURL *);
extern CURLcode curl_global_init(long);
typedef void CURLU;
extern CURLU *curl_url(void);
extern int curl_url_set(CURLU *, int, const char *, unsigned);
extern int curl_url_get(CURLU *, int, char **, unsigned);
extern void curl_url_cleanup(CURLU *);
extern void curl_free(void *);

const char *mb_temp_file(void) {
    static char path[64];
    strcpy(path, "/tmp/maybrowser-XXXXXX");
    int fd = mkstemp(path);
    if (fd < 0) return "";
    close(fd);
    return path;
}

const char *mb_url_resolve(const char *base, const char *reference) {
    static char *result;
    free(result); result = NULL;
    CURLU *url = curl_url();
    char *resolved = NULL;
    if (url && !curl_url_set(url, 0, base, 0) &&
        !curl_url_set(url, 0, reference, 0) && !curl_url_get(url, 0, &resolved, 0))
        result = strdup(resolved);
    curl_free(resolved);
    if (url) curl_url_cleanup(url);
    return result ? result : "";
}

#define CURL_GLOBAL_DEFAULT 3L
#define CURLOPT_WRITEDATA 10001
#define CURLOPT_URL 10002
#define CURLOPT_USERAGENT 10018
#define CURLOPT_TIMEOUT 13
#define CURLOPT_FOLLOWLOCATION 52
#define CURLOPT_MAXREDIRS 68
#define CURLOPT_ACCEPT_ENCODING 10102
#define CURLOPT_NOSIGNAL 99
#define CURLOPT_FAILONERROR 45
#define CURLOPT_CONNECTTIMEOUT 78

/* Returns a buffer: uint64 length, then the response bytes. NULL on failure. */
static void *mb_fetch_mem(const char *url, size_t *out_len) {
    static int inited = 0;
    if (!inited) { curl_global_init(CURL_GLOBAL_DEFAULT); inited = 1; }
    CURL *h = curl_easy_init();
    if (!h) return NULL;
    char *buf = NULL;
    size_t sz = 0;
    FILE *ms = open_memstream(&buf, &sz);
    if (!ms) { curl_easy_cleanup(h); return NULL; }
    curl_easy_setopt(h, CURLOPT_URL, url);
    curl_easy_setopt(h, CURLOPT_WRITEDATA, ms);
    curl_easy_setopt(h, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(h, CURLOPT_MAXREDIRS, 8L);
    curl_easy_setopt(h, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(h, CURLOPT_CONNECTTIMEOUT, 8L);
    curl_easy_setopt(h, CURLOPT_FAILONERROR, 1L);
    curl_easy_setopt(h, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(h, CURLOPT_USERAGENT, "MayBrowser/0.1");
    curl_easy_setopt(h, CURLOPT_ACCEPT_ENCODING, "");
    CURLcode rc = curl_easy_perform(h);
    fflush(ms);
    fclose(ms);
    curl_easy_cleanup(h);
    if (rc != 0) { if (buf) free(buf); return NULL; }
    *out_len = sz;
    return buf;
}

static int mb_hexval(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static unsigned char *mb_b64_decode(const char *in, size_t n, size_t *out_len) {
    static const char *tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    int rev[256];
    for (int i = 0; i < 256; i++) rev[i] = -1;
    for (int i = 0; i < 64; i++) rev[(unsigned char)tbl[i]] = i;
    unsigned char *out = (unsigned char *)malloc(n / 4 * 3 + 4);
    if (!out) return NULL;
    size_t o = 0;
    int acc = 0, bits = 0;
    for (size_t i = 0; i < n; i++) {
        int c = (unsigned char)in[i];
        if (c == '=') break;
        int v = rev[c];
        if (v < 0) continue;
        acc = (acc << 6) | v;
        bits += 6;
        if (bits >= 8) { bits -= 8; out[o++] = (unsigned char)((acc >> bits) & 0xFF); }
    }
    *out_len = o;
    return out;
}

/*
 * Fetches a URL (http/https or data:) and writes the bytes to `path`.
 * Returns 0 on success, non-zero on failure.
 */
int mb_fetch_file(const char *url, const char *path) {
    unsigned char *data = NULL;
    size_t len = 0;
    if (strncmp(url, "data:", 5) == 0) {
        const char *comma = strchr(url, ',');
        if (!comma) return 1;
        const char *payload = comma + 1;
        size_t pn = strlen(payload);
        if (strstr(url, ";base64") && strstr(url, ";base64") < comma) {
            data = mb_b64_decode(payload, pn, &len);
        } else {
            /* percent-decoded plain text */
            data = (unsigned char *)malloc(pn + 1);
            if (!data) return 1;
            size_t o = 0;
            for (size_t i = 0; i < pn; i++) {
                if (payload[i] == '%' && i + 2 < pn) {
                    int hi = mb_hexval(payload[i + 1]);
                    int lo = mb_hexval(payload[i + 2]);
                    if (hi >= 0 && lo >= 0) { data[o++] = (unsigned char)(hi * 16 + lo); i += 2; continue; }
                }
                data[o++] = (unsigned char)payload[i];
            }
            len = o;
        }
    } else {
        data = (unsigned char *)mb_fetch_mem(url, &len);
    }
    if (!data) return 1;
    FILE *fp = fopen(path, "wb");
    if (!fp) { free(data); return 1; }
    size_t wrote = len ? fwrite(data, 1, len, fp) : 0;
    fclose(fp);
    free(data);
    return wrote == len ? 0 : 1;
}

/* Decode a base64 string into an image and return the RGBA header buffer. */
void *mb_image_load_b64(const char *b64) {
    size_t n = strlen(b64);
    size_t len = 0;
    unsigned char *raw = mb_b64_decode(b64, n, &len);
    if (!raw) return NULL;
    void *img = mb_image_load_mem(raw, (int)len);
    free(raw);
    return img;
}
