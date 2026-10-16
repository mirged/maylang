/* Sokol window/input and batched GPU rendering of Maylang UI draw packets.
 * Linux only: a worker owns sapp_run and all Sokol/GL calls. The public ABI
 * remains synchronous so Maylang applications can keep their open/poll loop.
 * Widgets and layout stay in Maylang; Sokol renders analytic shapes and a glyph atlas.
 */
#define SOKOL_IMPL
#define SOKOL_NO_ENTRY
#define SOKOL_GLCORE
#include "vendor/sokol_app.h"
#include "vendor/sokol_gfx.h"
#include "vendor/sokol_glue.h"
#include "gpu.h"

#include <locale.h>
#include <pthread.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include <X11/Xatom.h>
#include <limits.h>

typedef struct {
    int64_t kind, a, b, modifiers;
    char text[128];
} MuiEvent;

typedef struct EventNode {
    MuiEvent value;
    struct EventNode *next;
} EventNode;

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static pthread_t worker;
static int started, running, ready, stopping;
static int width, height, cursor, cursor_dirty, paste_requested;
static char *initial_title, *title_request, *copy_request;
static char paste[16384];
static MuiVertex *packet_vertices;
static size_t packet_count, packet_capacity;
static unsigned char *packet_image;
static size_t packet_image_capacity;
static int surface_width, surface_height, packet_width, packet_height, packet_channels;
static uint64_t packet_revision, packet_geometry_revision;
static uint64_t frame_serial;
static unsigned char *packet_bitmap;
static int bitmap_width, bitmap_height;
static uint64_t bitmap_revision;
static unsigned char held_keys[SAPP_MAX_KEYCODES], pressed_keys[SAPP_MAX_KEYCODES];
static int has_focus;
static char renderer[256];
static EventNode *first, *last;
static MuiEvent event;

static void log_message(const char *tag, uint32_t level, uint32_t item,
                        const char *message, uint32_t line, const char *file, void *user) {
    (void)file; (void)user;
    fprintf(stderr, "mayui: %s:%u (%u): %s\n", tag, line, item, message ? message : "Sokol error");
    if (level == 0) abort();
}

/* Called with mutex held. Only adjacent transient events may be coalesced;
 * clicks/keys must retain their order relative to mouse and resize events. */
static void enqueue(MuiEvent value) {
    if (!value.kind) return;
    if (last && value.kind >= 2 && value.kind <= 4 && last->value.kind == value.kind) {
        last->value = value;
    } else {
        EventNode *node = malloc(sizeof(*node));
        if (!node) { stopping = 1; pthread_cond_broadcast(&changed); return; }
        *node = (EventNode){.value = value};
        if (last) last->next = node;
        else first = node;
        last = node;
    }
    pthread_cond_broadcast(&changed);
}

/* Preserve dispatch's published raw-event values, including its legacy key
 * numbers and Shift=1 / Control=4 modifier bits, without exposing Sokol enums. */
static int64_t key_number(sapp_keycode key) {
    if (key >= SAPP_KEYCODE_A && key <= SAPP_KEYCODE_Z) return 'a' + key - SAPP_KEYCODE_A;
    switch (key) {
        case SAPP_KEYCODE_SPACE: return 32;
        case SAPP_KEYCODE_TAB: return 65289;
        case SAPP_KEYCODE_ENTER: case SAPP_KEYCODE_KP_ENTER: return 65293;
        case SAPP_KEYCODE_ESCAPE: return 65307;
        case SAPP_KEYCODE_BACKSPACE: return 65288;
        case SAPP_KEYCODE_DELETE: return 65535;
        case SAPP_KEYCODE_LEFT: return 65361;
        case SAPP_KEYCODE_RIGHT: return 65363;
        case SAPP_KEYCODE_HOME: return 65360;
        case SAPP_KEYCODE_END: return 65367;
        default: return 0;
    }
}

static void encode_utf8(uint32_t c, char *out) {
    if (c < 0x80) { out[0] = (char)c; }
    else if (c < 0x800) { out[0] = (char)(0xc0 | (c >> 6)); out[1] = (char)(0x80 | (c & 63)); }
    else if (c < 0x10000) {
        out[0] = (char)(0xe0 | (c >> 12)); out[1] = (char)(0x80 | ((c >> 6) & 63)); out[2] = (char)(0x80 | (c & 63));
    } else {
        out[0] = (char)(0xf0 | (c >> 18)); out[1] = (char)(0x80 | ((c >> 12) & 63));
        out[2] = (char)(0x80 | ((c >> 6) & 63)); out[3] = (char)(0x80 | (c & 63));
    }
}

static void handle_event(const sapp_event *input) {
    MuiEvent value = {0};
    value.modifiers = ((input->modifiers & SAPP_MODIFIER_SHIFT) ? 1 : 0) |
                      ((input->modifiers & SAPP_MODIFIER_CTRL) ? 4 : 0);
    switch (input->type) {
        case SAPP_EVENTTYPE_QUIT_REQUESTED:
            sapp_cancel_quit(); value.kind = 1; break;
        case SAPP_EVENTTYPE_RESTORED: case SAPP_EVENTTYPE_FOCUSED:
            value.kind = 2; break;
        case SAPP_EVENTTYPE_RESIZED:
            value.kind = 3; value.a = input->framebuffer_width; value.b = input->framebuffer_height; break;
        case SAPP_EVENTTYPE_MOUSE_MOVE: case SAPP_EVENTTYPE_MOUSE_LEAVE:
            value.kind = 4;
            value.a = input->type == SAPP_EVENTTYPE_MOUSE_LEAVE ? -1 : (int64_t)input->mouse_x;
            value.b = input->type == SAPP_EVENTTYPE_MOUSE_LEAVE ? -1 : (int64_t)input->mouse_y;
            break;
        case SAPP_EVENTTYPE_MOUSE_DOWN:
            value.kind = 5; value.a = (int64_t)input->mouse_x; value.b = (int64_t)input->mouse_y;
            value.modifiers = input->mouse_button == SAPP_MOUSEBUTTON_LEFT ? 1 : 0; break;
        case SAPP_EVENTTYPE_MOUSE_UP:
            value.kind = 8; value.a = (int64_t)input->mouse_x; value.b = (int64_t)input->mouse_y;
            value.modifiers = input->mouse_button == SAPP_MOUSEBUTTON_LEFT ? 1 : 0; break;
        case SAPP_EVENTTYPE_MOUSE_SCROLL:
            if (input->scroll_y != 0) { value.kind = 6; value.a = input->scroll_y > 0 ? -1 : 1; }
            break;
        case SAPP_EVENTTYPE_KEY_DOWN:
            value.a = key_number(input->key_code);
            /* Printable keys arrive as CHAR events. Ctrl shortcuts have no
             * text; Space is handled by CHAR too, to avoid double activation. */
            if (value.a && ((input->modifiers & SAPP_MODIFIER_CTRL) || value.a > 255)) value.kind = 7;
            break;
        case SAPP_EVENTTYPE_CHAR:
            if (!(input->modifiers & (SAPP_MODIFIER_CTRL | SAPP_MODIFIER_SUPER)) &&
                input->char_code >= 32 && input->char_code != 127 &&
                input->char_code <= 0x10ffff && !(input->char_code >= 0xd800 && input->char_code <= 0xdfff)) {
                value.kind = 7; value.a = input->char_code;
                encode_utf8(input->char_code, value.text);
            }
            break;
        default: break;
    }
    pthread_mutex_lock(&mutex);
    if (input->type == SAPP_EVENTTYPE_KEY_DOWN && (unsigned)input->key_code < (unsigned)SAPP_MAX_KEYCODES) {
        held_keys[input->key_code] = 1;
        if (!input->key_repeat && pressed_keys[input->key_code] < 255) pressed_keys[input->key_code]++;
    }
    if (input->type == SAPP_EVENTTYPE_KEY_UP && (unsigned)input->key_code < (unsigned)SAPP_MAX_KEYCODES) held_keys[input->key_code] = 0;
    if (input->type == SAPP_EVENTTYPE_FOCUSED) has_focus = 1;
    if (input->type == SAPP_EVENTTYPE_UNFOCUSED || input->type == SAPP_EVENTTYPE_ICONIFIED) {
        memset(held_keys, 0, sizeof(held_keys)); memset(pressed_keys, 0, sizeof(pressed_keys)); has_focus = 0;
    }
    enqueue(value);
    pthread_mutex_unlock(&mutex);
}

static void init(void) {
    /* Window-manager metadata isn't part of sapp_desc. Keep the application's
     * identity, PID discovery and minimum size through Sokol's public handles. */
    Display *display = (Display *)sapp_x11_get_display();
    Window window = (Window)(uintptr_t)sapp_x11_get_window();
    XClassHint klass = {"mayui", "MayUI"};
    XSetClassHint(display, window, &klass);
    unsigned long pid = (unsigned long)getpid();
    XChangeProperty(display, window, XInternAtom(display, "_NET_WM_PID", False),
                    XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&pid, 1);
    XSizeHints hints = {.flags = PMinSize, .min_width = 480, .min_height = 360};
    XSetWMNormalHints(display, window, &hints);
    sg_setup(&(sg_desc){.environment = sglue_environment(), .logger.func = log_message});
    gpu_setup();
    snprintf(renderer, sizeof(renderer), "%s / OpenGL · %s", getenv("MAYUI_RENDERER") && !strcmp(getenv("MAYUI_RENDERER"), "cpu") ? "CPU raster + Sokol" : "Sokol GPU", (const char *)glGetString(GL_RENDERER));
    pthread_mutex_lock(&mutex);
    ready = 1;
    enqueue((MuiEvent){.kind = 3, .a = sapp_width(), .b = sapp_height()});
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&mutex);
}

static void frame(void) {
    /* Limit the loop on displays (including Xvfb) without working vsync. */
    static struct timespec previous;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    int64_t elapsed = (int64_t)(now.tv_sec - previous.tv_sec) * 1000000000 + now.tv_nsec - previous.tv_nsec;
    if (elapsed >= 0 && elapsed < 16000000) {
        struct timespec delay = {.tv_nsec = (long)(16000000 - elapsed)};
        nanosleep(&delay, NULL);
    }
    clock_gettime(CLOCK_MONOTONIC, &previous);

    pthread_mutex_lock(&mutex);
    if (stopping) { sapp_quit(); pthread_mutex_unlock(&mutex); return; }
    if (title_request) { sapp_set_window_title(title_request); free(title_request); title_request = NULL; }
    if (cursor_dirty) {
        const sapp_mouse_cursor cursors[] = {SAPP_MOUSECURSOR_DEFAULT, SAPP_MOUSECURSOR_POINTING_HAND, SAPP_MOUSECURSOR_IBEAM};
        sapp_set_mouse_cursor(cursors[cursor]); cursor_dirty = 0;
    }
    if (copy_request) { sapp_set_clipboard_string(copy_request); free(copy_request); copy_request = NULL; }
    if (paste_requested) {
        snprintf(paste, sizeof(paste), "%s", sapp_get_clipboard_string()); paste_requested = 0;
    }
    pthread_cond_broadcast(&changed);
    gpu_bitmap(packet_bitmap, bitmap_width, bitmap_height, bitmap_revision);
    gpu_upload(packet_vertices, packet_count, packet_image, packet_width, packet_height, packet_channels, packet_revision, packet_geometry_revision);
    sg_begin_pass(&(sg_pass){
        .swapchain = sglue_swapchain(),
        .action.colors[0] = {.load_action = SG_LOADACTION_CLEAR, .clear_value = {0.973f, 0.98f, 0.988f, 1}}
    });
    gpu_draw(packet_count, surface_width, surface_height);
    sg_end_pass(); sg_commit();
    frame_serial++;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&mutex);
}

static void cleanup(void) { gpu_shutdown(); sg_shutdown(); }

static void *run(void *unused) {
    (void)unused;
    sapp_run(&(sapp_desc){
        .init_cb = init, .frame_cb = frame, .event_cb = handle_event, .cleanup_cb = cleanup,
        .width = width, .height = height, .window_title = initial_title,
        .enable_clipboard = true, .clipboard_size = sizeof(paste),
        .logger.func = log_message
    });
    pthread_mutex_lock(&mutex);
    running = 0;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&mutex);
    return NULL;
}

void mui_window_close(void) {
    if (!started) return;
    pthread_mutex_lock(&mutex);
    stopping = 1;
    pthread_mutex_unlock(&mutex);
    pthread_join(worker, NULL);
    while (first) { EventNode *next = first->next; free(first); first = next; }
    last = NULL;
    memset(held_keys, 0, sizeof(held_keys)); memset(pressed_keys, 0, sizeof(pressed_keys)); has_focus = 0;
    free(packet_bitmap); packet_bitmap=NULL; bitmap_width=bitmap_height=0; bitmap_revision=0;
    free(initial_title); initial_title = NULL;
    free(title_request); title_request = NULL;
    free(copy_request); copy_request = NULL;
    free(packet_vertices); packet_vertices = NULL; packet_count = packet_capacity = 0;
    free(packet_image); packet_image = NULL; packet_image_capacity = 0;
    packet_width = packet_height = packet_channels = 0; packet_revision = 0; renderer[0] = 0;
    surface_width = surface_height = 0;
    started = ready = stopping = cursor = cursor_dirty = paste_requested = 0;
    paste[0] = 0;
}

long mui_window_open(long w, long h, const char *title) {
    mui_window_close();
    if (w < 1 || h < 1 || w > 8192 || h > 8192) return 0;
    /* Sokol treats an unavailable display as fatal. Preflight it to preserve
     * ui.open's recoverable failure, before entering the Sokol-owned loop. */
    XInitThreads();
    Display *probe = XOpenDisplay(NULL);
    if (!probe) return 0;
    XCloseDisplay(probe);
    setlocale(LC_CTYPE, "");
    initial_title = strdup(title);
    if (!initial_title) return 0;
    width = (int)w; height = (int)h; running = 1;
    if (pthread_create(&worker, NULL, run, NULL)) {
        running = 0; free(initial_title); initial_title = NULL; return 0;
    }
    started = 1;
    pthread_mutex_lock(&mutex);
    while (running && !ready) pthread_cond_wait(&changed, &mutex);
    int result = ready;
    pthread_mutex_unlock(&mutex);
    return result;
}

void mui_window_title(const char *title) {
    pthread_mutex_lock(&mutex);
    if (running) { free(title_request); title_request = strdup(title); }
    pthread_mutex_unlock(&mutex);
}

void mui_window_cursor(long kind) {
    if (kind < 0 || kind > 2) return;
    pthread_mutex_lock(&mutex);
    cursor = (int)kind; cursor_dirty = 1;
    pthread_mutex_unlock(&mutex);
}

void mui_window_copy(const char *text) {
    if (strlen(text) >= sizeof(paste)) return;
    pthread_mutex_lock(&mutex);
    if (running) {
        copy_request = strdup(text);
        while (running && copy_request) pthread_cond_wait(&changed, &mutex);
    }
    pthread_mutex_unlock(&mutex);
}

const char *mui_window_paste(void) {
    pthread_mutex_lock(&mutex);
    if (running) {
        paste_requested = 1;
        while (running && paste_requested) pthread_cond_wait(&changed, &mutex);
    }
    pthread_mutex_unlock(&mutex);
    return paste;
}

static void submit_packet(const MuiVertex *data, size_t count, const unsigned char *image,
                          int iw, int ih, int channels, uint64_t revision, int w, int h) {
    if (w < 1 || h < 1 || w > 8192 || h > 8192 || count > INT_MAX) return;
    pthread_mutex_lock(&mutex);
    if (running) {
        if (count > packet_capacity) {
            MuiVertex *next = realloc(packet_vertices, count * sizeof(*next));
            if (!next) { pthread_mutex_unlock(&mutex); return; }
            packet_vertices = next; packet_capacity = count;
        }
        if (revision != packet_revision || channels != packet_channels || iw != packet_width || ih != packet_height) {
            size_t bytes = (size_t)iw * ih * channels;
            if (bytes > packet_image_capacity) {
                unsigned char *next = realloc(packet_image, bytes);
                if (!next) { pthread_mutex_unlock(&mutex); return; }
                packet_image = next; packet_image_capacity = bytes;
            }
            if (bytes && image) memcpy(packet_image, image, bytes);
            packet_revision = revision; packet_width = iw; packet_height = ih; packet_channels = channels;
        }
        int geometry_dirty = count != packet_count || w != surface_width || h != surface_height ||
            (count && memcmp(packet_vertices, data, count * sizeof(*data)));
        if (geometry_dirty) {
            if (count) memcpy(packet_vertices, data, count * sizeof(*data));
            packet_geometry_revision++;
        }
        packet_count = count; surface_width = w; surface_height = h;
    }
    pthread_mutex_unlock(&mutex);
}
void mui_window_submit(const MuiVertex *data, size_t count, const unsigned char *atlas,
                       int aw, int ah, uint64_t revision, int w, int h) {
    submit_packet(data, count, atlas, aw, ah, 1, revision, w, h);
}
/* Legacy RGB presentation remains useful to FFI clients and adapter tests. */
void mui_window_present(const unsigned char *rgb, long w, long h) {
    if (!rgb || w < 1 || h < 1 || w > 8192 || h > 8192) return;
    unsigned char *rgba = malloc((size_t)w * h * 4);
    if (!rgba) return;
    for (size_t i = 0; i < (size_t)w * h; i++) {
        rgba[i * 4] = rgb[i * 3]; rgba[i * 4 + 1] = rgb[i * 3 + 1];
        rgba[i * 4 + 2] = rgb[i * 3 + 2]; rgba[i * 4 + 3] = 255;
    }
    const MuiVertex quad[] = {
        {.position={0,0}, .uv={0,0}, .shape[3]=3}, {.position={w,0}, .uv={w,0}, .shape[3]=3},
        {.position={w,h}, .uv={w,h}, .shape[3]=3}, {.position={0,0}, .uv={0,0}, .shape[3]=3},
        {.position={w,h}, .uv={w,h}, .shape[3]=3}, {.position={0,h}, .uv={0,h}, .shape[3]=3}
    };
    static uint64_t raw_revision;
    submit_packet(quad, 6, rgba, (int)w, (int)h, 4, ++raw_revision, (int)w, (int)h);
    free(rgba);
}
const char *mui_window_renderer(void) { return renderer; }

void *mui_window_event_timeout(long timeout_ms) {
    if (timeout_ms < 0) timeout_ms = 0;
    if (timeout_ms > 1000) timeout_ms = 1000;
    memset(&event, 0, sizeof(event));
    pthread_mutex_lock(&mutex);
    uint64_t previous_frame = frame_serial;
    struct timespec deadline;
    clock_gettime(CLOCK_REALTIME, &deadline);
    deadline.tv_nsec += (timeout_ms % 1000) * 1000000;
    deadline.tv_sec += timeout_ms / 1000;
    if (deadline.tv_nsec >= 1000000000) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000; }
    while (timeout_ms && !first && running && !stopping && frame_serial == previous_frame) {
        if (pthread_cond_timedwait(&changed, &mutex, &deadline)) break;
    }
    if (first) {
        EventNode *node = first;
        event = node->value; first = node->next;
        if (!first) last = NULL;
        free(node);
    } else if (!running || stopping) event.kind = 1;
    pthread_mutex_unlock(&mutex);
    return &event;
}

void *mui_window_event(void) { return mui_window_event_timeout(50); }

const char *mui_window_text(void) { return event.text; }

/* Sokol key codes are stable ASCII for letters and 256+ for special keys. */
long mui_window_key_down(long key) {
    pthread_mutex_lock(&mutex);
    long result = key >= 0 && key < SAPP_MAX_KEYCODES ? held_keys[key] : 0;
    pthread_mutex_unlock(&mutex);
    return result;
}
long mui_window_focused(void) {
    pthread_mutex_lock(&mutex); long result=has_focus; pthread_mutex_unlock(&mutex); return result;
}
void mui_window_bitmap(const unsigned char *data, int w, int h, uint64_t revision) {
    if (!data || w<1 || h<1 || w>4096 || h>4096) return;
    pthread_mutex_lock(&mutex);
    if (running && revision != bitmap_revision) {
        unsigned char *next=realloc(packet_bitmap,(size_t)w*h*4);
        if (next) {
            packet_bitmap=next; memcpy(next,data,(size_t)w*h*4);
            bitmap_width=w; bitmap_height=h; bitmap_revision=revision;
        }
    }
    pthread_mutex_unlock(&mutex);
}

long mui_window_key_pressed(long key) {
    pthread_mutex_lock(&mutex);
    long result = key >= 0 && key < SAPP_MAX_KEYCODES && pressed_keys[key] != 0;
    if (result) pressed_keys[key]--;
    pthread_mutex_unlock(&mutex);
    return result;
}
