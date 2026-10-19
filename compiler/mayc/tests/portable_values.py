#!/usr/bin/env python3
"""Compare portable collection/record semantics on every emitted target."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import compile_source
from core_runtime import emulate

HERE = Path(__file__).resolve().parent
EXPECTED = ('9 4 42 -1\n'
            '7 [1, 8] λ nil 3\n'
            '{"a": 7, "b": [1, 8], "c": "λ"}\n'
            'one two nil [1, -2, 3] ["one", "two", "three"]\n'
            'true false\n99 true 4\n{"a": 3, "b": 2}\n'
            '100 4950 500 nil\n'
            'false {"items": [1, {"n": 2}], "self": <cycle>}\nfalse\n').encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--require-emulation', action='store_true')
    options = parser.parse_args()
    try:
        import unicorn
        have_emulation = True
    except ImportError:
        have_emulation = False
    assert have_emulation or not options.require_emulation, 'Unicorn is required'
    with tempfile.TemporaryDirectory(prefix='mayc-portable-values-') as directory:
        work = Path(directory)
        source = HERE / 'backend/portable_collections.may'
        oracle = work / 'full'
        compile_source(options.compiler, source, oracle)
        result = subprocess.run([str(oracle)], capture_output=True, timeout=20)
        assert (result.returncode, result.stdout, result.stderr) == (0, EXPECTED, b''), result
        for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
            binary = work / target
            image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
            if target == 'x86_64-linux':
                result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                assert (result.returncode, result.stdout, result.stderr) == (0, EXPECTED, b''), result
            if have_emulation:
                emulate(image, target, EXPECTED, 0)
                if target == 'arm64-macos':
                    emulate(image, target, EXPECTED, 0, slide=0x12000000)
            print(f'PASS {target}: maps, records, structs, enums, hashing and cycles' +
                  ('' if have_emulation else ' (execution skipped: install Unicorn)'), flush=True)


if __name__ == '__main__':
    main()
