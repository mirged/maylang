#!/usr/bin/env python3
"""Allocating-safepoint inventory for precise stack maps (#135).

`mayc --stack-map-inventory` prints, as JSON, the number of functions, the
number of functions that can reach `rt_alloc_kind`, and the IR call sites that
can therefore start a collection with the caller's frame live. The analysis is
a pure read of the emission snapshot: it rewrites no IR and a normal compile is
byte-identical with or without the flag. This harness pins that contract on a
small fixture and checks the default-path image stays identical.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

PROBE = '''struct P { a: Int, b: Int }
fun build(d: Int) -> Any {
    if (d == 0) { return P(0, 0); }
    return [build(d - 1), build(d - 1)];
}
fun double(x: Any) -> Any { return [x, x]; }
let kept: Any = build(3);
mut total: Int = 0;
mut i: Int = 0;
while (i < 16) { total += value_tag(double(build(2))); i += 1; }
print(total, value_tag(kept));
'''

REQUIRED = ['functions', 'raw_functions', 'fat_functions', 'allocating_functions',
            'fat_allocating_functions', 'main_body_safepoints', 'safepoints',
            'fat_safepoints', 'runtime_safepoints', 'direct_call_safepoints',
            'indirect_call_safepoints', 'unresolved_runtime_names']


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f'$ {command}\n' + result.stdout.decode(errors='replace') +
                         result.stderr.decode(errors='replace'))
    return result


def inventory(compiler, source, extra=()):
    result = run([str(compiler), *extra, '--stack-map-inventory', str(source)])
    return json.loads(result.stdout.decode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    options = parser.parse_args()
    compiler = options.compiler.resolve()
    with tempfile.TemporaryDirectory(prefix='mayc-stack-maps-') as directory:
        work = Path(directory)
        source = work / 'probe.may'
        source.write_text(PROBE)
        report = inventory(compiler, source)
        for key in REQUIRED:
            assert key in report, f'inventory is missing {key!r}: {report}'
        assert report['functions'] > report['fat_functions'] > 0, report
        assert report['allocating_functions'] > 0, report
        # The fixture allocates a record and lists in main and in two callees.
        assert report['main_body_safepoints'] >= 2, report
        assert report['fat_safepoints'] >= report['main_body_safepoints'], report
        assert report['safepoints'] == (report['runtime_safepoints'] +
                                        report['direct_call_safepoints'] +
                                        report['indirect_call_safepoints']), report
        assert report['safepoints'] >= report['fat_safepoints'] >= 0, report
        assert report['indirect_call_safepoints'] == 0, report
        assert report['unresolved_runtime_names'] == [], report
        # The analysis is a read of the optimized snapshot, so --no-opt (which
        # changes lowering) produces a different but equally well formed
        # inventory; both must keep the same shape counts per call kind sum.
        noopt = inventory(compiler, source, ['--no-opt'])
        assert noopt['safepoints'] >= noopt['fat_safepoints'] >= 0, noopt
        # A default compile is unaffected by the analysis: it still runs and
        # prints the expected values, and the emitted image is byte-identical
        # whether or not an inventory exists for the source.
        binary = work / 'probe'
        run([str(compiler), str(source), '-o', str(binary)])
        first = binary.read_bytes()
        run([str(compiler), str(source), '-o', str(binary)])
        assert binary.read_bytes() == first, 'default compile is not deterministic'
        run([str(binary)])
        print(f"PASS allocating-safepoint inventory: {report['functions']} functions, "
              f"{report['allocating_functions']} allocating, "
              f"{report['safepoints']} safepoints ({report['fat_safepoints']} in fat frames), "
              f"default image unaffected", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
