#!/usr/bin/env python3
"""Check source-development prerequisites without installing or changing files."""
import argparse
import ctypes.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


PROFILES = {
    'build': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'test': ('cargo', 'rustc', 'cc', 'make', 'sha256sum', 'readelf'),
    'llvm': ('cargo', 'rustc', 'cc', 'make', 'sha256sum', 'readelf', 'clang'),
    'ui': ('cc', 'sha256sum'),
    'browser': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'package': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'editor': ('node', 'npm'),
}


def probe_c_compiler(cc):
    """Compile and link a minimal program with the selected compiler in a temporary directory."""
    remedy = 'install gcc or clang, or set CC to a working C compiler'
    with tempfile.TemporaryDirectory(prefix='maylang-doctor-') as directory:
        source = Path(directory) / 'probe.c'
        source.write_text('int main(void) { return 0; }\n')
        try:
            result = subprocess.run([cc, str(source), '-o', str(Path(directory) / 'probe')],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    text=True, errors='replace', timeout=30)
        except subprocess.TimeoutExpired:
            return False, f'{cc} timed out compiling a test program; {remedy}.'
        except OSError as error:
            return False, f'{cc} could not run ({error.strerror or error}); {remedy}.'
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        reason = f': {lines[0]}' if lines else ''
        return False, f'{cc} failed to compile a test program (exit {result.returncode}){reason}; {remedy}.'
    return True, cc


def inspect(profile):
    checks = []
    if profile != 'editor':
        checks.append(('Linux x86-64 host', platform.system() == 'Linux' and
                       platform.machine() in ('x86_64', 'amd64'),
                       'Use x86-64 Linux or an x86-64 WSL 2 distribution.'))
    minimum = (3, 12) if profile == 'package' else (3, 10)
    version = '.'.join(map(str, minimum))
    checks.append((f'Python {version}+', sys.version_info >= minimum,
                   f'Install Python {version} or newer.'))
    commands = {'cc': os.environ.get('CC', 'cc'), 'clang': os.environ.get('CLANG', 'clang')}
    for command in PROFILES[profile]:
        selected = commands.get(command, command)
        found = shutil.which(selected)
        if found and command == 'cc':
            checks.append((command, *probe_c_compiler(found)))
            continue
        checks.append((command, bool(found), found or f'Install {command} and add it to PATH.'))
    if profile in ('ui', 'browser', 'package'):
        cc = shutil.which(os.environ.get('CC', 'cc'))
        headers = False
        if cc:
            try:
                headers = subprocess.run([cc, '-E', '-x', 'c', '-'], input='#include <X11/Xlib.h>\n',
                                         text=True, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, timeout=10).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        checks.append(('X11 headers', headers, 'Install libx11-dev (Ubuntu/Debian).'))
        if profile in ('ui', 'package'):
            sokol = False
            if cc:
                try:
                    sokol = subprocess.run(
                        [cc, '-x', 'c', '-', '-o', os.devnull, '-lX11', '-lXi', '-lXcursor',
                         '-lGL', '-ldl', '-pthread', '-lm'],
                        input='#include <X11/extensions/XInput2.h>\n'
                              '#include <X11/Xcursor/Xcursor.h>\n#include <GL/gl.h>\n'
                              'int main(void) { return 0; }\n',
                        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=10).returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
            checks.append(('Sokol Linux libraries', sokol,
                           'Install libx11-dev libxi-dev libxcursor-dev libgl-dev (Ubuntu/Debian).'))
        font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        checks.append(('DejaVu font', font.is_file(), 'Install fonts-dejavu-core (Ubuntu/Debian).'))
    if profile == 'browser':
        for library in ('curl', 'duktape'):
            found = ctypes.util.find_library(library)
            checks.append((library, bool(found), found or f'Install the {library} shared library.'))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='build')
    args = parser.parse_args()
    checks = inspect(args.profile)
    for name, ready, detail in checks:
        print(f'{"OK" if ready else "MISSING"} {name}: {detail}')
    ready = all(check[1] for check in checks)
    if ready:
        print(f'Ready for {args.profile}. See CONTRIBUTING.md for commands.')
    else:
        print('Resolve the missing requirements and rerun this command. See docs/guide/DEVELOPMENT.md.')
    return 0 if ready else 1


if __name__ == '__main__':
    sys.exit(main())
