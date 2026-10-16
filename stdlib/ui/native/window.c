/* X11 presentation/input only. Layout, widgets and application logic are Maylang. 
 * Optimized: Direct 32-bit framebuffer packing (no XPutPixel), MotionNotify squashing, 60Hz poll.
 */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/cursorfont.h>
#include <X11/keysym.h>
#include <X11/Xatom.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <locale.h>
#include <sys/select.h>
#include <unistd.h>

static Display *display;
static Window window;
static GC gc;
static Atom wm_delete;
static XIM input_method;
static XIC input_context;
static Cursor cursors[3];
static XImage *image;
static char *clipboard;
static char *paste;
static int width, height;

/* Shift caches to avoid per-pixel while loops */
static int r_shift, g_shift, b_shift;
static int is_standard_rgb32;

static struct { int64_t kind, a, b, modifiers; char text[128]; } event;

static int calc_shift(unsigned long mask) {
    int shift = 0;
    if (!mask) return 0;
    while (!(mask & 1)) { shift++; mask >>= 1; }
    return shift;
}

void mui_window_close(void) {
    if (!display) return;
    if (image) { XDestroyImage(image); image = NULL; }
    if (input_context) { XDestroyIC(input_context); input_context = NULL; }
    if (input_method) { XCloseIM(input_method); input_method = NULL; }
    for (int i = 0; i < 3; i++) XFreeCursor(display, cursors[i]);
    XFreeGC(display, gc);
    XDestroyWindow(display, window);
    XCloseDisplay(display);
    display = NULL;
    free(clipboard); clipboard = NULL;
    free(paste); paste = NULL;
}

void mui_window_copy(const char *text) {
    if (!display) return;
    free(clipboard); clipboard = strdup(text);
    XSetSelectionOwner(display, XInternAtom(display, "CLIPBOARD", False), window, CurrentTime);
}

const char *mui_window_paste(void) {
    free(paste); paste = NULL;
    if (!display) return "";
    Atom selection = XInternAtom(display, "CLIPBOARD", False);
    if (XGetSelectionOwner(display, selection) == window) return clipboard ? clipboard : "";
    if (XGetSelectionOwner(display, selection) == None) selection = XA_PRIMARY;
    Atom property = XInternAtom(display, "MAYUI_PASTE", False);
    Atom utf8 = XInternAtom(display, "UTF8_STRING", False);
    XConvertSelection(display, selection, utf8, property, window, CurrentTime);
    XFlush(display);
    for (int attempt = 0; attempt < 20; attempt++) {
        XEvent e;
        if (XCheckTypedWindowEvent(display, window, SelectionNotify, &e)) {
            if (e.xselection.property == None) return "";
            Atom type; int format; unsigned long n, remaining; unsigned char *data = NULL;
            if (XGetWindowProperty(display, window, property, 0, 4096, True, AnyPropertyType,
                                   &type, &format, &n, &remaining, &data) == Success) {
                if (format == 8 && data) paste = strndup((char *)data, n);
                if (data) XFree(data);
            }
            return paste ? paste : "";
        }
        fd_set set; FD_ZERO(&set); FD_SET(ConnectionNumber(display), &set);
        struct timeval timeout = {0, 25000};
        select(ConnectionNumber(display) + 1, &set, NULL, NULL, &timeout);
        XEventsQueued(display, QueuedAfterReading);
    }
    return "";
}

long mui_window_open(long w, long h, const char *title) {
    mui_window_close();
    setlocale(LC_CTYPE, "");
    XSetLocaleModifiers("");
    display = XOpenDisplay(NULL);
    if (!display) return 0;
    int screen = DefaultScreen(display);
    width = (int)w; height = (int)h;
    window = XCreateSimpleWindow(display, RootWindow(display, screen), 0, 0,
                                width, height, 0, 0, 0xf8fafc);
    XStoreName(display, window, title);
    XClassHint klass = {"mayui", "MayUI"};
    XSetClassHint(display, window, &klass);
    unsigned long pid = getpid();
    XChangeProperty(display, window, XInternAtom(display, "_NET_WM_PID", False),
                    XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&pid, 1);
    XSizeHints hints = {0};
    hints.flags = PMinSize; hints.min_width = 480; hints.min_height = 360;
    XSetWMNormalHints(display, window, &hints);
    wm_delete = XInternAtom(display, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(display, window, &wm_delete, 1);
    XSelectInput(display, window, ExposureMask | StructureNotifyMask | KeyPressMask |
                 ButtonPressMask | PointerMotionMask | FocusChangeMask);
    gc = XCreateGC(display, window, 0, NULL);
    cursors[0] = XCreateFontCursor(display, XC_left_ptr);
    cursors[1] = XCreateFontCursor(display, XC_hand2);
    cursors[2] = XCreateFontCursor(display, XC_xterm);
    input_method = XOpenIM(display, NULL, NULL, NULL);
    if (input_method)
        input_context = XCreateIC(input_method, XNInputStyle, XIMPreeditNothing | XIMStatusNothing,
                                  XNClientWindow, window, XNFocusWindow, window, NULL);
    XMapWindow(display, window);
    XFlush(display);
    return 1;
}

void mui_window_title(const char *title) { if (display) XStoreName(display, window, title); }
void mui_window_cursor(long kind) {
    if (display && kind >= 0 && kind < 3) XDefineCursor(display, window, cursors[kind]);
}

void mui_window_present(const unsigned char *rgb, long w, long h) {
    if (!display || !rgb || w < 1 || h < 1) return;
    if (!image || image->width != w || image->height != h) {
        if (image) XDestroyImage(image);
        int screen = DefaultScreen(display);
        image = XCreateImage(display, DefaultVisual(display, screen), DefaultDepth(display, screen),
                             ZPixmap, 0, NULL, (unsigned int)w, (unsigned int)h, 32, 0);
        if (!image) return;
        image->data = malloc((size_t)h * image->bytes_per_line);
        if (!image->data) { XDestroyImage(image); image = NULL; return; }

        /* Precompute bitshifts once per image allocation instead of per pixel */
        r_shift = calc_shift(image->red_mask);
        g_shift = calc_shift(image->green_mask);
        b_shift = calc_shift(image->blue_mask);
        is_standard_rgb32 = (image->bits_per_pixel == 32 && 
                             image->red_mask == 0x00FF0000 && 
                             image->green_mask == 0x0000FF00 && 
                             image->blue_mask == 0x000000FF);
    }

    /* Fast-path: Standard 32-bit Little-Endian X11 Framebuffer (99.9% of modern Linux) */
    if (is_standard_rgb32) {
        for (long y = 0; y < h; y++) {
            const unsigned char *src = rgb + (y * w) * 3;
            uint32_t *dst = (uint32_t *)(image->data + y * image->bytes_per_line);
            for (long x = 0; x < w; x++, src += 3) {
                dst[x] = ((uint32_t)src[0] << 16) | ((uint32_t)src[1] << 8) | (uint32_t)src[2];
            }
        }
    } else {
        /* General TrueColor fallback with precomputed bit shifts (zero while-loops) */
        for (long y = 0; y < h; y++) {
            const unsigned char *src = rgb + (y * w) * 3;
            uint32_t *dst = (uint32_t *)(image->data + y * image->bytes_per_line);
            for (long x = 0; x < w; x++, src += 3) {
                dst[x] = (((uint32_t)src[0]) << r_shift) |
                         (((uint32_t)src[1]) << g_shift) |
                         (((uint32_t)src[2]) << b_shift);
            }
        }
    }

    XPutImage(display, window, gc, image, 0, 0, 0, 0, (unsigned int)w, (unsigned int)h);
    XFlush(display);
}

void *mui_window_event(void) {
    memset(&event, 0, sizeof(event));
    if (!display) { event.kind = 1; return &event; }
    
    if (!XPending(display)) {
        fd_set set; FD_ZERO(&set); FD_SET(ConnectionNumber(display), &set);
        struct timeval timeout = {0, 16000}; /* 16ms: responsive 60 FPS tick */
        select(ConnectionNumber(display) + 1, &set, NULL, NULL, &timeout);
        if (!XPending(display)) return &event;
    }

    XEvent e;
    XNextEvent(display, &e);

    if (e.type == SelectionRequest) {
        XSelectionRequestEvent *request = &e.xselectionrequest;
        XEvent reply = {0};
        reply.xselection.type = SelectionNotify; reply.xselection.display = display;
        reply.xselection.requestor = request->requestor; reply.xselection.selection = request->selection;
        reply.xselection.target = request->target; reply.xselection.time = request->time;
        reply.xselection.property = None;
        Atom target = XInternAtom(display, "UTF8_STRING", False);
        Atom targets = XInternAtom(display, "TARGETS", False);
        Atom property = request->property ? request->property : request->target;
        if (request->target == targets) {
            Atom list[] = {targets, target, XA_STRING};
            XChangeProperty(display, request->requestor, property, XA_ATOM, 32, PropModeReplace,
                            (unsigned char *)list, 3);
            reply.xselection.property = property;
        } else if (clipboard && (request->target == target || request->target == XA_STRING)) {
            XChangeProperty(display, request->requestor, property, request->target, 8, PropModeReplace,
                            (unsigned char *)clipboard, strlen(clipboard));
            reply.xselection.property = property;
        }
        XSendEvent(display, request->requestor, False, 0, &reply);
        XFlush(display);
        return &event;
    }
    if (e.type == MappingNotify) { XRefreshKeyboardMapping(&e.xmapping); return &event; }
    if (XFilterEvent(&e, window)) return &event;

    if (e.type == ClientMessage && (Atom)e.xclient.data.l[0] == wm_delete) {
        event.kind = 1;
    } else if (e.type == Expose) {
        /* Squash multiple expose events into one frame request */
        while (XCheckTypedWindowEvent(display, window, Expose, &e));
        event.kind = 2;
    } else if (e.type == ConfigureNotify) {
        /* Squash intermediate resize events to the final size */
        while (XCheckTypedWindowEvent(display, window, ConfigureNotify, &e));
        if (e.xconfigure.width != width || e.xconfigure.height != height) {
            width = e.xconfigure.width; height = e.xconfigure.height;
            event.kind = 3; event.a = width; event.b = height;
        }
    } else if (e.type == MotionNotify) {
        /* CRITICAL OPTIMIZATION: Squash all pending motion events to the newest coordinates */
        while (XCheckTypedWindowEvent(display, window, MotionNotify, &e));
        event.kind = 4; event.a = e.xmotion.x; event.b = e.xmotion.y;
    } else if (e.type == ButtonPress) {
        if (e.xbutton.button == 4 || e.xbutton.button == 5) {
            event.kind = 6; event.a = e.xbutton.button == 4 ? -1 : 1;
        } else {
            event.kind = 5; event.a = e.xbutton.x; event.b = e.xbutton.y;
            event.modifiers = e.xbutton.button;
        }
    } else if (e.type == KeyPress) {
        KeySym key = 0; int count;
        if (input_context) {
            Status status;
            count = Xutf8LookupString(input_context, &e.xkey, event.text, sizeof(event.text)-1, &key, &status);
            if (status == XBufferOverflow) count = 0;
        } else count = XLookupString(&e.xkey, event.text, sizeof(event.text)-1, &key, NULL);
        if (count < 0 || count >= (int)sizeof(event.text)) count = 0;
        event.text[count] = 0;
        event.kind = 7; event.a = key; event.modifiers = e.xkey.state;
    } else if (e.type == FocusIn && input_context) {
        XSetICFocus(input_context);
    } else if (e.type == FocusOut && input_context) {
        XUnsetICFocus(input_context);
    }
    return &event;
}

const char *mui_window_text(void) { return event.text; }