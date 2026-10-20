#!/usr/bin/env python3
"""Compare portable values, calls, faults, fibers, floats and comparisons on every target."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import random
import struct

from backends import compile_source
from core_runtime import emulate
from fibers import CASES as FIBER_CASES
from float_literals import LITERALS

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
FAULT_EXPECTED = (b'42\n["fail", "explicit"]\nrender\narithmetic\ntype\nfirst\nsecond\n'
                  b'7\n3 once\n4\nexception handler limit exceeded\nafter\n')
DEBUG_EXPECTED = b'true true true\ntrue false true\ntrue\nfalse\n'
FLOAT_EXPECTED = (b'3.75 5.0 3.0 3.5 -2.5 2.5\n'
                  b'0.3333333333333333 0.30000000000000004 6.5\n'
                  b'-3.0 -2.0 -2 2.0 3.0 -2.0 3.0\n4.0 true true\n-122.5 42.0 3 -3\n'
                  b'true true true true true true\nfalse true true true\n'
                  b'[1.25, -2.5] {"number": 3.75}\narithmetic\n'
                  b'true false true true true true\nnan\n'
                  b'arithmetic Float outside Int range -1152921504606846976 arithmetic\n3.75\n1.0 1e20 1e-10\n3.5\n')
ROUNDING_EXPECTED = (b'2.0 3.0 -3.0 -2.0 -0.0 -0.0 0.0\ntrue true nan -inf\n'
                     b'3.0 -2.0 2.0 0.0 -0.0\ntrue true true true\n')
FIBER_EXPECTED = b'true false\na a\ntrue false\nb b\nmain\n'
COMPARE_EXPECTED = (b'true false true true true false true false false\ntrue 1\none letter other other\n'
                    b'type: cannot compare Float with Int\ntype: cannot compare Nil with Int\n'
                    b'type: cannot compare List with Map\ntrue true true true\n')


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
        for name, expected in [('portable_collections', EXPECTED), ('portable_calls', CALL_EXPECTED),
                               ('portable_faults', FAULT_EXPECTED), ('portable_debug', DEBUG_EXPECTED),
                               ('portable_fibers', FIBER_EXPECTED), ('portable_floats', FLOAT_EXPECTED),
                               ('portable_compare', COMPARE_EXPECTED),
                               ('portable_rounding', ROUNDING_EXPECTED)]:
            source = HERE / 'backend' / (name + '.may')
            flags = ['--debug'] if name in ('portable_debug', 'portable_fibers') else []
            oracle = work / 'full'
            compile_source(options.compiler, source, oracle, *flags)
            result = subprocess.run([str(oracle)], capture_output=True, timeout=20)
            assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result
            for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
                binary = work / target
                image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target, *flags)
                if target == 'x86_64-linux':
                    result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result
                if have_emulation:
                    emulate(image, target, expected, 0)
                    if target == 'arm64-macos':
                        emulate(image, target, expected, 0, slide=0x12000000)
                print(f'PASS {target}: {name}' +
                      ('' if have_emulation else ' (execution skipped: install Unicorn)'), flush=True)
        source = work / 'float-bits.may'
        rng = random.Random(20917)
        body = [
            'fun bits(value: Any) -> Nil { let p: Any = addr(value); print(load32(p), load32(p + 4)); return; }',
            'fun number(low: Int, high: Int) -> Float { let value: Float = 0.0; let p: Any = addr(value); store32(p, low); store32(p + 4, high); return value; }',
            'fun narrow(value: Float32) -> Float32 { return value; }',
            # Out-of-range and non-finite conversions fault identically on every target.
            'fun convert(value: Float) -> Nil { print(may { str(int(value)) } otherwise { err.kind }, may { str(floor(value)) } otherwise { err.kind },'
            ' may { str(ceil(value)) } otherwise { err.kind }, may { str(trunc(value)) } otherwise { err.kind }); return; }',
        ]
        for literal in LITERALS:
            body.append(f'bits({literal}); bits(-{literal}); bits(narrow({literal}));')
        for _ in range(32):
            a, b = [repr(rng.uniform(-10000, 10000)) for _ in range(2)]
            for operator in ['+', '-', '*', '/']:
                body.append(f'bits({a} {operator} {b});')
        for raw in [1, 0x8000000000000001, 0x0010000000000000, 0x3fefffffffffffff,
                    0x43dfffffffffffff, 0x43e0000000000000, 0xc3e0000000000000,
                    0x7ff0000000000000, 0xfff0000000000000, 0x7ff8000000000000]:
            low, high = struct.unpack('<II', struct.pack('<Q', raw))
            body.append(f'convert(number({low}, {high}));')
        body.append('print(str(number(0, 2146435072)), str(number(0, 4293918720))); exit(0);')
        source.write_text('\n'.join(body))
        binary = work / 'float-oracle'
        compile_source(options.compiler, source, binary)
        oracle = subprocess.run([str(binary)], capture_output=True, timeout=20)
        assert oracle.returncode == 0 and not oracle.stderr, oracle
        for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
            binary = work / target
            image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
            if target == 'x86_64-linux':
                result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                assert result.returncode == 0 and not result.stderr, result
                assert result.stdout == oracle.stdout, (target, [(i, a, b) for i, (a, b) in enumerate(zip(oracle.stdout.splitlines(), result.stdout.splitlines())) if a != b][:10])
            if have_emulation:
                emulate(image, target, oracle.stdout, 0)
            print(f'PASS {target}: binary64 bits, binary32 rounding and conversion limits', flush=True)
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
        for name, (text, status, expected) in FIBER_CASES.items():
            source = work / 'fibers.may'
            source.write_text(text + '\nexit(0);\n')
            if name == 'uncaught':
                expected = b'worker\n'  # Core retains plain uncaught diagnostics.
            for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
                binary = work / target
                image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
                if target == 'x86_64-linux':
                    result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                    assert (result.returncode, result.stdout, result.stderr) == (status, expected, b''), result
                if have_emulation:
                    emulate(image, target, expected, status)
            print(f'PASS portable fiber isolation: {name}', flush=True)


if __name__ == '__main__':
    main()
