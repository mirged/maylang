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
