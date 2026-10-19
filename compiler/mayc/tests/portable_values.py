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
CALL_EXPECTED = (b'42 10\n150 120\n3 4\n8\n10 11 12\n'
                 b'[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]\n'
                 b'[21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]\n'
                 b'[1, 2, nil, nil, nil, nil, nil, nil, nil, nil, nil, nil]\n'
                 b'[2, 3, 4] [2, 4]\n6\n4 6\n')


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
        for name, expected in [('portable_collections', EXPECTED), ('portable_calls', CALL_EXPECTED)]:
            source = HERE / 'backend' / (name + '.may')
            oracle = work / 'full'
            compile_source(options.compiler, source, oracle)
            result = subprocess.run([str(oracle)], capture_output=True, timeout=20)
            assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result
            for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
                binary = work / target
                image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
                if target == 'x86_64-linux':
                    result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result
                if have_emulation:
                    emulate(image, target, expected, 0)
                    if target == 'arm64-macos':
                        emulate(image, target, expected, 0, slide=0x12000000)
                print(f'PASS {target}: {name}' +
                      ('' if have_emulation else ' (execution skipped: install Unicorn)'), flush=True)
        for value in ['0', '1152921504606846975', 'nil', 'true', '"text"', '[]', '{"a": 1}']:
            source = work / 'invalid.may'
            source.write_text('let good: Any = fun() -> Int { return 1; }; print(good());'
                              f'let bad: Any = {value}; bad(); exit(0);')
            expected = b'1\nvalue is not callable\n'
            for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
                binary = work / target
                image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
                if target == 'x86_64-linux':
                    result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                    assert (result.returncode, result.stdout, result.stderr) == (70, expected, b''), result
                if have_emulation:
                    emulate(image, target, expected, 70)
        print('PASS invalid callable values are rejected safely on every target', flush=True)


if __name__ == '__main__':
    main()
