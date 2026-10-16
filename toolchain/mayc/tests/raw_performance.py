#!/usr/bin/env python3
"""Reproduce issue #76 with checksums, optional pinned timings and perf counters.

No performance threshold is enforced. Use --baseline-compiler with a compiler
copied together with its runtime sidecars before rebuilding the changed source.
"""
import argparse
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tempfile
import time

from backends import compiler_binary, compile_source

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CHECKSUMS = {'PRNG': 1263606197, 'Collatz': 2864311, 'Byte histogram': 33685504,
             'Cellular automaton': 44849, 'Pointer chase': 578415528,
             'Random walk': 1997581997722}


def parse_output(output):
    rows = {}
    for line in output.splitlines():
        match = re.fullmatch(r'(.+?)\s+(-?\d+)\s+(\d+)', line)
        if match and match[1].strip() in CHECKSUMS:
            name = match[1].strip()
            assert name not in rows, (name, output)
            rows[name] = {'checksum': int(match[2]), 'ns': int(match[3])}
    assert {name: row['checksum'] for name, row in rows.items()} == CHECKSUMS, output
    return rows


def capture(command):
    return subprocess.check_output([str(part) for part in command], cwd=ROOT, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(samples):
    return {'median': statistics.median(samples), 'min': min(samples), 'max': max(samples),
            'mean': statistics.mean(samples), 'stdev': statistics.stdev(samples) if len(samples) > 1 else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--baseline-compiler', type=Path)
    parser.add_argument('--baseline-revision', default='unspecified')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--cpu', type=int, help='pin every measured binary to this logical CPU')
    parser.add_argument('--perf', action='store_true', help='also capture five user-mode hardware-counter runs')
    parser.add_argument('--output', type=Path, help='JSON report; adjacent directory holds disassembly and perf logs')
    args = parser.parse_args()
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Linux x86-64 required'
    assert args.runs > 0 and args.warmup >= 0
    compiler = compiler_binary(args.compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-raw-performance-') as directory:
        work = Path(directory)
        artifacts = args.output.resolve().with_suffix('') if args.output else work / 'artifacts'
        artifacts.mkdir(parents=True, exist_ok=True)
        binaries = {'may': work / 'may'}
        compile_source(compiler, HERE / 'backend/raw_performance.may', binaries['may'], '--raw')
        compilers = {'may': {'sha256': digest(compiler), 'version': capture([compiler, '--version'])}}
        if args.baseline_compiler:
            baseline = compiler_binary(args.baseline_compiler)
            binaries['before'] = work / 'before'
            compile_source(baseline, HERE / 'backend/raw_performance.may', binaries['before'], '--raw')
            compilers['before'] = {'sha256': digest(baseline), 'version': capture([baseline, '--version']),
                                   'revision': args.baseline_revision}
        for name, flags in [('gcc', []), ('gcc_scalar', ['-fno-tree-vectorize'])]:
            binaries[name] = work / name
            subprocess.run(['gcc', '-O3', '-march=native', '-std=c11', *flags,
                            str(HERE / 'backend/raw_performance.c'), '-o', str(binaries[name])], check=True)
        commands = {name: (['taskset', '-c', str(args.cpu)] if args.cpu is not None else []) + [str(binary)]
                    for name, binary in binaries.items()}
        results = {name: {'samples': [], 'perf': []} for name in binaries}
        for name, binary in binaries.items():
            assembly = capture(['objdump', '-d', '-Mintel', '--no-show-raw-insn', binary]) + '\n'
            (artifacts / f'{name}.asm').write_text(assembly)
            counts = Counter(re.findall(r'^\s*[0-9a-f]+:\s+(\w+)', assembly, re.M))
            results[name].update({'binary_sha256': digest(binary), 'binary_bytes': binary.stat().st_size,
                                  'static_instructions': sum(counts.values()), 'opcodes': dict(counts)})
            for _ in range(args.warmup):
                parse_output(capture(commands[name]))
        names = list(binaries)
        # Rotate execution order to distribute drift between the candidates.
        for iteration in range(args.runs):
            order = names[iteration % len(names):] + names[:iteration % len(names)]
            for name in order:
                start = time.perf_counter_ns()
                output = capture(commands[name])
                elapsed = time.perf_counter_ns() - start
                rows = parse_output(output)
                results[name]['samples'].append({'elapsed_ns': elapsed, 'workloads': rows})
        if args.perf:
            hybrid = Path('/sys/bus/event_source/devices/cpu_core').exists()
            events = [f'cpu_core/{event}/u' if hybrid else f'{event}:u'
                      for event in ['cycles', 'instructions', 'branches', 'branch-misses']]
            for iteration in range(5):
                for name in names[iteration % len(names):] + names[:iteration % len(names)]:
                    log = artifacts / f'{name}-perf-{iteration}.csv'
                    output = capture(['perf', 'stat', '--no-big-num', '-x', ',', '-e', ','.join(events),
                                      '-o', log, '--', *commands[name]])
                    parse_output(output)
                    counters = {}
                    for line in log.read_text().splitlines():
                        fields = line.split(',')
                        if len(fields) >= 3 and fields[0].strip().isdigit():
                            counters[fields[2]] = {'count': int(fields[0]), 'runtime_and_coverage': fields[3:]}
                    assert all(event in counters for event in events), log.read_text()
                    results[name]['perf'].append(counters)
        for name, result in results.items():
            result['elapsed_ns'] = summarize([sample['elapsed_ns'] for sample in result['samples']])
            result['workload_ns'] = {label: summarize([s['workloads'][label]['ns'] for s in result['samples']])
                                     for label in CHECKSUMS}
            print(f"{name}: {result['elapsed_ns']['median'] / 1e6:.3f} ms median; all six checksums match")
        report = {'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'revision': capture(['git', 'rev-parse', 'HEAD']), 'status': capture(['git', 'status', '--short']),
                  'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in [
                      ROOT / 'toolchain/mayc/src/backend/x86_64.may', ROOT / 'toolchain/mayc/src/regalloc.may',
                      HERE / 'backend/raw_performance.may', HERE / 'backend/raw_performance.c']},
                  'uname': capture(['uname', '-a']), 'lscpu': capture(['lscpu']),
                  'gcc': capture(['gcc', '--version']), 'cpu': args.cpu,
                  'allowed_cpus': sorted(os.sched_getaffinity(0)), 'runs': args.runs,
                  'warmup': args.warmup, 'compilers': compilers, 'results': results,
                  'notes': 'End-to-end samples include Python process launch/capture overhead. Workload timers exclude output. '
                           'Host is not isolated; no timing thresholds or per-pass attribution. '
                           'GCC scalar disables tree vectorization only. Static counts cover entire executables.'}
        if args.output:
            # Keep every sample without repeating checksums and field names for
            # every workload/run. parse_output has checked all of them above.
            report['checksums'] = CHECKSUMS
            for result in results.values():
                samples = result['samples']
                result['samples'] = {'elapsed_ns': [s['elapsed_ns'] for s in samples],
                                     'workload_ns': {label: [s['workloads'][label]['ns'] for s in samples]
                                                     for label in CHECKSUMS}}
            args.output.resolve().write_text(json.dumps(report, indent=2) + '\n')
            print(f'Report: {args.output}; disassembly and perf logs: {artifacts}')


if __name__ == '__main__':
    main()
