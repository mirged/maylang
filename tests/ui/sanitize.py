#!/usr/bin/env python3
"""Run the native UI adapter on malformed input under AddressSanitizer and UBSan.

Builds stdlib/ui/native/draw.c with tests/ui/sanitize.c, then runs each case in
its own process. Any sanitizer report, crash or wrong result fails the run.
Reports are written to --reports (kept as a CI artifact). Needs a C compiler
with ASan/UBSan runtimes (GCC with libasan/libubsan, or Clang); no display.
"""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'stdlib/ui/native'
SYSTEM_FONTS = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
                '/usr/share/fonts/TTF/DejaVuSans.ttf']
FLAGS = ['-g', '-O1', '-fno-omit-frame-pointer', '-fsanitize=address,undefined,float-cast-overflow',
         '-fno-sanitize-recover=all', '-Wall', '-Wextra', '-Werror']


def sfnt(tables, declared=None):
    """An sfnt header whose table records are (tag, offset, length)."""
    header = struct.pack('>IHHHH', 0x00010000, len(tables) if declared is None else declared, 0, 0, 0)
    return header + b''.join(struct.pack('>4sIII', tag, 0, offset, length) for tag, offset, length in tables)


def fixtures(system_font):
    """Deterministic malformed fonts, by name."""
    required = [b'cmap', b'head', b'hhea', b'hmtx', b'loca', b'glyf', b'maxp']
    cases = {
        'one-byte': b'\0',
        'magic-only': b'\0\1\0\0',
        'collection-truncated': b'ttcf\0\1\0\0',
        'collection-offset-past-end': b'ttcf\0\1\0\0' + struct.pack('>II', 1, 0x7fffffff),
        'collection-offset-negative': b'ttcf\0\1\0\0' + struct.pack('>II', 1, 0xfffffff0),
        'header-only': sfnt([], declared=40),
        'directory-truncated': sfnt([(tag, 0, 0) for tag in required])[:40],
        'tables-past-end': sfnt([(tag, 0x10000, 64) for tag in required]),
        'table-length-overflow': sfnt([(tag, 12, 0xffffffff) for tag in required]),
    }
    state = 0x2545F491
    noise = bytearray()
    for _ in range(4096):
        state = (state * 1103515245 + 12345) & 0x7fffffff
        noise.append(state >> 16 & 255)
    cases['noise-with-magic'] = b'\0\1\0\0' + bytes(noise)
    if system_font:
        data = Path(system_font).read_bytes()
        cases['truncated-real-font'] = data[:len(data) // 2]
        cases['real-font-directory-only'] = data[:12 + 16 * struct.unpack('>H', data[4:6])[0]]
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    parser.add_argument('--reports', type=Path, help='directory for sanitizer reports (default: temporary)')
    options = parser.parse_args()
    if not shutil.which(options.cc):
        print(f'SKIP sanitizer adapter tests: {options.cc} not found')
        return 0
    with tempfile.TemporaryDirectory(prefix='may-ui-sanitize-') as temporary:
        work = Path(temporary)
        reports = (options.reports or work / 'reports').resolve()
        reports.mkdir(parents=True, exist_ok=True)
        binary = work / 'sanitize'
        subprocess.run([options.cc, *FLAGS, str(NATIVE / 'draw.c'), str(Path(__file__).with_name('sanitize.c')),
                        '-o', str(binary), '-lm'], check=True)
        system_font = next((path for path in SYSTEM_FONTS if Path(path).is_file()), None)
        runs = [(name, name, None) for name in ('geometry', 'bitmap', 'text')]
        for name, content in fixtures(system_font).items():
            path = work / f'{name}.ttf'
            path.write_bytes(content)
            runs.append((f'font:{name}', 'font', path))
        failures, skipped = [], []
        for label, case, font in runs:
            environment = dict(os.environ, MAYUI_RENDERER='cpu',
                               ASAN_OPTIONS=f'detect_leaks=0:abort_on_error=0:log_path={reports / label.replace(":", "-")}',
                               UBSAN_OPTIONS='print_stacktrace=1:halt_on_error=1')
            environment.pop('MAYUI_FONT', None)
            if font:
                environment['MAYUI_FONT'] = str(font)
            result = subprocess.run([str(binary), case], env=environment, capture_output=True, text=True, timeout=300)
            # UBSan prints to stderr even with log_path; keep it beside the ASan report.
            if result.stderr:
                (reports / f'{label.replace(":", "-")}.stderr').write_text(result.stderr)
            if result.returncode == 2 and not font:
                skipped.append(label)
            elif result.returncode or 'runtime error' in result.stderr:
                failures.append(f'{label}: exit {result.returncode}\n{result.stderr[-4000:]}')
            elif font and system_font and 'fallback font' not in result.stdout:
                failures.append(f'{label}: did not fall back to {system_font}')
        for failure in failures:
            print(f'FAIL {failure}', file=sys.stderr)
        if skipped:
            print(f'SKIP {", ".join(skipped)}: no usable system font')
        print(f'{"FAIL" if failures else "PASS"} native UI adapter under ASan/UBSan: '
              f'{len(runs) - len(failures) - len(skipped)}/{len(runs)} malformed-input cases' + (f', reports in {reports}' if options.reports else ''))
        return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
