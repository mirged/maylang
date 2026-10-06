#!/usr/bin/env python3
"""Browser regression tests; only the optional window tests require xdotool."""
import argparse
import base64
import contextlib
import errno
import http.server
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
ENV = dict(os.environ, LD_LIBRARY_PATH=str(BUILD) + ':' + os.environ.get('LD_LIBRARY_PATH', ''))
RESULTS = []


def run(*arguments, input=None, success=True, env=None):
    result = subprocess.run([str(a) for a in arguments], cwd=ROOT, env=env or ENV,
                            input=input, text=True, capture_output=True, timeout=90)
    if (result.returncode == 0) != success:
        raise AssertionError(f'{arguments}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout + result.stderr


def browser(*arguments, **kwargs):
    return run(ROOT / 'maybrowser', *arguments, **kwargs)


def png(path):
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'invalid PNG signature'
    pos, compressed, width, height = 8, bytearray(), 0, 0
    while pos < len(data):
        size = struct.unpack_from('>I', data, pos)[0]
        kind, body = data[pos+4:pos+8], data[pos+8:pos+8+size]
        assert zlib.crc32(kind + body) & 0xffffffff == struct.unpack_from('>I', data, pos+8+size)[0]
        if kind == b'IHDR':
            width, height, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', body)
            assert (depth, color, comp, filt, interlace) == (8, 2, 0, 0, 0), 'expected RGB PNG'
        elif kind == b'IDAT':
            compressed.extend(body)
        elif kind == b'IEND':
            break
        pos += size + 12
    raw, rows, previous, stride = zlib.decompress(compressed), [], bytearray(width*3), width*3
    assert len(raw) == height * (stride + 1)
    for y in range(height):
        offset = y * (stride + 1)
        kind = raw[offset]
        row = bytearray(raw[offset+1:offset+1+stride])
        for x in range(stride):
            a = row[x-3] if x >= 3 else 0
            b = previous[x]
            c = previous[x-3] if x >= 3 else 0
            if kind == 1: prediction = a
            elif kind == 2: prediction = b
            elif kind == 3: prediction = (a+b)//2
            elif kind == 4:
                p = a+b-c
                distances = (abs(p-a), abs(p-b), abs(p-c))
                prediction = (a,b,c)[distances.index(min(distances))]
            else:
                assert kind == 0, 'unknown PNG filter'
                prediction = 0
            row[x] = (row[x] + prediction) & 255
        rows.append(bytes(row))
        previous = row
    pixels = b''.join(rows)
    return width, height, pixels


def pixel(image, x, y):
    width, _, data = image
    pos = (y*width+x)*3
    return tuple(data[pos:pos+3])


def passed(label):
    RESULTS.append({'test': label, 'status': 'pass'})
    print('PASS', label, flush=True)


def skipped(label, reason):
    RESULTS.append({'test': label, 'status': 'skip', 'reason': reason})
    print('SKIP', label + ':', reason, flush=True)


def wait_for(predicate, label, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError('timed out: ' + label)


def test_cli(directory):
    assert 'graphical start page' in browser('--help')
    for flags in [('--width',), ('--height','0'), ('--width','4097'), ('--width','banana'),
                  ('--unknown',), ('a','b'), ('--snapshot','--width','639')]:
        browser(*flags, success=False)
    browser('missing-page.html', '-o', directory/'missing.png', success=False)
    browser('--html', '<html></html>', '-o', directory/'absent'/'out.png', success=False)
    browser('--gui', env=dict(ENV, DISPLAY=''), success=False)
    html = '<html><head><style>html{background:#112233}</style></head><body><p>Hello λ</p></body></html>'
    sources = [('--html', html), ('-',), ('data:text/html,' + html,),
               ('data:text/html;base64,' + base64.b64encode(html.encode()).decode(),)]
    for index, source in enumerate(sources):
        output = directory / f'source-{index}.png'
        browser(*source, '-o', output, '--width','320','--height','240',
                input=html if source == ('-',) else None)
        image = png(output)
        assert image[:2] == (320,240) and pixel(image,319,239) == (17,34,51)
    output = BUILD / 'start.png'
    browser('--snapshot', '-o', output)
    image = png(output)
    assert image[:2] == (1024,768)
    assert pixel(image,0,0) != pixel(image,0,200), 'chrome and page must have distinct backgrounds'
    browser('--snapshot', '--width','640','--height','480','-o', BUILD/'start-small.png')
    assert png(BUILD/'start-small.png')[:2] == (640,480)
    passed('CLI validation, inline/stdin/data inputs, PNG export, and interface snapshots')


def test_scripts(directory):
    html = "<html><head><title>JS</title><style>html{background:#112233}</style></head><body><script>window.onload=function(){document.documentElement.style.background='#cc5533';console.log('loaded');};</script></body></html>"
    output = directory/'script.png'
    result = browser('--html', html,'-o', output,'--width','320','--height','240')
    assert '[js] loaded' in result and pixel(png(output),319,239) == (204,85,51)
    browser('--html', html,'--no-js','-o',output,'--width','320','--height','240')
    assert pixel(png(output),319,239) == (17,34,51)
    for name in ('hello', 'dynamic'):
        browser(ROOT/'examples'/f'{name}.html','-o',BUILD/f'{name}.png','--width','800','--height','700')
        assert png(BUILD/f'{name}.png')[:2] == (800,700)
    browser('about:demo','--snapshot','-o',BUILD/'playground.png')
    passed('page-load JavaScript, preserved CSS, --no-js, and example pages')


def test_network(directory, required):
    site = directory/'site'
    (site/'nested').mkdir(parents=True)
    (site/'assets').mkdir()
    (site/'nested'/'index.html').write_text('<html><head><link rel="stylesheet" href="../assets/style.css"></head><body><img src="../assets/image.png"><script src="../assets/script.js"></script></body></html>')
    (site/'assets'/'style.css').write_text('html{background:#294b6d}')
    (site/'assets'/'script.js').write_text("console.log('remote script loaded');")
    shutil.copyfile(BUILD/'start-small.png', site/'assets'/'image.png')
    requests = []
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)
        def log_message(self, *_):
            pass
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    except OSError as error:
        if required or error.errno not in (errno.EPERM, errno.EACCES):
            raise
        skipped('live HTTP and relative assets', 'sandbox blocks local sockets')
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f'http://127.0.0.1:{server.server_port}'
        output = directory/'remote.png'
        result = browser(origin+'/nested/index.html','-o',output,'--width','800','--height','700')
        assert '[js] remote script loaded' in result
        assert pixel(png(output),799,699) == (41,75,109)
        assert set(['/nested/index.html','/assets/style.css','/assets/script.js','/assets/image.png']).issubset(requests), requests
        browser(origin+'/missing.html','-o',output,success=False)
        passed('live HTTP, relative CSS/scripts/images, and HTTP errors')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_gui(directory, coordinates):
    assert os.environ.get('DISPLAY') and shutil.which('xdotool'), '--gui requires DISPLAY and xdotool'
    screenshot = BUILD/'window.png'
    logpath = BUILD/'window.log'
    def xdo(*arguments, success=True):
        return run('xdotool', *arguments, success=success).strip()
    with logpath.open('w') as log:
        process = subprocess.Popen([str(ROOT/'maybrowser'),'--gui','-o',str(screenshot)],
                                   cwd=ROOT, env=ENV, stdout=log, stderr=log)
        try:
            def window_id():
                assert process.poll() is None, logpath.read_text()
                result = subprocess.run(['xdotool','search','--onlyvisible','--pid',str(process.pid)],capture_output=True,text=True)
                # Some X servers do not provide _NET_WM_PID: fall back to the class.
                if result.returncode:
                    result = subprocess.run(['xdotool','search','--onlyvisible','--class','^MayBrowser$'],capture_output=True,text=True)
                return result.stdout.splitlines()[0] if result.stdout.strip() else None
            window = wait_for(window_id, 'browser window')
            xdo('windowfocus','--sync',window)
            def key(value):
                xdo('key','--clearmodifiers',value)
            def title(expected):
                wait_for(lambda: expected in xdo('getwindowname',window), 'window title '+expected)
            def save(expected_size=(1024,768)):
                screenshot.unlink(missing_ok=True)
                key('ctrl+s')
                def ready():
                    if not screenshot.exists(): return None
                    try:
                        image = png(screenshot)
                        return image if image[:2] == expected_size else None
                    except (AssertionError, ValueError, struct.error, zlib.error):
                        return None
                return wait_for(ready, 'saved window PNG')
            title('Start page')
            save()
            key('ctrl+l')
            xdo('type','--clearmodifiers','--delay','10','about:demo')
            key('Return'); title('The playground')
            before = save()
            xdo('mousemove','--window',window,str(coordinates['x']),str(coordinates['y']))
            xdo('click','--repeat','2','--delay','250','1')
            wait_for(lambda: '[js] Playground clicks 2' in logpath.read_text(), 'two live JavaScript clicks')
            assert before[2] != save()[2], 'clicks should repaint page text'
            key('alt+Left'); title('Start page')
            key('alt+Right'); title('The playground')
            key('ctrl+r'); time.sleep(.4)
            xdo('click','1')
            wait_for(lambda: logpath.read_text().count('[js] Playground clicks 1') >= 2, 'reload resets script state')
            first = save()
            key('Next'); time.sleep(.2)
            assert first[2] != save()[2], 'Page Down should scroll'
            key('Home')
            loads = logpath.read_text().count('[js] The playground is ready')
            key('ctrl+l'); key('ctrl+c'); key('ctrl+h'); title('Start page')
            key('ctrl+l'); key('ctrl+v'); key('Return')
            wait_for(lambda: logpath.read_text().count('[js] The playground is ready') > loads, 'clipboard address navigation')
            title('The playground')
            xdo('windowsize','--sync',window,'640','480')
            save((640,480))
            key('ctrl+q')
            assert process.wait(timeout=10) == 0, logpath.read_text()
            passed('live window, address/clipboard, clicks, history, reload, scrolling, resize, save, and quit')
        finally:
            if process.poll() is None:
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired): process.wait(timeout=5)
                if process.poll() is None: process.kill(); process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='../mayc/mayc_new')
    parser.add_argument('--require-network',action='store_true')
    parser.add_argument('--gui',action='store_true')
    options = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='maybrowser-tests-',dir=BUILD) as temporary:
            directory = Path(temporary)
            run((ROOT / options.compiler).resolve(), ROOT/'tests'/'state.may','-o',BUILD/'state-tests')
            state = run(BUILD/'state-tests',directory/'state.png')
            assert 'PASS browser navigation' in state, state
            coordinates = json.loads(next(line[5:] for line in state.splitlines() if line.startswith('META ')))
            passed('Maylang navigation, JavaScript, input, scrolling, clipping, URL resolution, and cleanup')
            test_cli(directory)
            test_scripts(directory)
            test_network(directory,options.require_network)
            if options.gui: test_gui(directory,coordinates)
            else: skipped('live window input', 'run with --gui under X11 or xvfb-run')
    finally:
        (BUILD/'test-report.json').write_text(json.dumps(RESULTS,indent=2)+'\n')
    print(f"{sum(r['status']=='pass' for r in RESULTS)} test groups passed", flush=True)


if __name__ == '__main__':
    main()
