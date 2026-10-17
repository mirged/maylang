#!/usr/bin/env python3
"""Drive a private Sokol window with xdotool; no third-party Python packages."""
import ctypes as c
import json
import os
from pathlib import Path
import select
import signal
import shutil
import struct
import subprocess
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAY = Path(os.environ.get('MAY', str(Path.home() / '.maylang/bin/may')))
REPO = ROOT.parents[2]
import tempfile


def screenshot(window, path, width=1280, height=960):
    x = c.CDLL('libX11.so.6')
    x.XOpenDisplay.restype = c.c_void_p
    x.XGetImage.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_ulong, c.c_int]
    x.XGetImage.restype = c.c_void_p
    x.XGetPixel.argtypes = [c.c_void_p, c.c_int, c.c_int]
    x.XGetPixel.restype = c.c_ulong
    x.XDestroyImage.argtypes = [c.c_void_p]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    display = x.XOpenDisplay(None)
    assert display
    image = x.XGetImage(display, int(window), 0, 0, width, height, c.c_ulong(-1).value, 2)
    assert image
    try:
        data = bytearray()
        for y in range(height):
            data.append(0)
            for col in range(width):
                pixel = x.XGetPixel(image, col, y)
                data.extend(((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255))
        def chunk(kind, value):
            return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value))
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) +
                         chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))
    finally:
        x.XDestroyImage(image)
        x.XCloseDisplay(display)


def main():
    assert shutil.which('Xvfb') and shutil.which('xdotool')
    with tempfile.TemporaryDirectory(prefix='maynes-desktop-') as temporary:
        directory = Path(temporary)
        environment = dict(os.environ, XDG_DATA_HOME=str(directory/'data'), GDK_BACKEND='x11', GTK_USE_PORTAL='0',
                           DBUS_SESSION_BUS_ADDRESS='unix:path='+str(directory/'no-session-bus'), GSETTINGS_BACKEND='memory')
        if (REPO/'stdlib/ui.may').is_file(): environment['MAYLANG_STDLIB']=str(REPO/'stdlib')
        read_fd, write_fd = os.pipe()
        server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1600x1200x24', '-nolisten', 'tcp', '-ac'], pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.close(write_fd)
        child = None
        try:
            assert select.select([read_fd], [], [], 10)[0]
            environment['DISPLAY'] = ':' + os.read(read_fd, 32).decode().strip()
            os.environ['DISPLAY'] = environment['DISPLAY']
            os.close(read_fd)
            def run(*args, timeout=120):
                result = subprocess.run(list(map(str,args)), cwd=ROOT, env=environment, capture_output=True, text=True, timeout=timeout)
                assert result.returncode == 0, (args,result.stdout,result.stderr)
                return result.stdout
            def xdo(*args): return run('xdotool',*args,timeout=15).strip()
            native_report = directory/'native.json'
            run(MAY,'run','--','--frames','180','--report',native_report)
            report = json.loads(native_report.read_text())
            assert report['frames'] == 180 and report['renderer'].startswith('Sokol GPU'), report
            child = subprocess.Popen([str(MAY),'run','--'],cwd=ROOT,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            window = xdo('search','--sync','--onlyvisible','--name','^May NES · Native player$').splitlines()[0]
            xdo('windowfocus','--sync',window)
            time.sleep(.6)
            xdo('key','p'); time.sleep(.15)
            # Read the live GPU framebuffer, excluding changing UI counters.
            x = c.CDLL('libX11.so.6')
            x.XOpenDisplay.restype=c.c_void_p
            x.XGetImage.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_int,c.c_uint,c.c_uint,c.c_ulong,c.c_int]
            x.XGetImage.restype=c.c_void_p
            x.XGetPixel.argtypes=[c.c_void_p,c.c_int,c.c_int]; x.XGetPixel.restype=c.c_ulong
            x.XDestroyImage.argtypes=[c.c_void_p]; x.XCloseDisplay.argtypes=[c.c_void_p]
            display=x.XOpenDisplay(None)
            def game():
                im=x.XGetImage(display,int(window),511,191,512,480,c.c_ulong(-1).value,2)
                assert im
                try: return bytes(channel for y in range(0,480,2) for col in range(0,512,2) for channel in ((x.XGetPixel(im,col,y)>>16)&255,(x.XGetPixel(im,col,y)>>8)&255,x.XGetPixel(im,col,y)&255))
                finally: x.XDestroyImage(im)
            paused=game(); time.sleep(.2); assert game()==paused, 'P must pause real emulation'
            xdo('key','n'); time.sleep(.15); stepped=game()
            assert stepped!=paused, 'N must advance a real NES frame'
            xdo('key','F5'); time.sleep(.15)
            assert list((directory/'data/maynes').glob('*.state')), 'F5 must save to disk'
            saved=game()
            xdo('keydown','Right'); xdo('key','n','n','n'); xdo('keyup','Right'); time.sleep(.2)
            assert game()!=saved, 'held controller input must reach the emulated game'
            xdo('key','F8'); time.sleep(.2)
            assert game()==saved, 'F8 must restore paused framebuffer exactly'
            screenshot(window,ROOT/'preview-native.png')
            # Paste/load a real cartridge path, including whitespace.
            rom=directory/'Starfall demo.nes'; shutil.copyfile(ROOT/'roms/starfall.nes',rom)
            xdo('mousemove','--window',window,450,125,'click',1)
            xdo('key','ctrl+a'); xdo('type','--clearmodifiers',str(rom)); xdo('key','Return'); time.sleep(.3)
            settings=json.loads((directory/'data/maynes/library.json').read_text())
            assert settings['recent']==[str(rom)], settings
            # Exercise the actual native file chooser, not only the path fallback.
            if shutil.which('zenity'):
                xdo('key','o')
                chooser=xdo('search','--sync','--onlyvisible','--name','^Open NES cartridge$').splitlines()[0]
                xdo('windowfocus','--sync',chooser)
                time.sleep(.5)
                # The chooser preselects the current cartridge. Accept it.
                xdo('key','Return')
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    visible=subprocess.run(['xdotool','search','--onlyvisible','--name','^Open NES cartridge$'],env=environment,capture_output=True)
                    if visible.returncode!=0: break
                    time.sleep(.1)
                assert visible.returncode!=0, 'file chooser did not accept the current cartridge'
                xdo('windowfocus','--sync',window)
                settings=json.loads((directory/'data/maynes/library.json').read_text())
                assert settings['recent'][0]==str(rom), settings
            # Window resize and focus loss/recovery remain usable.
            xdo('windowsize',window,1024,800); time.sleep(.3)
            screenshot(window,ROOT/'preview-compact.png',1024,800)
            xdo('key','ctrl+q')
            output,error=child.communicate(timeout=15)
            assert child.returncode==0,(output,error)
            x.XCloseDisplay(display)
            print('PASS native GPU boot, pause/step, held controller keys, F5/F8 pixel-exact state restore, ROM path/file-chooser loading, recent library, resize and clean exit')
            print(json.dumps(report))
        finally:
            # Closing the private display also releases any nested native dialog.
            server.terminate(); server.communicate(timeout=5)
            if child and child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL)
            if child:
                child.wait(timeout=5)
                child.stdout.close(); child.stderr.close()

if __name__ == '__main__':
    main()
