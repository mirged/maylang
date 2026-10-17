/* X11 presentation/input only. Browser chrome and page rendering are Maylang. */
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
static struct { int64_t kind, a, b, modifiers; char text[128]; } event;

void mb_window_close(void) {
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

void mb_window_copy(const char *text) {
    if (!display) return;
    free(clipboard); clipboard = strdup(text);
    XSetSelectionOwner(display, XInternAtom(display, "CLIPBOARD", False), window, CurrentTime);
}

const char *mb_window_paste(void) {
    free(paste); paste = NULL;
    if (!display) return "";
    Atom selection = XInternAtom(display, "CLIPBOARD", False);
    if (XGetSelectionOwner(display, selection) == window) return clipboard ? clipboard : "";
    if (XGetSelectionOwner(display, selection) == None) selection = XA_PRIMARY;
    Atom property = XInternAtom(display, "MAYBROWSER_PASTE", False);
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

long mb_window_open(long w, long h, const char *title) {
    mb_window_close();
    setlocale(LC_CTYPE, "");
    XSetLocaleModifiers("");
    display = XOpenDisplay(NULL);
    if (!display) return 0;
    int screen = DefaultScreen(display);
    width = (int)w; height = (int)h;
    window = XCreateSimpleWindow(display, RootWindow(display, screen), 0, 0,
                                width, height, 0, 0, 0xf8fafc);
    XStoreName(display, window, title);
    XClassHint klass = {"maybrowser", "MayBrowser"};
    XSetClassHint(display, window, &klass);
    unsigned long pid = getpid();
    XChangeProperty(display, window, XInternAtom(display, "_NET_WM_PID", False),
                    XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&pid, 1);
    XSizeHints hints = {0};
    hints.flags = PMinSize; hints.min_width = 640; hints.min_height = 400;
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

void mb_window_title(const char *title) { if (display) XStoreName(display, window, title); }
void mb_window_cursor(long kind) {
    if (display && kind >= 0 && kind < 3) XDefineCursor(display, window, cursors[kind]);
}

/* Translate visual masks rather than assuming the server uses RGB byte order. */
static unsigned long channel(unsigned value, unsigned long mask) {
    if (!mask) return 0;
    unsigned shift = 0;
    while (!(mask & 1)) { shift++; mask >>= 1; }
    return ((value * mask + 127) / 255) << shift;
}

void mb_window_present(const unsigned char *rgb, long w, long h) {
    if (!display || !rgb || w < 1 || h < 1) return;
    if (!image || image->width != w || image->height != h) {
        if (image) XDestroyImage(image);
        int screen = DefaultScreen(display);
        image = XCreateImage(display, DefaultVisual(display, screen), DefaultDepth(display, screen),
                             ZPixmap, 0, NULL, w, h, 32, 0);
        if (!image) return;
        image->data = calloc(h, image->bytes_per_line);
        if (!image->data) { XDestroyImage(image); image = NULL; return; }
    }
    for (long y = 0; y < h; y++) for (long x = 0; x < w; x++) {
        const unsigned char *p = rgb + (y * w + x) * 3;
        XPutPixel(image, x, y, channel(p[0], image->red_mask) |
                   channel(p[1], image->green_mask) | channel(p[2], image->blue_mask));
    }
    XPutImage(display, window, gc, image, 0, 0, 0, 0, w, h);
    XFlush(display);
}

void *mb_window_event(void) {
    memset(&event, 0, sizeof(event));
    if (!display) { event.kind = 1; return &event; }
    if (!XPending(display)) {
        fd_set set; FD_ZERO(&set); FD_SET(ConnectionNumber(display), &set);
        struct timeval timeout = {0, 50000};
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
    if (XFilterEvent(&e, window)) return &event;
    if (e.type == ClientMessage && (Atom)e.xclient.data.l[0] == wm_delete) event.kind = 1;
    else if (e.type == Expose) event.kind = 2;
    else if (e.type == ConfigureNotify && (e.xconfigure.width != width || e.xconfigure.height != height)) {
        width = e.xconfigure.width; height = e.xconfigure.height;
        event.kind = 3; event.a = width; event.b = height;
    } else if (e.type == MotionNotify) {
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
    } else if (e.type == FocusIn && input_context) XSetICFocus(input_context);
    else if (e.type == FocusOut && input_context) XUnsetICFocus(input_context);
    return &event;
}

const char *mb_window_text(void) { return event.text; }
