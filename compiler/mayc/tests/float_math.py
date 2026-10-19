#!/usr/bin/env python3
"""Check transcendental functions and floating powers on every backend.

The full runtime uses x87 instructions, LLVM uses the platform libm and the
portable core runtime uses its own binary64 implementation. IEEE special
cases must agree exactly everywhere; portable results must stay within one
ulp of the host libm and be bit-identical on every core target.
"""
import argparse
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile

from backends import compile_source
from core_runtime import emulate

TARGETS = ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']
PRELUDE = '''let z: Float = 0.0;
let inf: Float = 1e308 * 10.0;
let nan: Float = inf - inf;
let nz: Float = z * -1.0;
fun high(v: Any) -> Int { return load32(addr(v) + 4); }
'''
# Each line runs as its own program so emulation stays within its budget.
SPECIAL = [
    ('print(sin(z), sin(nz), cos(z), tan(nz), sin(inf), cos(nan), tan(0.0 - inf));',
     '0.0 -0.0 1.0 -0.0 nan nan nan'),
    ('print(ln(1.0), ln(z), ln(-1.0), ln(inf), ln(nan), log2(1024.0), log2(0.5), log10(1000.0), log10(0.001), log10(1e300));',
     '0.0 -inf nan inf nan 10.0 -1.0 3.0 -3.0 300.0'),
    ('print(exp(z), exp(inf), exp(0.0 - inf), exp(710.0), exp(-746.0), exp(nan));',
     '1.0 inf 0.0 inf 0.0 nan'),
    ('print(pow(2.0, 3.0), pow(-2.0, 3.0), pow(-2.0, 2.0), pow(-8.0, 0.5), pow(nan, z), pow(1.0, nan), pow(nan, 1.0));',
     '8.0 -8.0 4.0 nan 1.0 1.0 nan'),
    ('print(pow(z, 3.0), pow(nz, 3.0), pow(nz, 2.0), pow(z, -1.0), pow(nz, -1.0), pow(nz, -2.0), pow(z, inf), pow(z, 0.0 - inf));',
     '0.0 -0.0 0.0 inf -inf inf 0.0 inf'),
    ('print(pow(inf, 0.5), pow(inf, -0.5), pow(0.0 - inf, 3.0), pow(0.0 - inf, 2.0), pow(0.0 - inf, -3.0), pow(-1.0, inf), '
     'pow(0.5, inf), pow(2.0, inf), pow(0.5, 0.0 - inf), pow(2.0, 0.0 - inf));',
     'inf 0.0 -inf inf -0.0 1.0 0.0 inf inf 0.0'),
    ('print(pow(2.0, 1024.0), pow(2.0, -1075.0), pow(2.0, -1074.0), pow(9.0, 0.5), pow(10.0, 2.0), pow(2.0, 0.5));',
     'inf 0.0 5e-324 3.0 100.0 1.4142135623730951'),
    ('print(pow(2, 8), pow(2, -1), pow(1.5, 2), 2 ** 10, 2.0 ** 10, 2 ** -2, 9.0 ** 0.5);',
     '256.0 0.5 2.25 1024 1024.0 0.25 3.0'),
    ('print(sqrt(4), floor(3), ceil(3), trunc(-3), sin(0), cos(0), exp(0), ln(1), log2(8), log10(100), tan(0));',
     '2.0 3 3 -3 0.0 1.0 1.0 0.0 3.0 2.0 0.0'),
    # Signed zeros display as -0.0; also compare their sign bits.
    ('print(high(sin(nz)), high(tan(nz)), high(pow(nz, 3.0)), high(pow(nz, 2.0)), high(pow(0.0 - inf, -3.0)), high(pow(-0.5, 1075.0)));',
     '2147483648 2147483648 2147483648 0 2147483648 2147483648'),
    ('let a: Any = 1.5; let b: Any = nil; print(a != b, b != a, a == b, a < 2.0, a != 1.5);',
     'true true false true false'),
]


def run_binary(binary):
    result = subprocess.run([str(binary)], capture_output=True, timeout=30)
    assert result.returncode == 0 and not result.stderr, result
    return result.stdout


def bits_program(calls):
    return ('fun bits(value: Any) -> Nil { let p: Any = addr(value); print(load32(p), load32(p + 4)); return; }\n'
            + '\n'.join(f'bits({call});' for call in calls) + '\nexit(0);\n')


def decode(output):
    values = []
    for line in output.decode().splitlines():
        low, high = map(int, line.split())
        values.append(struct.unpack('<d', struct.pack('<II', low, high))[0])
    return values


def accuracy_cases():
    rng = random.Random(4211)
    cases = []
    for _ in range(60):
        large = rng.choice([1, -1]) * 10 ** rng.uniform(6, 308)
        cases += [('sin', (rng.uniform(-100, 100),)), ('cos', (rng.uniform(-100, 100),)),
                  ('tan', (rng.uniform(-10, 10),)), ('sin', (large,)), ('cos', (large,)), ('tan', (large,)),
                  ('ln', (math.exp(rng.uniform(-700, 700)),)), ('log2', (math.exp(rng.uniform(-700, 700)),)),
                  ('log10', (math.exp(rng.uniform(-700, 700)),)), ('exp', (rng.uniform(-740, 709),)),
                  ('pow', (rng.uniform(0, 100), rng.uniform(-100, 100))),
                  ('pow', (rng.uniform(0.5, 2), rng.uniform(-1000, 1000))),
                  ('pow', (-rng.uniform(0, 10), float(rng.randint(-60, 60))))]
    # Subnormal inputs and outputs.
    cases += [('ln', (5e-324,)), ('log2', (1e-310,)), ('exp', (-744.0,)), ('pow', (2.0, -1070.5))]
    return cases


def oracle(name, args):
    if name == 'pow':
        try:
            return math.pow(*args)
        except OverflowError:
            return math.inf
    return {'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'ln': math.log,
            'log2': math.log2, 'log10': math.log10, 'exp': math.exp}[name](*args)


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
    with tempfile.TemporaryDirectory(prefix='mayc-float-math-') as directory:
        work = Path(directory)
        source = work / 'special.may'
        for line, expected in SPECIAL:
            source.write_text(PRELUDE + line + '\nexit(0);\n')
            want = (expected + '\n').encode()
            compile_source(options.compiler, source, work / 'full')
            assert run_binary(work / 'full') == want, ('full', line, run_binary(work / 'full'))
            if have_llvm:
                compile_source(options.compiler, source, work / 'llvm', '--target', 'clang-llvm')
                assert run_binary(work / 'llvm') == want, ('llvm', line, run_binary(work / 'llvm'))
            for target in TARGETS:
                image = compile_source(options.compiler, source, work / target, '--runtime', 'core', '--target', target)
                if target == 'x86_64-linux':
                    assert run_binary(work / target) == want, (target, line, run_binary(work / target))
                if have_emulation:
                    emulate(image, target, want, 0)
        print('PASS IEEE special cases, Int arguments and signed zeros agree on full, '
              + ('LLVM ' if have_llvm else '') + 'and core runtimes'
              + ('' if have_emulation else ' (core emulation skipped: install Unicorn)')
              + ('' if have_llvm else ' (LLVM skipped: clang unavailable)'), flush=True)

        cases = accuracy_cases()
        calls = [f'{name}({", ".join(repr(value) for value in args)})' for name, args in cases]
        source.write_text(bits_program(calls))
        compile_source(options.compiler, source, work / 'core', '--runtime', 'core')
        native = run_binary(work / 'core')
        worst = 0.0
        for (name, args), got in zip(cases, decode(native)):
            want = oracle(name, args)
            if got != want:
                error = abs(got - want) / math.ulp(want) if math.isfinite(want) and want != 0.0 else math.inf
                assert error <= 1.0, (name, args, got, want)
                worst = max(worst, error)
        print(f'PASS portable transcendentals and powers within {worst:.0f} ulp of the host libm ({len(cases)} inputs)', flush=True)
        # Full and LLVM share the portable trigonometry; their x87/libm logs,
        # exp and pow may differ from core only in the last place.
        portable = decode(native)
        for name, flags in [('full', [])] + ([('llvm', ['--target', 'clang-llvm'])] if have_llvm else []):
            compile_source(options.compiler, source, work / name, *flags)
            for (function, args), got, core in zip(cases, decode(run_binary(work / name)), portable):
                if function in ('sin', 'cos', 'tan'):
                    assert struct.pack('<d', got) == struct.pack('<d', core), (name, function, args, got, core)
                elif got != core:
                    want = oracle(function, args)
                    assert math.isfinite(want) and abs(got - want) <= math.ulp(want), (name, function, args, got, want)
        print('PASS full' + (' and LLVM' if have_llvm else '') + ' trigonometry matches core bit for bit', flush=True)
        if have_emulation:
            lines = native.splitlines(keepends=True)
            for start in range(0, len(calls), 24):
                source.write_text(bits_program(calls[start:start + 24]))
                expected = b''.join(lines[start:start + 24])
                for target in TARGETS[1:]:
                    image = compile_source(options.compiler, source, work / target, '--runtime', 'core', '--target', target)
                    emulate(image, target, expected, 0)
            print('PASS portable math results are bit-identical on every core target', flush=True)


if __name__ == '__main__':
    main()
