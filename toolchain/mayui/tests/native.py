#!/usr/bin/env python3
"""Check the native ABI, Sokol texture presentation and repeated lifecycle."""
import argparse
import ctypes as c
import os
from pathlib import Path
import subprocess
import time


class Event(c.Structure):
    _fields_ = [(name, c.c_int64) for name in ('kind', 'a', 'b', 'modifiers')] + [('text', c.c_char * 128)]


class ClientMessage(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', c.c_long * 5)]


class XEvent(c.Union):
    _fields_ = [('client', ClientMessage), ('padding', c.c_long * 24)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library', type=Path)
    parser.add_argument('--window', action='store_true')
    options = parser.parse_args()
    ui = c.CDLL(str(options.library.resolve()))
    ui.mui_window_open.argtypes = [c.c_long, c.c_long, c.c_char_p]
    ui.mui_window_open.restype = c.c_long
    ui.mui_window_present.argtypes = [c.c_void_p, c.c_long, c.c_long]
    ui.mui_window_event.restype = c.POINTER(Event)
    ui.mui_window_copy.argtypes = [c.c_char_p]
    ui.mui_window_paste.restype = c.c_char_p
    ui.mui_window_title.argtypes = [c.c_char_p]
    ui.mui_window_renderer.restype = c.c_char_p
    ui.mui_surface.argtypes = [c.c_long, c.c_long]
    ui.mui_surface.restype = c.c_long
    ui.mui_rect.argtypes = [c.c_long] * 6
    ui.mui_stroke.argtypes = [c.c_long] * 8
    ui.mui_shadow.argtypes = [c.c_long] * 8
    ui.mui_line.argtypes = [c.c_long] * 7
    ui.mui_text.argtypes = [c.c_long, c.c_long, c.c_char_p, c.c_long, c.c_long]
    ui.mui_pixel.argtypes = [c.c_long, c.c_long]
    ui.mui_pixel.restype = c.c_long
    ui.mui_draw_stat.argtypes = [c.c_long]
    ui.mui_draw_stat.restype = c.c_long
    ui.mui_window_event_timeout.argtypes = [c.c_long]
    ui.mui_window_event_timeout.restype = c.POINTER(Event)

    ui.mui_bitmap_upload.argtypes = [c.c_void_p, c.c_long, c.c_long]
    ui.mui_bitmap.argtypes = [c.c_long] * 4
    ui.mui_window_key_down.argtypes = [c.c_long]
    ui.mui_window_key_down.restype = c.c_long
    ui.mui_window_key_pressed.argtypes = [c.c_long]
    ui.mui_window_key_pressed.restype = c.c_long
    x_focus_key = 262
    assert not ui.mui_window_key_down(x_focus_key)
    assert not ui.mui_window_open(0, 360, b'Invalid')
    assert not ui.mui_window_open(480, 8193, b'Invalid')
    if not options.window:
        os.environ['DISPLAY'] = ''
        assert not ui.mui_window_open(480, 360, b'No display')
        ui.mui_window_copy(b'Closed')
        assert ui.mui_window_paste() == b''
        assert ui.mui_window_event().contents.kind == 1
        ui.mui_window_close()
        ui.mui_window_close()
        print('PASS native invalid dimensions, missing display and idempotent close')
        return

    def command(*args):
        return subprocess.check_output(['xdotool', *map(str, args)], text=True, timeout=10).strip()

    def wait(predicate, label):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.02)
        raise AssertionError(label)

    def drain():
        events = []
        while True:
            event = ui.mui_window_event().contents
            if event.kind == 0:
                return events
            events.append((event.kind, event.a, event.b, event.modifiers, bytes(event.text)))

    x11 = c.CDLL('libX11.so.6')
    x11.XOpenDisplay.argtypes = [c.c_char_p]
    x11.XOpenDisplay.restype = c.c_void_p
    x11.XGetImage.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_ulong, c.c_int]
    x11.XGetImage.restype = c.c_void_p
    x11.XGetPixel.argtypes = [c.c_void_p, c.c_int, c.c_int]
    x11.XGetPixel.restype = c.c_ulong
    x11.XDestroyImage.argtypes = [c.c_void_p]
    x11.XCloseDisplay.argtypes = [c.c_void_p]
    x11.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
    x11.XInternAtom.restype = c.c_ulong
    x11.XSendEvent.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(XEvent)]
    x11.XFlush.argtypes = [c.c_void_p]
    display = x11.XOpenDisplay(None)
    assert display
    try:
        for cycle in range(2):
            assert ui.mui_window_open(480, 360, b'MayUI native regression') == 1
            try:
                window = int(command('search', '--sync', '--onlyvisible', '--pid', os.getpid(),
                                     '--name', 'MayUI native regression').splitlines()[0])
                command('windowfocus', '--sync', window)
                assert b'OpenGL' in ui.mui_window_renderer()
                expected_renderer = b'CPU raster' if os.environ.get('MAYUI_RENDERER') == 'cpu' else b'Sokol GPU'
                assert ui.mui_window_renderer().startswith(expected_renderer)
                # Upload a 2x2 RGB surface. Read the actual X11 window back to
                # detect blank GPU output, swapped channels and flipped UVs.
                pixels = (c.c_ubyte * 12)(255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255)
                ui.mui_window_present(pixels, 2, 2)

                def colors_match(points):
                    image = x11.XGetImage(display, window, 0, 0, 480, 360, c.c_ulong(-1).value, 2)
                    assert image
                    try:
                        return all(x11.XGetPixel(image, x, y) & 0xffffff == color for x, y, color in points)
                    finally:
                        x11.XDestroyImage(image)

                wait(lambda: colors_match([(20, 20, 0xff0000), (460, 20, 0x00ff00),
                                           (20, 340, 0x0000ff), (460, 340, 0xffffff)]),
                     'Sokol did not present the RGB surface correctly')
                replacement = (c.c_ubyte * 3)(17, 34, 51)
                ui.mui_window_present(replacement, 1, 1)
                wait(lambda: colors_match([(20, 20, 0x112233), (460, 340, 0x112233)]),
                     'Sokol did not replace the resized texture')
                # Exercise real GPU primitives and the glyph atlas, rather than
                # only a fullscreen texture. Compare against the software path.
                assert ui.mui_surface(480, 360)
                ui.mui_rect(0, 0, 480, 360, 0, 0xffffff)
                ui.mui_shadow(32, 34, 120, 80, 22, 5, 0x102030, 80)
                ui.mui_rect(32, 30, 120, 80, 22, 0x6d5efc)
                ui.mui_stroke(175, 30, 120, 80, 22, 2, 0x192a40, 255)
                ui.mui_line(40, 140, 75, 175, 3, 0x19b99a, 255)
                ui.mui_line(75, 175, 130, 125, 3, 0x19b99a, 255)
                ui.mui_text(30, 220, 'Sokol · café λ'.encode(), 24, 0x172638)
                rgba = (c.c_ubyte * 16)(255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,128)
                assert ui.mui_bitmap_upload(rgba,2,2)
                ui.mui_bitmap(340,30,80,80)
                ui.mui_present()
                wait(lambda: colors_match([(90, 70, 0x6d5efc), (220, 65, 0xffffff)]), 'GPU geometry not rendered')
                image = x11.XGetImage(display, window, 0, 0, 480, 360, c.c_ulong(-1).value, 2)
                assert image
                try:
                    points = [(x, y) for x in range(24, 310, 3) for y in range(24, 185, 3)]
                    points += [(x, y) for x in range(30, 200, 2) for y in range(222, 245, 2)]
                    different = 0
                    for px, py in points:
                        actual = x11.XGetPixel(image, px, py) & 0xffffff
                        expected = ui.mui_pixel(px, py)
                        difference = max(abs(((actual >> shift) & 255) - ((expected >> shift) & 255)) for shift in (0, 8, 16))
                        different += difference > 12
                    assert different < len(points) // 100, (different, len(points))
                finally:
                    x11.XDestroyImage(image)
                wait(lambda: colors_match([(350,40,0xff0000),(410,40,0x00ff00),(350,100,0x0000ff)]), 'RGBA framebuffer UVs or channels incorrect')
                assert ui.mui_pixel(350,40) == 0xff0000
                replacement_rgba = (c.c_ubyte * 16)(*([17,34,51,255]*4))
                assert ui.mui_bitmap_upload(replacement_rgba,2,2)
                ui.mui_present()
                wait(lambda: colors_match([(350,40,0x112233),(410,100,0x112233)]), 'dynamic framebuffer did not update without geometry changes')
                assert ui.mui_pixel(410,100) == 0x112233
                # A curved edge contains partial coverage, not a binary staircase.
                edge = [ui.mui_pixel(x, y) for x in range(32, 55) for y in range(30, 53)]
                assert any(value not in (0xffffff, 0x6d5efc) for value in edge)
                assert ui.mui_draw_stat(1) > 100
                ui.mui_window_copy('Clipboard café λ'.encode())
                assert ui.mui_window_paste().decode() == 'Clipboard café λ'
                drain()
                waits = []
                for _ in range(3):
                    before = time.monotonic()
                    ui.mui_window_event_timeout(0)
                    waits.append(time.monotonic() - before)
                assert min(waits) < .02, 'nonblocking polling waited'
                command('key', 'space', 'Return', 'shift+Tab', 'ctrl+a')
                events = [e for e in drain() if e[0] == 7]
                assert [(e[1], e[3] & 5, e[4]) for e in events] == [
                    (32, 0, b' '), (65293, 0, b''), (65289, 1, b''), (97, 4, b'')], events
                command('keydown', 'Right', 'x')
                wait(lambda: ui.mui_window_key_down(262) and ui.mui_window_key_down(88), 'held keys were not recorded')
                command('keyup', 'Right', 'x')
                wait(lambda: not ui.mui_window_key_down(262) and not ui.mui_window_key_down(88), 'released keys remained held')
                assert ui.mui_window_key_pressed(262), 'short press was lost between polls'
                assert not ui.mui_window_key_pressed(262), 'press was not consumed'
                command('keydown', 'Right')
                wait(lambda: ui.mui_window_key_down(262), 'key down missing')
                x11.XDefaultRootWindow.argtypes = [c.c_void_p]
                x11.XDefaultRootWindow.restype = c.c_ulong
                command('windowfocus', x11.XDefaultRootWindow(display))
                wait(lambda: not ui.mui_window_key_down(262), 'losing focus left a stuck controller key')
                command('keyup', 'Right')
                command('windowfocus', '--sync', window)
                ui.mui_window_title(b'MayUI renamed')
                wait(lambda: command('getwindowname', window) == 'MayUI renamed', 'window title not updated')
                command('windowsize', window, 560, 420)
                wait(lambda: any(e[:3] == (3, 560, 420) for e in drain()), 'resize not delivered')
                close = XEvent()
                close.client = ClientMessage(
                    type=33, display=display, window=window, format=32,
                    message_type=x11.XInternAtom(display, b'WM_PROTOCOLS', 0),
                    data=(c.c_long * 5)(x11.XInternAtom(display, b'WM_DELETE_WINDOW', 0), 0, 0, 0, 0))
                assert x11.XSendEvent(display, window, 0, 0, c.byref(close))
                x11.XFlush(display)
                wait(lambda: any(e[0] == 1 for e in drain()), 'window-manager close not delivered')
                # The polling API lets Maylang observe close before releasing
                # the window. A cancelled Sokol quit must keep it alive here.
                assert command('getwindowname', window) == 'MayUI renamed'
            finally:
                ui.mui_window_close()
                ui.mui_window_close()
        print('PASS Sokol GPU shapes/glyphs/framebuffer vs software, live RGBA uploads, held/released/focus-cleared keys, clipboard, resize, WM close and reopen')
    finally:
        x11.XCloseDisplay(display)


if __name__ == '__main__':
    main()
