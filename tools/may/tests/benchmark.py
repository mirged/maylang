#!/usr/bin/env python3
"""Measure workspace runner overhead with identical compiler and cached artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


def invoke(binary, workspace, arguments, environment):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    result = subprocess.run([str(binary), *arguments], cwd=workspace, env=environment,
                            capture_output=True, timeout=180)
    elapsed = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert result.returncode == 0, (arguments, result.stdout, result.stderr)
    return result, {'wall_ms': elapsed * 1000,
                    'user_ms': (after.ru_utime - before.ru_utime) * 1000,
                    'system_ms': (after.ru_stime - before.ru_stime) * 1000}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--stdlib', type=Path)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--report', type=Path, required=True)
    options = parser.parse_args()
    if options.samples < 1:
        parser.error('--samples must be positive')
    environment = dict(os.environ, MAYC=str(options.compiler.resolve()))
    if options.stdlib:
        environment['MAYLANG_STDLIB'] = str(options.stdlib.resolve())
    else:
        environment.pop('MAYLANG_STDLIB', None)
    runners = {'candidate': options.binary.resolve()}
    if options.baseline:
        runners = {'baseline': options.baseline.resolve(), **runners}
    report = {'host': platform.platform(), 'samples': options.samples,
              'compiler': environment['MAYC'], 'path_bytes': len(environment.get('PATH', '').encode()),
              'environment_bytes': sum(len(k.encode()) + len(v.encode()) + 2 for k, v in environment.items()),
              'runners': {}, 'measurements': {}}
    with tempfile.TemporaryDirectory(prefix='may-benchmark-') as directory:
        workspace = Path(directory)
        (workspace / 'main.may').write_text('print("hello benchmark");\n')
        (workspace / 'may.json').write_text(json.dumps({
            'schema': 1, 'name': 'benchmark', 'default': 'app', 'dependencies': {},
            'targets': {'app': {'kind': 'app', 'entry': 'main.may'}},
        }) + '\n')
        # Populate once; both runners must use the same content-addressed artifact.
        invoke(options.binary.resolve(), workspace, ['build'], environment)
        original_artifacts = sorted(p.name for p in (workspace / '.may/store').iterdir())
        for label, binary in runners.items():
            report['runners'][label] = {'path': str(binary),
                                       'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
            report['measurements'][label] = {}
            for command in ['tasks', 'build', 'run']:
                samples = []
                for _ in range(options.samples):
                    result, timing = invoke(binary, workspace, [command], environment)
                    if command != 'tasks':
                        assert b'cached app' in result.stderr, result.stderr
                    if command == 'run':
                        assert result.stdout == b'hello benchmark\n', result.stdout
                    samples.append(timing)
                medians = {key: statistics.median(sample[key] for sample in samples) for key in samples[0]}
                report['measurements'][label][command] = {'median': medians, 'samples': samples}
                print(f'{label} {command}: {medians["wall_ms"]:.3f} ms median', flush=True)
            assert sorted(p.name for p in (workspace / '.may/store').iterdir()) == original_artifacts
    if options.baseline:
        report['speedup'] = {
            command: report['measurements']['baseline'][command]['median']['wall_ms'] /
                     report['measurements']['candidate'][command]['median']['wall_ms']
            for command in ['tasks', 'build', 'run']
        }
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, indent=2) + '\n')
    print(options.report)


if __name__ == '__main__':
    main()
