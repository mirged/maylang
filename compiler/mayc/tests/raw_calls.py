#!/usr/bin/env python3
"""Measure direct-call overhead with checked RAW workloads; no timing threshold."""
import argparse
import datetime
import json
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

from backends import compiler_binary, compile_source
from raw_performance import ROOT, capture, digest, summarize

HERE = Path(__file__).resolve().parent
ARITIES = (1, 6, 7, 8)
ITERATIONS = 1_000_000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--baseline-compiler', type=Path, action='append', default=[])
    parser.add_argument('--baseline-revision', action='append', default=[])
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
    assert args.runs > 0 and args.warmup >= 0
    assert len(args.baseline_revision) <= len(args.baseline_compiler)
    compilers = {'may': compiler_binary(args.compiler)}
    revisions = {'may': capture(['git', 'rev-parse', 'HEAD'])}
    for index, compiler in enumerate(args.baseline_compiler):
        name = f'before_{index + 1}'
        compilers[name] = compiler_binary(compiler)
        revisions[name] = args.baseline_revision[index] if index < len(args.baseline_revision) else 'unspecified'
    samples = {name: {str(arity): [] for arity in ARITIES} for name in compilers}
    expected = [ITERATIONS * (ITERATIONS - 1) // 2 + ITERATIONS * arity * (arity - 1) // 2
                for arity in ARITIES]
    with tempfile.TemporaryDirectory(prefix='mayc-raw-calls-') as directory:
        binaries = {}
        for name, compiler in compilers.items():
            binary = Path(directory) / name
            compile_source(compiler, HERE / 'backend/raw_calls.may', binary, '--raw')
            binaries[name] = binary
        names = list(binaries)
        for iteration in range(args.warmup + args.runs):
            # Rotate order to avoid giving one compiler a consistent host bias.
            offset = iteration % len(names)
            for name in names[offset:] + names[:offset]:
                command = (['taskset', '-c', str(args.cpu)] if args.cpu is not None else []) + [str(binaries[name])]
                output = subprocess.check_output(command, timeout=30)
                assert len(output) == 16 * len(ARITIES), (name, output)
                pairs = list(struct.iter_unpack('<QQ', output))
                assert [checksum for checksum, _ in pairs] == expected, (name, pairs)
                if iteration >= args.warmup:
                    for arity, (_, elapsed) in zip(ARITIES, pairs):
                        samples[name][str(arity)].append(elapsed)
        results = {name: {arity: summarize(values) for arity, values in rows.items()}
                   for name, rows in samples.items()}
        for name, rows in results.items():
            print(name + ': ' + ', '.join(f"{arity} args: {row['median'] / ITERATIONS:.2f} ns/iteration"
                                         for arity, row in rows.items()) + '; all checksums match')
        report = {
            'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'revision': capture(['git', 'rev-parse', 'HEAD']), 'status': capture(['git', 'status', '--short']),
            'cpu': args.cpu, 'runs': args.runs, 'warmup': args.warmup, 'iterations': ITERATIONS,
            'uname': capture(['uname', '-a']), 'lscpu': capture(['lscpu']),
            'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in [
                HERE / 'backend/raw_calls.may', HERE / 'raw_calls.py',
                ROOT / 'compiler/mayc/src/backend/x86_64.may', ROOT / 'compiler/mayc/src/regalloc.may',
                ROOT / 'compiler/mayc/src/ir.may', ROOT / 'compiler/mayc/src/emitter.may']},
            'compilers': {name: {'revision': revisions[name], 'sha256': digest(compiler),
                                 'binary_sha256': digest(binaries[name])} for name, compiler in compilers.items()},
            'checksums': dict(zip(map(str, ARITIES), expected)), 'samples_ns': samples, 'results_ns': results,
            'notes': 'Times include loop, arithmetic and parameter access as well as calls; these are not isolated instruction latencies. '
                     'Each sample contains one million calls. Host is not isolated. No timing threshold is enforced.'}
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
