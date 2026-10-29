#!/usr/bin/env python3
"""Fat values (#92): feature fixtures and 64-bit dynamic integers under --values fat.

Each fixture listed in PASSING must reproduce its recorded tagged behavior
(legacy_behavior.json) byte for byte. The others are reported, not failed,
while the fat runtime is incomplete (docs/design/FAT_VALUES.md).
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / 'compiler/mayc/tests'

PASSING = {
    'arith.may', 'arith_overflow.may', 'closures_adv.may', 'cond.may', 'deep_recursion.may',
    'destructure.may', 'div_zero.may', 'edge.may', 'enums.may', 'env_args.may', 'fibers1.may',
    'files.may', 'floats.may', 'funcs.may', 'interp.may', 'intkeys.may', 'json.may', 'lists1.may',
    'lists_hof.may', 'lists_nested.may', 'logical.may', 'loops.may', 'map_ops.may', 'maps1.may',
    'match.may', 'math.may', 'may1.may', 'modules_app.may', 'nested_may.may', 'parse_num.may',
    'pipe.may', 'pointers.may', 'results.may', 'shared_capture.may', 'spread_comp.may',
    'stdlib_collections.may', 'stdlib_math.may', 'stress.may', 'strings1.may', 'strings2.may',
    'strings_esc.may', 'structs.may', 'typehints.may', 'values.may',
}

# Fixtures whose fat output intentionally differs from the tagged record:
# Int no longer overflows between 2^60 and 2^63.
INTENDED = {
    'bitwise.may': b'2 7 5 -1\n1 12 -2 -1152921504606846976\ntrue 2 true\n'
                   b'1152921504606846976 shift count out of range\n3 true\n2305843009213693952\n1\n9\n',
}

SEMANTICS = '''
let big: Int = 1 << 62;
print(big, big + (big - 1), -big - big);
print(may { big + big } otherwise { "${err.kind}: ${err.message}" });
let words: List<Int> = [big, -1, 0];
print(words, words[0] >> 61, (1 << 63) < 0);
let m: Map<Str, Int> = {"wide": big * -2};
print(m["wide"], len(m));
'''

SEMANTICS_EXPECTED = '''4611686018427387904 9223372036854775807 -9223372036854775808
arithmetic: integer overflow
[4611686018427387904, -1, 0] 2 true
-9223372036854775808 1
'''


def compile_run(compiler, source, binary, stdin=b''):
    result = subprocess.run([str(compiler), '--values', 'fat', str(source), '-o', str(binary)],
                            capture_output=True, timeout=180)
    if result.returncode != 0:
        return None, result.stderr.decode(errors='replace').strip().splitlines()[:1]
    run = subprocess.run([str(binary)], input=stdin, capture_output=True, timeout=60, cwd=TESTS)
    return (run.returncode, run.stdout, run.stderr), None


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
        print('PASS 64-bit integers in dynamic values', flush=True)
        passed, pending = [], []
        for name in sorted(expected):
            if not (TESTS / name).exists():
                continue
            record = expected[name]
            want = (record['exit'], base64.b64decode(record['stdout']), base64.b64decode(record['stderr']))
            if name in INTENDED:
                want = (0, INTENDED[name], b'')
            got, error = compile_run(compiler, TESTS / name, work / name.replace('.may', ''))
            if got == want:
                passed.append(name)
            else:
                assert name not in PASSING and name not in INTENDED, (name, error or got)
                pending.append(name)
        missing = (PASSING | set(INTENDED)) - set(passed)
        assert not missing, missing
        print(f'PASS {len(passed)} of {len(passed) + len(pending)} feature fixtures match tagged behavior or its intended 64-bit difference', flush=True)
        if pending:
            print('PENDING ' + ' '.join(pending), flush=True)


if __name__ == '__main__':
    main()
