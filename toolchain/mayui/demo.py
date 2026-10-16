#!/usr/bin/env python3
"""Build and open the native UI showcase, or save a display-free preview."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dark', action='store_true')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='may-ui-demo-') as temporary:
        directory = Path(temporary)
        native = ROOT / 'stdlib/ui/native'
        env = dict(os.environ, MAYLANG_STDLIB=str(ROOT / 'stdlib'),
                   LD_LIBRARY_PATH=str(directory) + ':' + os.environ.get('LD_LIBRARY_PATH', ''))
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
                        str(native / 'draw.c'), str(native / 'sokol.c'), '-o', str(directory / 'libmayui.so'),
                        '-lX11', '-lXi', '-lXcursor', '-lGL', '-ldl', '-pthread', '-lm'], check=True, env=env)
        subprocess.run([str(args.compiler.resolve()), str(ROOT / 'examples/ui_showcase.may'),
                        '-o', str(directory / 'showcase')], check=True, env=env)
        command = [str(directory / 'showcase')]
        if args.dark:
            command += ['--dark']
        if args.snapshot:
            command += ['--snapshot', str(args.snapshot.resolve())]
        subprocess.run(command, check=True, env=env)
        if args.snapshot:
            print(args.snapshot.resolve())


if __name__ == '__main__':
    main()
