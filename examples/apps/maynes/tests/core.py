#!/usr/bin/env python3
"""ROM admission, controller behavior, deterministic states and persistent saves."""
import argparse
import ctypes as c
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

def build(output, sanitize=False):
    native = ROOT / 'native'
    flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if sanitize else ['-O2']
    command = ['cc', *flags, '-DBINJNES_GCC', str(native / 'nes.c'),
               *map(str, [native / 'vendor/binjnes' / f for f in ('emulator.c', 'common.c', 'cartdb.c')])]
    if sanitize:
        command += [str(ROOT / 'tests/memory.c')]
    else:
        command += ['-shared', '-fPIC']
    subprocess.run([*command, '-o', str(output), '-ldl', '-pthread', '-lm'], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu-rom',type=Path,help='Optional blargg official_only.nes CPU behavior ROM')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='maynes-core-') as temp:
        directory = Path(temp)
        os.environ['XDG_DATA_HOME'] = str(directory / 'data')
        library = directory / 'libmaynes.so'
        build(library)
        n = c.CDLL(str(library))
        for name in ('nes_frame_hash', 'nes_frame_count', 'nes_mapper'):
            getattr(n, name).restype = c.c_long
        n.nes_pixels.restype = c.c_void_p
        n.nes_message.restype = c.c_char_p
        assert n.nes_load(b'')
        start = time.monotonic()
        for i in range(90):
            assert n.nes_frame(0)
        print(f'90 NTSC frames: {(time.monotonic()-start)*1000:.1f} ms core time')
        assert n.nes_audio_samples() > 60000 and n.nes_audio_peak() > 0, 'APU must synthesize audible samples'
        first = c.string_at(n.nes_pixels(), 256*240*4)
        assert len({first[i:i+4] for i in range(0,len(first),4)}) >= 3, 'PPU must produce a populated image'
        assert n.nes_save()
        saved_frames, saved_hash = n.nes_frame_count(), n.nes_frame_hash()
        for i in range(30):
            assert n.nes_frame(128)
        moved_hash = n.nes_frame_hash()
        assert n.nes_restore()
        assert (n.nes_frame_count(), n.nes_frame_hash()) == (saved_frames, saved_hash), 'restore pixels immediately, while paused'
        for i in range(30):
            assert n.nes_frame(128)
        assert n.nes_frame_hash() == moved_hash, 'same input after restore must be deterministic'
        assert n.nes_restore()
        for i in range(30):
            assert n.nes_frame(64)
        assert n.nes_frame_hash() != moved_hash, 'controller changes actual emulated gameplay'
        old_hash = n.nes_frame_hash()
        for name, content in [('short.nes', b'NES'), ('garbage.nes', b'x'*32),
                              ('truncated.nes', b'NES\x1a'+bytes([2,1])+bytes(10)),
                              ('nes2.nes', b'NES\x1a'+bytes([1,1,0,8])+bytes(8)+bytes(24576)),
                              ('ram-overflow.nes', b'NES\x1a'+bytes([1,1,0,0,255])+bytes(7)+bytes(24576)),
                              ('unsupported.nes', b'NES\x1a'+bytes([1,1,240,240])+bytes(8)+bytes(24576))]:
            path = directory / name; path.write_bytes(content)
            assert not n.nes_load(os.fsencode(path)), name
            assert n.nes_frame_hash() == old_hash, 'failed load must retain current game'
        states = list((directory/'data/maynes').glob('*.state'))
        assert len(states) == 1
        damaged = bytearray(states[0].read_bytes()); damaged[-50] ^= 127
        states[0].write_bytes(damaged)
        assert not n.nes_restore() and n.nes_frame_hash() == old_hash, 'corrupt state must leave the game intact'
        # Same game under a different name shares its content-addressed save.
        path = directory/'name with spaces λ.nes'; path.write_bytes((ROOT/'roms/starfall.nes').read_bytes())
        assert n.nes_load(os.fsencode(path)) and n.nes_mapper() == 0
        for i in range(100): assert n.nes_frame(0)
        assert n.nes_save()
        persisted = n.nes_frame_hash()
        n.nes_close()
        assert n.nes_load(os.fsencode(path)) and n.nes_restore()
        assert n.nes_frame_hash() == persisted, 'states survive a full machine recreation'
        pal = bytearray(path.read_bytes()); pal[9] = 1
        pal_path = directory/'pal.nes'; pal_path.write_bytes(pal)
        assert n.nes_load(os.fsencode(pal_path)) and 19900 < n.nes_period_us() < 20100, 'PAL header sets the region clock'
        # Battery-backed variant: persist SRAM, separately from manual state.
        battery = bytearray(path.read_bytes()); battery[6] |= 2; battery[8] = 1
        path.write_bytes(battery)
        assert n.nes_load(os.fsencode(path))
        n.nes_battery_flush()
        saves = list((directory/'data/maynes').glob('*.sav'))
        assert saves and saves[0].stat().st_size == 8192
        assert n.nes_preferences(b'{"schema":1,"recent":[]}\n')
        assert (directory/'data/maynes/library.json').read_text().startswith('{')
        n.nes_close()
        executable = directory/'memory'
        build(executable, sanitize=True)
        subprocess.run([str(executable)], check=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1', UBSAN_OPTIONS='halt_on_error=1'))
        if args.cpu_rom:
            native = ROOT/'native/vendor/binjnes'
            cpu_test = directory/'cpu-test'
            subprocess.run(['cc','-O2','-DBINJNES_GCC','-I'+str(native),str(ROOT/'tests/cpu_rom.c'),
                            *[str(native/f) for f in ('emulator.c','common.c','cartdb.c')],'-o',str(cpu_test),'-lm'],check=True)
            subprocess.run([str(cpu_test),str(args.cpu_rom.resolve())],check=True,timeout=60)
    print('PASS core: real PPU/controller, deterministic persistent state, corrupt/invalid input, battery SRAM, ASAN/UBSAN')

if __name__ == '__main__':
    main()
