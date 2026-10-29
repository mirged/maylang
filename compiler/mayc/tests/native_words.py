#!/usr/bin/env python3
"""Check native-word lowering of strictly typed Int functions (#92).

Qualifying functions compute with untagged 64-bit words. Calls from tagged
code untag arguments and retag the result, so values beyond the tagged range
fault only when they leave native code. A seeded oracle compares random
expressions with Python's signed 64-bit semantics. Further programs check
that Ptr parameters and load/store keep all 64 bits, that Bool parameters,
results and locals cross the tagged boundary, that range loops count natively,
that global reads and writes convert to and from tagged values, and that
bitwise expressions in tagged code are outlined into native-word functions. All run on the full and core
runtimes, with and without --debug, and on ARM64/RISC-V core targets when
QEMU user emulators are installed, and on clang-llvm when clang is.
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
let t: Int = 6;
print(t & 3, t | 1, t ^ 5, ~t, t << 2, -t >> 1, t << 57, -1 << 60);
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
arithmetic: integer overflow
2 7 3 -7 24 -3 864691128455135232 -1152921504606846976
'''

# Native loads keep bit 63; tagged load64 faults on such a word.
MEMORY = '''
fun low_at(p: Ptr, offset: Int) -> Int { return load64(p + offset) & 4294967295; }
fun word_at(p: Ptr) -> Int { return load64(p); }
fun top_byte(p: Ptr) -> Int { return (load64(p) >> 56) & 255; }
fun top_set(p: Ptr) -> Int { if (load64(p) < 0) { return 1; } return 0; }
fun put(p: Ptr, v: Int) -> Int { store64(p, v); store8(p + 9, 7); return load8(p + 9); }
fun fill(p: Ptr) -> Int { store64(p, 1 << 63); return 0; }
fun next(p: Ptr) -> Ptr { return p + 8; }
fun sum16(p: Ptr, n: Int) -> Int {
    mut i: Int = 0;
    mut total: Int = 0;
    while (i < n) { total = total + load16(p + i * 2); i = i + 1; }
    return total;
}
let buf: Ptr = addr("abcdefghijklmnopqrstuvwxyz012345");
print(low_at(buf, 1), load32(buf + 1));
print(sum16(buf, 3), load16(buf) + load16(buf + 2) + load16(buf + 4));
print(next(buf) == buf + 8);
let w: Str = repeat("x", 32);
let q: Ptr = addr(w);
print(put(q, 5), load64(q), top_set(q));
fill(q);
print(top_set(q), top_byte(q), load8(q + 7));
print(may { load64(q) } otherwise { err.message });
print(may { word_at(q) } otherwise { "${err.kind}: ${err.message}" });
'''

MEMORY_EXPECTED = '''1701077858 1701077858
77097 77097
true
7 5 0
1 128 128
integer overflow
arithmetic: integer overflow
'''

# `x << 62` faults in tagged code, so wide() only passes if the Bool callers
# it depends on stay native.
BOOLS = '''
fun bit_set(x: Int, n: Int) -> Bool { return ((x >> n) & 1) != 0; }
fun top(x: Int) -> Bool { return bit_set(x, 63); }
fun pick(flag: Bool, a: Int, b: Int) -> Int { if (flag) { return a; } return b; }
fun both(a: Bool, b: Bool) -> Bool { return a and b; }
fun either(a: Bool, b: Bool) -> Bool { return a or not b; }
fun always() -> Bool { return true; }
fun never() -> Bool { let f: Bool = false; return f; }
fun flip(x: Bool) -> Bool { mut v: Bool = x; v = not v; return v; }
fun wide(x: Int) -> Int { if (top(x << 62)) { return pick(true, 1, 2); } return pick(false, 1, 2); }
print(bit_set(5, 0), bit_set(5, 1), top(-1), top(1));
print(pick(true, 7, 8), pick(false, 7, 8), pick(bit_set(2, 1), 3, 4));
print(both(true, true), both(true, false), either(false, true), either(false, false));
print(always(), never(), flip(true), flip(false), wide(1), wide(2));
let g: (Bool, Int, Int) -> Int = pick;
print(g(true, 5, 6), if (top(-5)) { "neg" } else { "pos" });
'''

BOOLS_EXPECTED = '''true false true false
7 8 3
true false false true
true false false true 2 1
5 neg
'''

# edge() counts up to 2^63 - 1, which only native code can represent.
LOOPS = '''
fun sum(n: Int) -> Int { mut t: Int = 0; for i: Int in 0..n { if (i == 5) { continue; } t = t + i; } return t; }
fun upto(a: Int, b: Int) -> Int { mut t: Int = 0; for i in a..=b { t = t + i; } return t; }
fun first_over(n: Int, limit: Int) -> Int { for i in 0..n { if (i * i > limit) { return i; } } return -1; }
fun nested(n: Int) -> Int {
    mut t: Int = 0;
    for i in 0..n { for j in i..n { if (j == 7) { break; } t = t + 1; } }
    return t;
}
fun edge() -> Int {
    let top: Int = (1 << 62) - 1 + (1 << 62);
    mut t: Int = 0;
    for i in top - 2..=top { t = t + 1; }
    return t;
}
fun shadow(n: Int) -> Int { mut t: Int = 0; for i in 0..n { let i2: Int = i * 2; t = t + i2; } return t; }
fun bump(n: Int) -> Int { mut k: Int = n; mut t: Int = 0; for i in 0..k { k = k + 1; t = t + 1; } return t; }
fun deep() -> Int { mut t: Int = 0; for i in 0..3 { t = t + upto(1, i); } return t; }
fun tagged_for(n: Int) -> Int { mut t: Int = 0; for i in [1, 2, 3] { t = t + i * n; } return t; }
print(sum(10), upto(1, 10), upto(5, 4), first_over(100, 50), first_over(3, 50));
print(nested(10), edge(), shadow(4), bump(3), deep(), tagged_for(2));
print(sum(0), upto(-3, -1), may { edge() + 0 } otherwise { err.message });
'''

LOOPS_EXPECTED = '''40 55 0 8 -1
31 3 12 3 4 12
0 -6 3
'''

# Globals stay tagged: native reads untag, writes retag and fault (leaving the
# global unchanged) outside the 61-bit range. wide() shifts by 62, so it
# only passes natively.
GLOBALS = '''
let LIMIT: Int = 1000;
let MASK: Int = 255;
mut counter: Int = 0;
mut seen: Bool = false;
mut total: Int = -5;
fun tick(n: Int) -> Int { counter = counter + n; return counter; }
fun mark() -> Bool { let was: Bool = seen; seen = true; return was; }
fun clamp(x: Int) -> Int { if (x > LIMIT) { return LIMIT; } return x & MASK; }
fun run(n: Int) -> Int { for i in 0..n { total = total + i; } return total; }
fun spill() -> Int { counter = 1 << 61; return 0; }
fun wide() -> Int { let w: Int = counter << 62; return (w >> 62) + LIMIT; }
fun local_shadow(counter: Int) -> Int { return counter * 2; }
print(tick(3), tick(4), counter);
print(mark(), mark(), seen);
seen = false;
print(mark(), clamp(5000), clamp(300));
print(run(10), total);
counter = 1;
print(wide(), local_shadow(21), counter);
print(may { spill() } otherwise { "${err.kind}: ${err.message}" }, counter);
'''

GLOBALS_EXPECTED = '''3 7 7
false true true
false 1000 44
40 40
1001 42 1
arithmetic: integer overflow 1
'''

# Tagged load64 accepts exactly the 61-bit range and faults outside it.
TAGGED_LOAD = '''
let w: Str = repeat("x", 32);
let q: Ptr = addr(w);
fun put(p: Ptr, v: Int) -> Int { store64(p, v); return 0; }
fun put_max(p: Ptr) -> Int { store64(p, (1 << 60) - 1); return 0; }
fun put_min(p: Ptr) -> Int { store64(p, 0 - (1 << 60)); return 0; }
fun put_over(p: Ptr) -> Int { store64(p, 1 << 60); return 0; }
fun put_under(p: Ptr) -> Int { store64(p, -1 - (1 << 60)); return 0; }
fun put_top(p: Ptr) -> Int { store64(p, 1 << 63); return 0; }
put(q, 1 << 59);
print(load64(q));
put(q, -1);
print(load64(q));
put_max(q);
print(load64(q));
put_min(q);
print(load64(q));
put_over(q);
print(may { load64(q) } otherwise { "${err.kind}: ${err.message}" });
put_under(q);
print(may { load64(q) } otherwise { "${err.kind}: ${err.message}" });
put_top(q);
print(may { load64(q) } otherwise { "${err.kind}: ${err.message}" });
print(load64(addr(w) - 8));
'''

TAGGED_LOAD_EXPECTED = '''576460752303423488
-1
1152921504606846975
-1152921504606846976
arithmetic: integer overflow
arithmetic: integer overflow
arithmetic: integer overflow
32
'''

# syscall needs the full runtime. clock_ns() shifts by 62, so it only passes
# natively.
SYSCALLS = '''
fun write_bytes(p: Ptr, n: Int) -> Int { return syscall(1, 1, p, n); }
fun pid_ok() -> Bool { return syscall(39) > 0; }
fun bad_fd() -> Int { return syscall(3, -1); }
fun clock_ns(buf: Ptr) -> Int {
    if (syscall(228, 1, buf) != 0) { return -1; }
    return (load64(buf) << 62) >> 62;
}
let msg: Str = "native write\n";
print(write_bytes(addr(msg), 13));
print(pid_ok(), bad_fd());
let buf: Str = repeat("x", 16);
print(clock_ns(addr(buf)) >= -2);
'''

SYSCALLS_EXPECTED = '''native write
13
true -9
true
'''

# Tagged code outlines bitwise expressions into native-word functions, so
# intermediate values are 64-bit and only stored results must fit 61 bits.
OUTLINED = '''
print((1 << 63) & (1 << 63) != 0);
let x: Int = 5;
let top: Bool = ((x << 62) >> 62) == 1;
print(top, (x << 61) >> 61, (-1 >> 63));
fun bits(n: Int) -> Int { return n; }
fun pick(a: Any) -> Int { return int(a) & 255; }
mut acc: Int = 0;
for i in 0..4 { acc = acc | (1 << (60 + i)) >> 60; }
print(acc, pick(4097), ~0, 6 & 3 | 8 ^ 1);
print(may { 1 << 62 } otherwise { "${err.kind}: ${err.message}" });
print(may { x << 64 } otherwise { "${err.kind}: ${err.message}" });
let list: List<Int> = [1, 2, 3];
print(list[0] << 2, len(list) & 1);
fun page(entry: Int) -> Bool { return (entry & (1 << 63)) != 0; }
print(page(-1), page(1));
let f: (Int) -> Int = fun(v: Int) -> Int { return (v << 62) >> 62; };
print(f(3));
mut seen: Int = 1;
fun bump() -> Int { seen = seen + 10; return 0; }
print((bump() | 0) + seen, seen + (bump() | 0), (bump() | 0) + seen);
'''

OUTLINED_EXPECTED = '''true
true -3 -1
-1 1 -1 11
arithmetic: integer overflow
arithmetic: shift count out of range
4 1
true false
-1
11 11 31
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
    if shutil.which('clang'):
        configurations.append((['--target', 'clang-llvm'], None))
    else:
        skipped.append('clang-llvm')
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
        source = work / 'memory.may'
        source.write_text(MEMORY)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'memory', *flags, runner=runner)
            assert output == MEMORY_EXPECTED, (flags, output)
        print('PASS native-word Ptr parameters and full-width loads and stores', flush=True)
        source = work / 'bools.may'
        source.write_text(BOOLS)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'bools', *flags, runner=runner)
            assert output == BOOLS_EXPECTED, (flags, output)
        print('PASS native-word Bool parameters, results and locals', flush=True)
        source = work / 'loops.may'
        source.write_text(LOOPS)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'loops', *flags, runner=runner)
            assert output == LOOPS_EXPECTED, (flags, output)
        print('PASS native-word range loops', flush=True)
        source = work / 'globals.may'
        source.write_text(GLOBALS)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'globals', *flags, runner=runner)
            assert output == GLOBALS_EXPECTED, (flags, output)
        print('PASS native-word reads and writes of tagged globals', flush=True)
        source = work / 'tagged_load.may'
        source.write_text(TAGGED_LOAD)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'tagged_load', *flags, runner=runner)
            assert output == TAGGED_LOAD_EXPECTED, (flags, output)
        print('PASS tagged load64 faults outside the 61-bit range', flush=True)
        source = work / 'outlined.may'
        source.write_text(OUTLINED)
        for flags, runner in configurations:
            output = compile_run(compiler, source, work / 'outlined', *flags, runner=runner)
            assert output == OUTLINED_EXPECTED, (flags, output)
        print('PASS tagged bitwise expressions compute with native words', flush=True)
        source = work / 'syscalls.may'
        source.write_text(SYSCALLS)
        for flags, runner in configurations:
            if runner or '--runtime' in flags:
                continue
            output = compile_run(compiler, source, work / 'syscalls', *flags, runner=runner)
            assert output == SYSCALLS_EXPECTED, (flags, output)
        print('PASS native-word syscall on the full runtime', flush=True)
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
            print('SKIP ' + ', '.join(skipped) + ': install clang or QEMU user emulators', flush=True)


if __name__ == '__main__':
    main()
