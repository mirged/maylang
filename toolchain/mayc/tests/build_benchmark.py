#!/usr/bin/env python3
"""Measure actual compilation, including one full compiler rebuild per version."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


def measure(compiler, source, output, samples, options=()):
    times, sizes, hashes = [], [], []
    for _ in range(samples):
        start = time.perf_counter()
        result = subprocess.run([str(compiler), *options, str(source), '-o', str(output)],
                                cwd=ROOT, capture_output=True, timeout=600)
        times.append((time.perf_counter() - start) * 1000)
        assert result.returncode == 0, result.stderr.decode()
        assert output.read_bytes()[:4] == b'\x7fELF'
        sizes.append(output.stat().st_size)
        hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
    assert len(set(hashes)) == 1, hashes
    return {'median_ms': round(statistics.median(times), 3),
            'samples_ms': [round(t, 3) for t in times], 'image_bytes': sizes[0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    assert args.samples > 0
    report = {'timing': 'whole compiler process including startup and writing; no cache; sequential runs; identical runtime/library sidecars',
              'compiler_rebuild_samples': 1, 'results': {}}
    with tempfile.TemporaryDirectory(prefix='mayc-build-benchmark-') as directory:
        work = Path(directory)
        compilers = {}
        outputs = {}
        sidecars = {'runtime.may': ROOT / 'toolchain/mayc/runtime.may',
                    'native.may': ROOT / 'toolchain/mayc/native.may',
                    'prelude.may': ROOT / 'stdlib/prelude.may'}
        report['sidecars_sha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sidecars.items()}
        for name, original in [('before', args.baseline.resolve()), ('after', args.compiler.resolve())]:
            home = work / name; home.mkdir()
            compiler = home / 'mayc'; shutil.copy2(original, compiler)
            compilers[name] = compiler
            for filename, path in sidecars.items():
                shutil.copy2(path, home / filename)
            shutil.copytree(ROOT / 'toolchain/mayc/runtime', home / 'runtime')
            results = report['results'][name] = {'compiler_sha256': hashlib.sha256(original.read_bytes()).hexdigest()}
            for label, source, samples in [
                ('hello', ROOT / 'examples/hello.may', args.samples),
                ('features', ROOT / 'examples/features.may', args.samples),
                ('compiler_rebuild', ROOT / 'toolchain/mayc/main.may', 1),
            ]:
                results[label] = measure(compiler, source, work / label, samples)
                print(f'{name} {label}: {results[label]["median_ms"]:.3f} ms', flush=True)
                if label != 'compiler_rebuild':
                    run = subprocess.run([str(work / label)], capture_output=True, timeout=10)
                    assert run.returncode == 0 and not run.stderr, run
                    # features.may prints its own clock measurement last.
                    stable_output = re.sub(rb'(?m)^running time is: [^\n]+ seconds$',
                                           b'running time is: <elapsed> seconds', run.stdout)
                    if name == 'before':
                        outputs[label] = stable_output
                    else:
                        assert stable_output == outputs[label], run.stdout
            # Ensure a timed rebuild produced a usable compiler.
            version = subprocess.run([str(work / 'compiler_rebuild'), '--version'], capture_output=True, timeout=10)
            assert version.returncode == 0 and version.stdout.startswith(b'mayc '), version
        report['results']['core_hello'] = measure(compilers['after'], ROOT / 'examples/hello.may', work / 'core', args.samples, ['--runtime', 'core'])
        expected = b'Hello, Maylang!\nHello, world!\n'
        run = subprocess.run([str(work / 'core')], capture_output=True, timeout=10)
        assert run.returncode == 0 and run.stdout == expected and not run.stderr, run
    report['speedups'] = {label: round(report['results']['before'][label]['median_ms'] / report['results']['after'][label]['median_ms'], 2)
                          for label in ['hello', 'features', 'compiler_rebuild']}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
