#!/usr/bin/env python3
"""Check native-word lowering of strictly typed Int functions (#92).

Qualifying functions compute with untagged 64-bit words. Calls from tagged
code untag arguments and retag the result, so values beyond the tagged range
fault only when they leave native code. A seeded oracle compares random
expressions with Python's signed 64-bit semantics on the full and core
runtimes, with and without --debug, and on ARM64/RISC-V core targets when
QEMU user emulators are installed.
"""
import argparse
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TAGGED = 1 << 60
WORD = 1 << 63

SEMANTICS = '''
fun fib(n: Int) -> Int {
    if (n < 2) { return n; }
    return fib(n - 1) + fib(n - 2);
}
fun gcd(a: Int, b: Int) -> Int {
    mut x: Int = a;
    mut y: Int = b;
    while (y != 0) {
        let t: Int = x % y;
        x = y;
        y = t;
    }
    return x;
}
fun top_bit() -> Int { return 1 << 63; }
fun has_top(x: Int) -> Int {
    if ((x & top_bit()) != 0) { return 1; }
    return 0;
}
fun wide(x: Int) -> Int { return (x << 62) >> 62; }
fun div(a: Int, b: Int) -> Int { return a / b; }
fun rem(a: Int, b: Int) -> Int { return a % b; }
fun shl(a: Int, b: Int) -> Int { return a << b; }
fun mul(a: Int, b: Int) -> Int { return a * b; }
fun neg(a: Int) -> Int { return -a; }
fun big() -> Int { return 1 << 61; }
fun even(n: Int) -> Int { if (n == 0) { return 1; } return odd(n - 1); }
fun odd(n: Int) -> Int { if (n == 0) { return 0; } return even(n - 1); }
fun count(n: Int) -> Int {
    mut i: Int = 0;
    mut total: Int = 0;
    while (i < n and not (total < 0)) {
        i = i + 1;
        if (i % 3 == 0) { continue; }
        if (i > 1000) { break; }
        total = total + i;
    }
    return total;
}
fun tagged(n: Int) -> Int { print("tagged ${n}"); return n + 1; }
fun mixed(n: Int) -> Int { return tagged(n) * 2; }
fun tagged_top() -> Int { print("tagged"); return 1 << 63; }

print(fib(20), gcd(1071, 462));
print(has_top(-1), has_top(5), wide(1), wide(3));
print(div(-7, 2), rem(-7, 2), div(7, -1), rem(7, -1));
print(even(11), odd(11), count(100), mixed(4));
let f: (Int) -> Int = fib;
print(f(10));
print(may { div(1, 0) } otherwise { "${err.kind}: ${err.message}" });
print(may { rem(1, 0) } otherwise { "${err.kind}: ${err.message}" });
print(may { shl(1, 64) } otherwise { "${err.kind}: ${err.message}" });
print(may { shl(1, -1) } otherwise { "${err.kind}: ${err.message}" });
print(may { mul(mul(1073741824, 1073741824), mul(1073741824, 8)) } otherwise { "${err.kind}: ${err.message}" });
print(may { big() } otherwise { "${err.kind}: ${err.message}" });
print(may { neg(-1152921504606846975 - 1) } otherwise { "${err.kind}: ${err.message}" });
print(may { tagged_top() } otherwise { "${err.kind}: ${err.message}" });
'''

EXPECTED = '''6765 21
1 0 1 -1
-3 -1 -7 0
tagged 4
0 1 3367 10
55
arithmetic: division by zero
arithmetic: division by zero
arithmetic: shift count out of range
arithmetic: shift count out of range
arithmetic: integer overflow
arithmetic: integer overflow
arithmetic: integer overflow
tagged
arithmetic: shift count out of range
'''


class Fault(Exception):
    pass


def signed(value):
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= WORD else value


def checked(value):
    if not -WORD <= value < WORD:
        raise Fault('integer overflow')
    return value


def truncate(a, b):
    if b == 0:
        raise Fault('division by zero')
    quotient = abs(a) // abs(b)
    return quotient if (a < 0) == (b < 0) else -quotient


def evaluate(node, env):
    kind = node[0]
    if kind == 'int':
        return node[1]
    if kind == 'var':
        return env[node[1]]
    if kind == 'neg':
        return checked(-evaluate(node[1], env))
    if kind == 'not':
        return ~evaluate(node[1], env)
    a, b = evaluate(node[1], env), evaluate(node[2], env)
    op = kind
    if op == '+': return checked(a + b)
    if op == '-': return checked(a - b)
    if op == '*': return checked(a * b)
    if op == '/': return checked(truncate(a, b))
    if op == '%':
        if b == 0:
            raise Fault('division by zero')
        return a - truncate(a, b) * b if not (a == -WORD and b == -1) else 0
    if op == '&': return a & b
    if op == '|': return a | b
    if op == '^': return a ^ b
    if op in ('<<', '>>'):
        if not 0 <= b <= 63:
            raise Fault('shift count out of range')
        return signed(a << b) if op == '<<' else a >> b
    raise AssertionError(op)


def literal(value):
    # Source literals stop at 2^60 - 1, so spell negatives as a subtraction.
    return str(value) if value >= 0 else f'(0 - 1 - {-value - 1})'


def render(node):
    kind = node[0]
    if kind == 'int':
        return literal(node[1])
    if kind == 'var':
        return node[1]
    if kind == 'neg':
        return f'(-{render(node[1])})'
    if kind == 'not':
        return f'(~{render(node[1])})'
    return f'({render(node[1])} {kind} {render(node[2])})'


def generate(rng, depth):
    if depth == 0 or rng.random() < 0.25:
        choice = rng.random()
        if choice < 0.5:
            return ('var', rng.choice('abc'))
        return ('int', rng.choice([0, 1, 2, 3, 7, 31, 32, 61, 62, 63, 64, 255, 1 << 30, (1 << 60) - 1, -1, -8]))
    if rng.random() < 0.15:
        return (rng.choice(['neg', 'not']), generate(rng, depth - 1))
    op = rng.choice(['+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>', '<<', '>>', '&', '^'])
    right = generate(rng, depth - 1)
    if op in ('<<', '>>') and rng.random() < 0.8:
        right = ('int', rng.randrange(64))
    return (op, generate(rng, depth - 1), right)


def oracle_program(seed, count):
    rng = random.Random(seed)
    functions, calls, expected = [], [], []
    for index in range(count):
        body = generate(rng, 4)
        functions.append(f'fun case{index}(a: Int, b: Int, c: Int) -> Int {{ return {render(body)}; }}')
        for _ in range(3):
            args = [rng.choice([0, 1, -1, 5, 63, rng.randrange(-TAGGED, TAGGED), TAGGED - 1, -TAGGED]) for _ in range(3)]
            calls.append(f'print(may {{ case{index}({", ".join(map(literal, args))}) }} otherwise {{ err.message }});')
            try:
                value = evaluate(body, dict(zip('abc', args)))
                expected.append(str(value) if -TAGGED <= value < TAGGED else 'integer overflow')
            except Fault as fault:
                expected.append(str(fault))
    # Portable backends cap frames at 2000 bytes, so batch the tagged callers.
    batches = []
    for start in range(0, len(calls), 10):
        batches.append(f'fun batch{start}() -> Nil {{ ' + ' '.join(calls[start:start + 10]) + ' return; }')
        batches.append(f'batch{start}();')
    return '\n'.join(functions + batches) + '\n', ''.join(line + '\n' for line in expected)


def compile_run(compiler, source, binary, *flags, runner=None):
    result = subprocess.run([str(compiler), *flags, str(source), '-o', str(binary)], capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr.decode()
    result = subprocess.run(([runner] if runner else []) + [str(binary)], capture_output=True, timeout=120)
    assert result.returncode == 0 and not result.stderr, result
    return result.stdout.decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--seed', type=int, default=92)
    parser.add_argument('--cases', type=int, default=120)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    configurations = [([], None), (['--runtime', 'core'], None), (['--debug'], None)]
    skipped = []
    for target, emulator in (('arm64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')):
        runner = shutil.which(emulator)
        if runner:
            configurations.append((['--target', target], runner))
        else:
            skipped.append(target)
    with tempfile.TemporaryDirectory(prefix='mayc-native-words-') as directory:
        work = Path(directory)
        source = work / 'semantics.may'
        source.write_text(SEMANTICS)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'semantics', *flags, runner=runner)
            assert output == EXPECTED, (flags, output)
        print('PASS native-word results, faults, recursion and tagged boundaries', flush=True)
        program, expected = oracle_program(args.seed, args.cases)
        source = work / 'oracle.may'
        source.write_text(program)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'oracle', *flags, runner=runner)
            if output != expected:
                lines = list(zip(output.splitlines(), expected.splitlines()))
                mismatch = next(i for i, (got, want) in enumerate(lines) if got != want)
                raise AssertionError((flags, mismatch, lines[mismatch], program.splitlines()[mismatch // 3]))
        print(f'PASS {args.cases * 3} seeded native-word oracle calls match signed 64-bit semantics', flush=True)
        if skipped:
            print('SKIP ' + ', '.join(skipped) + ' execution: install QEMU user emulators', flush=True)


if __name__ == '__main__':
    main()
