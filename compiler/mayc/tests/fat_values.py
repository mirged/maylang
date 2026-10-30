#!/usr/bin/env python3
"""Fat values (#92): 64-bit dynamic integers, the --values tagged opt-out and self-hosting.

Fat values are the default on x86_64-linux with the full runtime, so
verify.py checks the feature fixtures against legacy_behavior.json with
them. This harness checks that the --values tagged opt-out still
reproduces every record, except where the tagged 61-bit Int differs
(TAGGED), and that compilers built either way emit identical programs.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / 'compiler/mayc/tests'

# Tagged output where Int still overflows between 2^60 and 2^63.
TAGGED = {
    'bitwise.may': b'2 7 5 -1\n1 12 -2 -1152921504606846976\ntrue 2 true\n'
                   b'integer overflow shift count out of range\n3 true\narithmetic\n1\n9\n',
}

SEMANTICS = '''
let big: Int = 1 << 62;
print(big, big + (big - 1), -big - big);
print(may { big + big } otherwise { "${err.kind}: ${err.message}" });
let words: List<Int> = [big, -1, 0];
print(words, words[0] >> 61, (1 << 63) < 0);
let m: Map<Str, Int> = {"wide": big * -2};
print(m["wide"], len(m), 9223372036854775807, -9223372036854775808);
'''

SEMANTICS_EXPECTED = '''4611686018427387904 9223372036854775807 -9223372036854775808
arithmetic: integer overflow
[4611686018427387904, -1, 0] 2 true
-9223372036854775808 1 9223372036854775807 -9223372036854775808
'''

# Inline Int division and closure calls (#92) against the runtime's rules:
# truncation, the dividend's sign, faults for 0 and the -2^63 / -1
# overflow, nil padding and the non-callable fault.
INLINE = '''let xs: List<Any> = [7, -7, 0, 9223372036854775807, -9223372036854775807 - 1];
let ys: List<Any> = [2, -2, 1, -1, 0, 3];
for x: Any in xs { for y: Any in ys {
    let q: Str = may { str(x / y) } otherwise { str(err.kind) };
    let r: Str = may { str(x % y) } otherwise { str(err.kind) };
    print("${x} ${y} ${q} ${r}");
} }
let f: Any = 7.5; let g: Any = 2;
print(f / g, may { f % g } otherwise { str(err.kind) });
let sa: Any = "a"; print(may { sa / 2 } otherwise { str(err.kind) });
fun pad(a: Any, b: Any, c: Any) -> Any { return [a, b, c]; }
let h: Any = pad;
print(h(1), h(1, 2, 3));
print(may { let n: Any = 3; n(1) } otherwise { str(err.kind) + ": " + str(err.message) });
'''

INLINE_EXPECTED = '''7 2 3 1
7 -2 -3 1
7 1 7 0
7 -1 -7 0
7 0 arithmetic arithmetic
7 3 2 1
-7 2 -3 -1
-7 -2 3 -1
-7 1 -7 0
-7 -1 7 0
-7 0 arithmetic arithmetic
-7 3 -2 -1
0 2 0 0
0 -2 0 0
0 1 0 0
0 -1 0 0
0 0 arithmetic arithmetic
0 3 0 0
9223372036854775807 2 4611686018427387903 1
9223372036854775807 -2 -4611686018427387903 1
9223372036854775807 1 9223372036854775807 0
9223372036854775807 -1 -9223372036854775807 0
9223372036854775807 0 arithmetic arithmetic
9223372036854775807 3 3074457345618258602 1
-9223372036854775808 2 -4611686018427387904 0
-9223372036854775808 -2 4611686018427387904 0
-9223372036854775808 1 -9223372036854775808 0
-9223372036854775808 -1 arithmetic 0
-9223372036854775808 0 arithmetic arithmetic
-9223372036854775808 3 -3074457345618258602 -2
3.75 type
type
[1, nil, nil] [1, 2, 3]
type: value is not callable
'''

# Inline Float arithmetic and comparisons (#92) against the runtime's rules:
# signed zeros, NaN (unordered, unequal), infinities, the zero divisor
# fault and mixed Int operands.
FLOATS = '''let big: Float = 1.0e308;
let xs: List<Any> = [1.5, -2.25, 0.0, -0.0, sqrt(-1.0), big * 10.0, -(big * 10.0), 3, 1.0e-300];
for x: Any in xs { for y: Any in xs {
    let q: Str = may { str(x / y) } otherwise { str(err.kind) };
    let lt: Str = may { "${x < y} ${x <= y} ${x > y} ${x >= y}" } otherwise { str(err.kind) };
    print("${x} ${y} ${x + y} ${x - y} ${x * y} ${q} ${x == y} ${x != y} ${lt}");
} }
mut acc: Float = 0.0;
for i: Int in 0..1000 { acc = acc * 0.5 + to_float(i) / 3.0; }
print(acc, acc < 700.0, acc - 666.0 > 0.0);
'''

# Recorded from the runtime path (rt_binary) before Float ran inline.
FLOATS_EXPECTED = '''1.5 1.5 3.0 0.0 2.25 1.0 true false false true false true
1.5 -2.25 -0.75 3.75 -3.375 -0.6666666666666666 false true false false true true
1.5 0.0 1.5 1.5 0.0 arithmetic false true false false true true
1.5 -0.0 1.5 1.5 -0.0 arithmetic false true false false true true
1.5 nan nan nan nan nan false true false false false false
1.5 inf inf -inf inf 0.0 false true true true false false
1.5 -inf -inf inf -inf -0.0 false true false false true true
1.5 3 4.5 -1.5 4.5 0.5 false true type
1.5 1e-300 1.5 1.5 1.5e-300 1.5e300 false true false false true true
-2.25 1.5 -0.75 -3.75 -3.375 -1.5 false true true true false false
-2.25 -2.25 -4.5 0.0 5.0625 1.0 true false false true false true
-2.25 0.0 -2.25 -2.25 -0.0 arithmetic false true true true false false
-2.25 -0.0 -2.25 -2.25 0.0 arithmetic false true true true false false
-2.25 nan nan nan nan nan false true false false false false
-2.25 inf inf -inf -inf -0.0 false true true true false false
-2.25 -inf -inf inf inf 0.0 false true false false true true
-2.25 3 0.75 -5.25 -6.75 -0.75 false true type
-2.25 1e-300 -2.25 -2.25 -2.25e-300 -2.25e300 false true true true false false
0.0 1.5 1.5 -1.5 0.0 0.0 false true true true false false
0.0 -2.25 -2.25 2.25 -0.0 -0.0 false true false false true true
0.0 0.0 0.0 0.0 0.0 arithmetic true false false true false true
0.0 -0.0 0.0 0.0 -0.0 arithmetic true false false true false true
0.0 nan nan nan nan nan false true false false false false
0.0 inf inf -inf nan 0.0 false true true true false false
0.0 -inf -inf inf nan -0.0 false true false false true true
0.0 3 3.0 -3.0 0.0 0.0 false true type
0.0 1e-300 1e-300 -1e-300 0.0 0.0 false true true true false false
-0.0 1.5 1.5 -1.5 -0.0 -0.0 false true true true false false
-0.0 -2.25 -2.25 2.25 0.0 0.0 false true false false true true
-0.0 0.0 0.0 -0.0 -0.0 arithmetic true false false true false true
-0.0 -0.0 -0.0 0.0 0.0 arithmetic true false false true false true
-0.0 nan nan nan nan nan false true false false false false
-0.0 inf inf -inf nan -0.0 false true true true false false
-0.0 -inf -inf inf nan 0.0 false true false false true true
-0.0 3 3.0 -3.0 -0.0 -0.0 false true type
-0.0 1e-300 1e-300 -1e-300 -0.0 -0.0 false true true true false false
nan 1.5 nan nan nan nan false true false false false false
nan -2.25 nan nan nan nan false true false false false false
nan 0.0 nan nan nan arithmetic false true false false false false
nan -0.0 nan nan nan arithmetic false true false false false false
nan nan nan nan nan nan false true false false false false
nan inf nan nan nan nan false true false false false false
nan -inf nan nan nan nan false true false false false false
nan 3 nan nan nan nan false true type
nan 1e-300 nan nan nan nan false true false false false false
inf 1.5 inf inf inf inf false true false false true true
inf -2.25 inf inf -inf -inf false true false false true true
inf 0.0 inf inf nan arithmetic false true false false true true
inf -0.0 inf inf nan arithmetic false true false false true true
inf nan nan nan nan nan false true false false false false
inf inf inf nan inf nan true false false true false true
inf -inf nan inf -inf nan false true false false true true
inf 3 inf inf inf inf false true type
inf 1e-300 inf inf inf inf false true false false true true
-inf 1.5 -inf -inf -inf -inf false true true true false false
-inf -2.25 -inf -inf inf inf false true true true false false
-inf 0.0 -inf -inf nan arithmetic false true true true false false
-inf -0.0 -inf -inf nan arithmetic false true true true false false
-inf nan nan nan nan nan false true false false false false
-inf inf nan -inf -inf nan false true true true false false
-inf -inf -inf nan inf nan true false false true false true
-inf 3 -inf -inf -inf -inf false true type
-inf 1e-300 -inf -inf -inf -inf false true true true false false
3 1.5 4.5 1.5 4.5 2.0 false true type
3 -2.25 0.75 5.25 -6.75 -1.3333333333333333 false true type
3 0.0 3.0 3.0 0.0 arithmetic false true type
3 -0.0 3.0 3.0 -0.0 arithmetic false true type
3 nan nan nan nan nan false true type
3 inf inf -inf inf 0.0 false true type
3 -inf -inf inf -inf -0.0 false true type
3 3 6 0 9 1 true false false true false true
3 1e-300 3.0 3.0 3e-300 3e300 false true type
1e-300 1.5 1.5 -1.5 1.5e-300 6.666666666666667e-301 false true true true false false
1e-300 -2.25 -2.25 2.25 -2.25e-300 -4.4444444444444446e-301 false true false false true true
1e-300 0.0 1e-300 1e-300 0.0 arithmetic false true false false true true
1e-300 -0.0 1e-300 1e-300 -0.0 arithmetic false true false false true true
1e-300 nan nan nan nan nan false true false false false false
1e-300 inf inf -inf inf 0.0 false true true true false false
1e-300 -inf -inf inf -inf -0.0 false true false false true true
1e-300 3 3.0 -3.0 3e-300 3.3333333333333334e-301 false true type
1e-300 1e-300 2e-300 0.0 0.0 1.0 true false false true false true
665.3333333333334 true false
'''


def compile_run(compiler, source, binary, *flags):
    result = subprocess.run([str(compiler), *flags, str(source), '-o', str(binary)],
                            capture_output=True, timeout=180)
    if result.returncode != 0:
        return None, result.stderr.decode(errors='replace').strip().splitlines()[:1]
    run = subprocess.run([str(binary)], capture_output=True, timeout=60, cwd=TESTS)
    return (run.returncode, run.stdout, run.stderr), None


def self_host(compiler, work):
    # A compiler built on tagged values must emit exactly what the fat
    # compiler emits, for the compiler itself.
    host = work / 'host'
    host.mkdir()
    for name in ['runtime.may', 'native.may', 'runtime']:
        (host / name).symlink_to(ROOT / 'compiler/mayc' / name)
    (host / 'prelude.may').symlink_to(ROOT / 'stdlib/prelude.may')
    tagged = host / 'mayc'
    main = ROOT / 'compiler/mayc/main.may'
    for argv in ([compiler, '--values', 'tagged', main, '-o', tagged],
                 [tagged, main, '-o', work / 'by-tagged'],
                 [compiler, main, '-o', work / 'by-fat']):
        result = subprocess.run([str(a) for a in argv], capture_output=True, timeout=600)
        assert result.returncode == 0, (argv, result.stderr.decode(errors='replace'))
    assert (work / 'by-tagged').read_bytes() == (work / 'by-fat').read_bytes()
    print('PASS a compiler built on tagged values emits the fat compiler\'s output', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    expected = json.loads((TESTS / 'legacy_behavior.json').read_text())
    with tempfile.TemporaryDirectory(prefix='mayc-fat-values-') as directory:
        work = Path(directory)
        source = work / 'semantics.may'
        source.write_text(SEMANTICS)
        got, error = compile_run(compiler, source, work / 'semantics')
        assert got == (0, SEMANTICS_EXPECTED.encode(), b''), (got, error)
        print('PASS 64-bit integers in dynamic values and literals', flush=True)
        source = work / 'inline.may'
        source.write_text(INLINE)
        got, error = compile_run(compiler, source, work / 'inline')
        assert got == (0, INLINE_EXPECTED.encode(), b''), (got, error)
        print('PASS inline Int division and closure calls', flush=True)
        source = work / 'floats.may'
        source.write_text(FLOATS)
        got, error = compile_run(compiler, source, work / 'floats')
        assert got == (0, FLOATS_EXPECTED.encode(), b''), (got, error)
        print('PASS inline Float arithmetic matches the runtime', flush=True)
        count = 0
        for name in sorted(expected):
            if not (TESTS / name).exists():
                continue
            record = expected[name]
            want = (record['exit'], base64.b64decode(record['stdout']), base64.b64decode(record['stderr']))
            if name in TAGGED:
                want = (0, TAGGED[name], b'')
            got, error = compile_run(compiler, TESTS / name, work / name.replace('.may', ''), '--values', 'tagged')
            assert got == want, (name, error or got)
            count += 1
        print(f'PASS {count} feature fixtures with --values tagged', flush=True)
        self_host(compiler, work)


if __name__ == '__main__':
    main()
