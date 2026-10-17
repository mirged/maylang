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


PROFILES = {
    'build': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'test': ('cargo', 'rustc', 'cc', 'make', 'sha256sum', 'readelf'),
    'ui': ('cc', 'sha256sum'),
    'browser': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'package': ('cargo', 'rustc', 'cc', 'make', 'sha256sum'),
    'editor': ('node', 'npm'),
}


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
    for command in PROFILES[profile]:
        selected = os.environ.get('CC', 'cc') if command == 'cc' else command
        found = shutil.which(selected)
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
