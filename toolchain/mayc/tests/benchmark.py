#!/usr/bin/env python3
"""Comparable whole-process timings, excluding compilation; assert checksums."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPECTED = b'5025114 400020000\n'
PYTHON = '''def workload():
    steps = 0
    for seed in range(1, 50001):
        n = seed
        while n > 1:
            n = n // 2 if n % 2 == 0 else n * 3 + 1
            steps += 1
    checksum = 0
    for i in range(20000):
        xs = [i, i + 1, i + 2]
        checksum += xs[0] + xs[2]
    print(steps, checksum)
workload()
'''


def measure(command, samples):
    times = []
    for index in range(samples + 1):
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, timeout=30)
        elapsed = (time.perf_counter() - start) * 1000
        assert result.returncode == 0 and result.stdout == EXPECTED and not result.stderr, result
        if index:
            times.append(elapsed)
    return {'median_ms': round(statistics.median(times), 3),
            'samples_ms': [round(value, 3) for value in times]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    assert args.samples > 0
    report = {'workload': 'Collatz for seeds 1..50000; 20000 three-element list allocations',
              'checksum': EXPECTED.decode().strip(), 'timing': 'whole process, compilation excluded, one warm-up', 'results': {}}
    with tempfile.TemporaryDirectory(prefix='mayc-benchmark-') as directory:
        work = Path(directory)
        for name, compiler in [('baseline', args.baseline), ('mayc', args.compiler)]:
            if compiler is None:
                continue
            binary = work / name
            subprocess.run([str(compiler.resolve()), str(HERE / 'backend/bench.may'), '-o', str(binary)], cwd=ROOT, check=True, timeout=120)
            report['results'][name] = measure([str(binary)], args.samples)
        python = work / 'bench.py'
        python.write_text(PYTHON)
        import sys
        report['results']['python'] = measure([sys.executable, str(python)], args.samples)
    results = report['results']
    if 'baseline' in results:
        report['speedup_vs_baseline'] = round(results['baseline']['median_ms'] / results['mayc']['median_ms'], 2)
    report['speedup_vs_python'] = round(results['python']['median_ms'] / results['mayc']['median_ms'], 2)
    text = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
