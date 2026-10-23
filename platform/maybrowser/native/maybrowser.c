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
#include <curl/curl.h>

#define MB_MAX_RESPONSE_BYTES ((size_t)16 * 1024 * 1024)
#define MB_MAX_IMAGE_DIMENSION 8192
#define MB_MAX_IMAGE_PIXELS ((size_t)16 * 1024 * 1024)

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
static char g_error[256];

static void mb_error(const char *message) {
    snprintf(g_error, sizeof(g_error), "%s", message);
}

const char *mb_last_error(void) { return g_error; }

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

static int mb_image_size(int w, int h, size_t *bytes) {
    if (w <= 0 || h <= 0 || w > MB_MAX_IMAGE_DIMENSION || h > MB_MAX_IMAGE_DIMENSION ||
        (size_t)w > MB_MAX_IMAGE_PIXELS / (size_t)h ||
        (size_t)w > (SIZE_MAX - 16) / 4 / (size_t)h) {
        mb_error("Image exceeds 8192 pixels per axis or 16777216 decoded pixels.");
        return 0;
    }
    *bytes = (size_t)w * (size_t)h * 4;
    return 1;
}

/* Probe dimensions before decoding. Returns int32 w,h,4,0 then RGBA bytes. */
void *mb_image_load_mem(const void *data, int len) {
    int w, h, comp;
    size_t bytes;
    mb_error("");
    if (len < 0 || (size_t)len > MB_MAX_RESPONSE_BYTES) {
        mb_error("Encoded image exceeds the 16 MiB limit.");
        return NULL;
    }
    if (!data || len == 0 ||
        !stbi_info_from_memory((const stbi_uc *)data, len, &w, &h, &comp)) {
        mb_error("Invalid or unsupported image header.");
        return NULL;
    }
    if (!mb_image_size(w, h, &bytes)) return NULL;
    unsigned char *px = stbi_load_from_memory((const stbi_uc *)data, len, &w, &h, &comp, 4);
    if (!px) { mb_error("Invalid or unsupported image data."); return NULL; }
    if (!mb_image_size(w, h, &bytes)) { stbi_image_free(px); return NULL; }
    unsigned char *out = (unsigned char *)malloc(16 + bytes);
    if (!out) { mb_error("Out of memory loading image."); stbi_image_free(px); return NULL; }
    int *hdr = (int *)out;
    hdr[0] = w; hdr[1] = h; hdr[2] = 4; hdr[3] = 0;
    memcpy(out + 16, px, bytes);
    stbi_image_free(px);
    return out;
}

void *mb_image_load(const char *path) {
    mb_error("");
    FILE *fp = fopen(path, "rb");
    if (!fp) { mb_error("Could not read image file."); return NULL; }
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); mb_error("Could not size image file."); return NULL; }
    long n = ftell(fp);
    if (n < 0 || (size_t)n > MB_MAX_RESPONSE_BYTES) {
        fclose(fp); mb_error("Encoded image exceeds the 16 MiB limit."); return NULL;
    }
    rewind(fp);
    unsigned char *data = (unsigned char *)malloc(n > 0 ? (size_t)n : 1);
    if (!data) { fclose(fp); mb_error("Out of memory reading image."); return NULL; }
    size_t got = fread(data, 1, (size_t)n, fp);
    fclose(fp);
    if (got != (size_t)n) { free(data); mb_error("Could not read image file."); return NULL; }
    /* Decode the same bounded snapshot that was probed, even if the file changes. */
    void *out = mb_image_load_mem(data, (int)n);
    free(data);
    return out;
}

int mb_png_write(const char *path, const void *data, int w, int h, int comp) {
    return stbi_write_png(path, w, h, comp, data, w * comp);
}

void mb_free(void *p) { free(p); }

void *mb_alloc(long n) { return calloc(1, (size_t)(n > 0 ? n : 1)); }

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
    if (url && !curl_url_set(url, CURLUPART_URL, base, 0) &&
        !curl_url_set(url, CURLUPART_URL, reference, 0) &&
        !curl_url_get(url, CURLUPART_URL, &resolved, 0))
        result = strdup(resolved);
    curl_free(resolved);
    if (url) curl_url_cleanup(url);
    return result ? result : "";
}

typedef struct {
    unsigned char *data;
    size_t len, capacity;
} MBResponse;

/* libcurl supplies decoded bytes here, including for gzip/chunked responses. */
static size_t mb_receive(char *data, size_t size, size_t count, void *user) {
    MBResponse *response = (MBResponse *)user;
    if ((size && count > SIZE_MAX / size) || size * count > MB_MAX_RESPONSE_BYTES - response->len) {
        mb_error("HTTP response exceeds the 16 MiB decoded-byte limit.");
        return 0;
    }
    size_t n = size * count;
    if (!n) return 0;
    size_t needed = response->len + n + 1;
    if (needed > response->capacity) {
        size_t capacity = response->capacity ? response->capacity : 4096;
        while (capacity < needed) {
            capacity *= 2;
            if (capacity > MB_MAX_RESPONSE_BYTES + 1) capacity = MB_MAX_RESPONSE_BYTES + 1;
        }
        unsigned char *next = (unsigned char *)realloc(response->data, capacity);
        if (!next) { mb_error("Out of memory receiving HTTP response."); return 0; }
        response->data = next;
        response->capacity = capacity;
    }
    memcpy(response->data + response->len, data, n);
    response->len += n;
    response->data[response->len] = 0;
    return n;
}

/* Returns the bounded response bytes, NULL on failure. */
static void *mb_fetch_mem(const char *url, size_t *out_len) {
    static int inited = 0;
    if (!inited) {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
            mb_error("Could not initialize HTTP support."); return NULL;
        }
        inited = 1;
    }
    CURL *h = curl_easy_init();
    if (!h) { mb_error("Could not initialize HTTP request."); return NULL; }
    MBResponse response = {0};
    if (curl_easy_setopt(h, CURLOPT_URL, url) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_WRITEFUNCTION, mb_receive) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_WRITEDATA, &response) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_FOLLOWLOCATION, 1L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_MAXREDIRS, 8L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_TIMEOUT, 30L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_CONNECTTIMEOUT, 8L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_FAILONERROR, 1L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_NOSIGNAL, 1L) != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_USERAGENT, "MayBrowser/0.1") != CURLE_OK ||
        curl_easy_setopt(h, CURLOPT_ACCEPT_ENCODING, "") != CURLE_OK) {
        curl_easy_cleanup(h); mb_error("Could not configure HTTP request."); return NULL;
    }
    CURLcode rc = curl_easy_perform(h);
    curl_easy_cleanup(h);
    if (rc != CURLE_OK) {
        if (!g_error[0]) mb_error(curl_easy_strerror(rc));
        free(response.data); return NULL;
    }
    if (!response.data) response.data = (unsigned char *)calloc(1, 1);
    if (!response.data) { mb_error("Out of memory receiving HTTP response."); return NULL; }
    *out_len = response.len;
    return response.data;
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
    size_t capacity = n / 4 * 3 + 3;
    if (capacity > MB_MAX_RESPONSE_BYTES) capacity = MB_MAX_RESPONSE_BYTES;
    unsigned char *out = (unsigned char *)malloc(capacity);
    if (!out) { mb_error("Out of memory decoding base64 data."); return NULL; }
    size_t o = 0;
    unsigned int acc = 0;
    int bits = 0;
    for (size_t i = 0; i < n; i++) {
        int c = (unsigned char)in[i];
        if (c == '=') break;
        int v = rev[c];
        if (v < 0) continue;
        acc = (acc << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (o == MB_MAX_RESPONSE_BYTES) {
                free(out); mb_error("Decoded data exceeds the 16 MiB limit."); return NULL;
            }
            out[o++] = (unsigned char)((acc >> bits) & 0xFF);
        }
    }
    *out_len = o;
    return out;
}

/*
 * Fetches a URL (http/https or data:) and writes the bytes to `path`.
 * Returns 0 on success, non-zero on failure.
 */
int mb_fetch_file(const char *url, const char *path) {
    mb_error("");
    unsigned char *data = NULL;
    size_t len = 0;
    if (strncmp(url, "data:", 5) == 0) {
        const char *comma = strchr(url, ',');
        if (!comma) { mb_error("Invalid data URL."); return 1; }
        const char *payload = comma + 1;
        size_t pn = strlen(payload);
        if (strstr(url, ";base64") && strstr(url, ";base64") < comma) {
            data = mb_b64_decode(payload, pn, &len);
        } else {
            /* percent-decoded plain text */
            size_t capacity = pn < MB_MAX_RESPONSE_BYTES ? pn : MB_MAX_RESPONSE_BYTES;
            data = (unsigned char *)malloc(capacity + 1);
            if (!data) { mb_error("Out of memory decoding data URL."); return 1; }
            size_t o = 0;
            for (size_t i = 0; i < pn; i++) {
                if (o == MB_MAX_RESPONSE_BYTES) {
                    free(data); mb_error("Decoded data exceeds the 16 MiB limit."); return 1;
                }
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
    if (!fp) { free(data); mb_error("Could not write downloaded resource."); return 1; }
    size_t wrote = len ? fwrite(data, 1, len, fp) : 0;
    int closed = fclose(fp);
    free(data);
    if (wrote != len || closed != 0) { mb_error("Could not write downloaded resource."); return 1; }
    return 0;
}

/* Decode a base64 string into an image and return the RGBA header buffer. */
void *mb_image_load_b64(const char *b64) {
    mb_error("");
    size_t n = strlen(b64);
    size_t len = 0;
    unsigned char *raw = mb_b64_decode(b64, n, &len);
    if (!raw) return NULL;
    void *img = mb_image_load_mem(raw, (int)len);
    free(raw);
    return img;
}
