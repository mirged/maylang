#!/usr/bin/env python3
"""Check analytical coverage, borders, clipping, alpha and Unicode glyph reuse."""
import ctypes as c
from pathlib import Path
import sys


def main():
    ui = c.CDLL(str(Path(sys.argv[1]).resolve()))
    for name, count in [('mui_surface', 2), ('mui_rect', 6), ('mui_clip', 4),
                        ('mui_stroke', 8), ('mui_shadow', 8), ('mui_fill', 7), ('mui_line', 7)]:
        getattr(ui, name).argtypes = [c.c_long] * count
    ui.mui_pixel.argtypes = [c.c_long, c.c_long]
    ui.mui_pixel.restype = c.c_long
    ui.mui_draw_stat.argtypes = [c.c_long]
    ui.mui_draw_stat.restype = c.c_long
    ui.mui_text.argtypes = [c.c_long, c.c_long, c.c_char_p, c.c_long, c.c_long]
    ui.mui_measure.argtypes = [c.c_char_p, c.c_long]
    ui.mui_measure.restype = c.c_long
    assert ui.mui_surface(96, 96)
    ui.mui_rect(0, 0, 96, 96, 0, 0xffffff)
    ui.mui_rect(16, 16, 64, 64, 24, 0)
    assert ui.mui_pixel(48, 48) == 0
    assert ui.mui_pixel(16, 16) == 0xffffff
    values = [ui.mui_pixel(x, y) for x in range(16, 40) for y in range(16, 40)]
    assert len(set(values) - {0, 0xffffff}) >= 8, 'corners need fractional coverage'
    for x in range(16, 40):
        for y in range(16, 40):
            assert ui.mui_pixel(x, y) == ui.mui_pixel(95 - x, y), 'corner symmetry'
    ui.mui_surface(96, 96)
    ui.mui_rect(0, 0, 96, 96, 0, 0xffffff)
    ui.mui_stroke(16, 16, 64, 64, 24, 2, 0, 255)
    assert ui.mui_pixel(48, 16) == 0 and ui.mui_pixel(48, 19) == 0xffffff
    assert ui.mui_pixel(48, 48) == 0xffffff
    ui.mui_fill(2, 2, 8, 8, 0, 0, 128)
    assert ui.mui_pixel(5, 5) == 0x7f7f7f, 'correct 255-denominator alpha compositing'
    ui.mui_clip(40, 40, 12, 12)
    ui.mui_shadow(30, 30, 32, 32, 8, 6, 0, 160)
    assert ui.mui_pixel(39, 48) == 0xffffff, 'shadow escaped clipping'
    assert ui.mui_pixel(48, 48) != 0xffffff
    ui.mui_surface(320, 80)
    ui.mui_rect(0, 0, 320, 80, 0, 0xffffff)
    text = 'Unicode café λ ✓'.encode()
    ui.mui_text(5, 10, text, 24, 0x102030)
    misses = ui.mui_draw_stat(3)
    assert misses > 5 and ui.mui_measure(text, 24) > 50
    ui.mui_surface(320, 80)
    ui.mui_text(5, 10, text, 24, 0)
    assert ui.mui_draw_stat(3) == misses, 'Unicode glyphs were rerasterized'
    for malformed in (b'\xe2', b'\xf0\x80', b'\xc0\xaf', b'\xed\xa0\x80', b'\xff'):
        assert ui.mui_measure(malformed, 24) > 0
        ui.mui_text(5, 10, malformed, 24, 0)
    ui.mui_release()
    assert ui.mui_surface(32, 32)
    ui.mui_release()
    print('PASS antialiased symmetric corners, concentric borders, alpha, shadow clipping, Unicode cache and malformed UTF-8')


if __name__ == '__main__':
    main()
