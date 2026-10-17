#!/usr/bin/env python3
"""Signed constant division/remainder, runtime fallbacks and actual x86 code."""
import argparse
from pathlib import Path
import random
import re
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def trunc_div(value, divisor):
    return abs(value) // abs(divisor) * (-1 if (value < 0) != (divisor < 0) else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    rng = random.Random(20261015)
    values = [-(1 << 60), -(1 << 60) + 1, -1073741825, -1025, -17, -9, -8, -7,
              -1, 0, 1, 7, 8, 9, 17, 1025, 1073741825, (1 << 60) - 1]
    values += [rng.randrange(-(1 << 60), 1 << 60) for _ in range(160)]
    divisors = [1, 2, 4, 8, 16, 1024, 1 << 30, 3, 1 << 31, -2]
    functions = []
    for index, divisor in enumerate(divisors):
        for operation, symbol in [('div', '/'), ('mod', '%')]:
            functions.append(f'fun probe_{operation}_{index}(n: Any) -> Any {{ return n {symbol} {divisor}; }}')
    body = ['let values: List<Int> = [' + ','.join(map(str, values)) + '];', 'for n: Int in values {']
    expected = []
    for number in values:
        for divisor in divisors:
            quotient = trunc_div(number, divisor)
            expected.append(f'{quotient} {number - quotient * divisor}\n')
    for index, _ in enumerate(divisors):
        body.append(f'print(probe_div_{index}(n), probe_mod_{index}(n));')
    body += ['}', 'print(probe_div_3(20.0) == 2.5, probe_div_3(-20.0) == -2.5);',
             'let custom: Any = {"/": fun(a: Any, b: Any) -> Any { return 99; }}; print(probe_div_3(custom));',
             'print(may { probe_mod_3(2.0); "missed" } otherwise { err.kind });',
             'print(may { probe_div_3("bad"); "missed" } otherwise { err.kind });',
             'print(may { probe_mod_3("bad"); "missed" } otherwise { err.kind });',
             'fun zero(n: Int) -> Int { return n / 0; }',
             'fun negative_one(n: Int) -> Int { return n / -1; }',
             'print(may { zero(1); "missed" } otherwise { err.kind });',
             'print(may { negative_one(-1152921504606846976); "missed" } otherwise { err.kind });']
    expected = ''.join(expected).encode() + b'true true\n99\ntype\ntype\ntype\narithmetic\narithmetic\n'
    with tempfile.TemporaryDirectory(prefix='may-strength-reduction-') as temporary:
        directory = Path(temporary)
        source = directory / 'division.may'
        source.write_text('\n'.join(functions + body))
        for target in (['x86_64-linux', 'clang-llvm'] if args.llvm else ['x86_64-linux']):
            binary = directory / target
            subprocess.run([compiler, '--target', target, source, '-o', binary], check=True, capture_output=True, timeout=180)
            result = subprocess.run([binary], capture_output=True, timeout=30)
            assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result
            if target == 'x86_64-linux':
                assembly = subprocess.check_output(['objdump', '-d', '-Mintel', '--no-show-raw-insn', binary], text=True)
                blocks = re.split(r'(?m)^\w+ <(.+)>:\n', assembly)
                functions_asm = dict(zip(blocks[1::2], blocks[2::2]))
                for index in range(7):
                    for operation in ('div', 'mod'):
                        name = next(n for n in functions_asm if n.endswith(f'::probe_{operation}_{index}'))
                        assert not re.search(r'\bidiv\b', functions_asm[name]), name
                name = next(n for n in functions_asm if n.endswith('::probe_div_7'))
                assert re.search(r'\bidiv\b', functions_asm[name]), 'non-power divisor lost the general path'
            print(f'PASS {target}: {len(values) * len(divisors)} signed boundaries/random pairs, fallbacks and arithmetic failures')
        # The same emitter helper serves unboxed runtime arithmetic.
        source.write_text('fun probe_raw(n: Any) -> Any { return n / 8 + n % 8; }\n' +
                          '\n'.join(f'if probe_raw({n}) != {trunc_div(n, 8) + n - trunc_div(n, 8) * 8} {{ exit(11); }}' for n in values) + '\nexit(0);')
        binary = directory / 'raw'
        subprocess.run([compiler, '--raw', source, '-o', binary], check=True, capture_output=True, timeout=180)
        subprocess.run([binary], check=True, timeout=30)
        print('PASS raw signed power-of-two division/remainder helper')


if __name__ == '__main__':
    main()
