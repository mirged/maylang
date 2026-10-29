#!/usr/bin/env python3
"""Check Float display and parsing against Python on every backend.

`str`, `print` and nested display must produce the shortest digits that parse
back to the same value (Python's `repr` digits in Maylang's layout), and
`float(text)` and JSON numbers must be correctly rounded.
"""
import argparse
from decimal import Decimal
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile

from backends import compile_source
from core_runtime import emulate

TARGETS = ['arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']
# __math_bits (runtime/math.may) builds a Float from its 32-bit halves with
# either value representation.
PRELUDE = 'fun bits(low: Int, high: Int) -> Float { return float(__math_bits(low, high)); }\n'
FIXED = (
    'let z: Float = 0.0;\n'
    'print(0.1, 1.0 / 3.0, 100.0, 1e16, 1e15, 0.0001, 0.00001, 5e-324, 1.7976931348623157e308, z * -1.0, -2.5);\n'
    'print([0.1, 2.5, -0.0001, 1e20], {"x": 0.86231887228768382});\n'
    'print(float("0.1"), float(" 2.5e-3 "), float("-0"), float("1.7976931348623159e308"), '
    'float("2.4703282292062328e-324"), float("+6.07710050630396597660e-11"));\n'
    'let bad: Any = may { float("1.2.3") } otherwise { err.message };\n'
    'print(bad);\n'
)
FIXED_EXPECTED = (b'0.1 0.3333333333333333 100.0 1e16 1000000000000000.0 0.0001 1e-5 5e-324 1.7976931348623157e308 -0.0 -2.5\n'
                  b'[0.1, 2.5, -0.0001, 1e20] {"x": 0.8623188722876838}\n'
                  b'0.1 0.0025 -0.0 inf 5e-324 6.077100506303966e-11\n'
                  b'cannot convert to Float\n')


def layout(value):
    """Python's shortest repr digits in Maylang's display layout."""
    if value == 0:
        return '-0.0' if struct.pack('<d', value)[7] & 128 else '0.0'
    _, digits, exponent = Decimal(repr(value)).normalize().as_tuple()
    text = ''.join(map(str, digits))
    point = len(text) - 1 + exponent
    sign = '-' if value < 0 else ''
    if point >= 16 or point < -4:
        return sign + text[0] + ('.' + text[1:] if len(text) > 1 else '') + 'e' + str(point)
    if point < 0:
        return sign + '0.' + '0' * (-point - 1) + text
    if len(text) <= point + 1:
        return sign + text + '0' * (point + 1 - len(text)) + '.0'
    return sign + text[:point + 1] + '.' + text[point + 1:]


def samples(count):
    rng = random.Random(3301)
    values = [0.1 * i for i in range(1, 60)] + [rng.uniform(-1000, 1000) for _ in range(count // 4)]
    while len(values) < count:
        value = struct.unpack('<d', struct.pack('<Q', rng.getrandbits(64)))[0]
        if value == value and abs(value) != float('inf'):
            values.append(value)
    return values


def program(values):
    lines = [PRELUDE]
    for value in values:
        low, high = struct.unpack('<II', struct.pack('<d', value))
        lines.append(f'print(bits({low}, {high})); print(float("{value!r}") == bits({low}, {high}));')
    return '\n'.join(lines) + '\nexit(0);\n'


def expected(values):
    return ''.join(f'{layout(value)}\ntrue\n' for value in values).encode()


def run(binary):
    result = subprocess.run([str(binary)], capture_output=True, timeout=120)
    assert result.returncode == 0 and not result.stderr, result
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--require-emulation', action='store_true')
    parser.add_argument('--clang', default='clang')
    options = parser.parse_args()
    try:
        import unicorn  # noqa: F401
        have_emulation = True
    except ImportError:
        have_emulation = False
    assert have_emulation or not options.require_emulation, 'Unicorn is required'
    have_llvm = shutil.which(options.clang) is not None
    modes = [('full', []), ('core', ['--runtime', 'core'])] + ([('llvm', ['--target', 'clang-llvm'])] if have_llvm else [])
    with tempfile.TemporaryDirectory(prefix='mayc-float-text-') as directory:
        work = Path(directory)
        source = work / 'text.may'
        source.write_text(FIXED + 'exit(0);\n')
        for name, flags in modes:
            compile_source(options.compiler, source, work / name, *flags)
            assert run(work / name) == FIXED_EXPECTED, (name, run(work / name))
        source.write_text(FIXED + 'print(json_parse("[0.1, 1e-7, 3.141592653589793238, -0.0]"));\nexit(0);\n')
        for name, flags in modes[:1] + modes[2:]:
            compile_source(options.compiler, source, work / name, *flags)
            assert run(work / name) == FIXED_EXPECTED + b'[0.1, 1e-7, 3.141592653589793, -0.0]\n', (name, run(work / name))
        print('PASS fixed display, nested display, float() edge cases and JSON numbers', flush=True)

        values = samples(1200)
        source.write_text(program(values))
        want = expected(values)
        for name, flags in modes:
            if name == 'llvm':
                source.write_text(program(values[:200]))
                want = expected(values[:200])
            compile_source(options.compiler, source, work / name, *flags)
            got = run(work / name)
            mismatches = [(value, a, b) for value, a, b in zip(values, got.decode().splitlines()[::2],
                                                              want.decode().splitlines()[::2]) if a != b]
            assert got == want, (name, mismatches[:5])
        print(f'PASS shortest round-trip display and correctly rounded float() ({len(values)} values; '
              + ', '.join(name for name, _ in modes) + ')', flush=True)
        if have_emulation:
            # Each conversion costs about two million emulated RISC-V instructions,
            # so keep every program well inside the emulator's budget.
            for start in range(0, 40, 5):
                chunk = values[start:start + 5]
                source.write_text(program(chunk))
                for target in TARGETS:
                    image = compile_source(options.compiler, source, work / target, '--runtime', 'core', '--target', target)
                    emulate(image, target, expected(chunk), 0)
            print('PASS display and parsing are identical on every core target', flush=True)


if __name__ == '__main__':
    main()
