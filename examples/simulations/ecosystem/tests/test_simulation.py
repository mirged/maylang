#!/usr/bin/env python3
"""Black-box determinism, checkpoint replay, energy budgets and CLI errors."""
import argparse
import json
import subprocess
import struct
import tempfile
from pathlib import Path


def run(binary, *args):
    return subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True, timeout=120)


def unpack(value):
    if isinstance(value, list):
        return [unpack(v) for v in value]
    if isinstance(value, dict):
        if list(value) == ["$float64"]:
            return struct.unpack("<d", struct.pack("<II", *value["$float64"]))[0]
        return {k: unpack(v) for k, v in value.items()}
    return value


def summary(prefix):
    return json.loads(Path(str(prefix) + '.summary.json').read_text())


def comparable(result):
    result = json.loads(json.dumps(result))
    result.pop('elapsed_seconds')
    result['config'].pop('output')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='maylang-ecosystem-tests-') as directory:
        work = Path(directory)
        a, b, resumed = (work / name for name in ('full', 'split', 'resumed'))
        for prefix in (a, work/'repeat'):
            result = run(binary, 'run', '--generations', 40, '--report', 10, '--checkpoint', 20, '--out', prefix)
            assert result.returncode == 0, result.stderr + result.stdout
        expected = summary(a)
        assert expected['generations_completed'] == 40 and expected['population'] > 0, expected
        assert comparable(expected) == comparable(summary(work/'repeat')), 'seeded run changed'
        print('PASS deterministic seeded evolution')
        result = run(binary, 'run', '--generations', 20, '--report', 10, '--checkpoint', 20, '--out', b)
        assert result.returncode == 0, result.stderr
        result = run(binary, 'resume', str(b)+'.checkpoint.json', '--generations', 40, '--out', resumed)
        assert result.returncode == 0, result.stderr + result.stdout
        assert comparable(expected) == comparable(summary(resumed)), 'checkpoint continuation differs from uninterrupted run'
        assert Path(str(a)+'.genomes.json').read_bytes() == Path(str(resumed)+'.genomes.json').read_bytes()
        print('PASS checkpoint replay and final genotype identity')
        assert abs(expected['energy_error']) < 0.00001, expected['energy_error']
        checkpoint = unpack(json.loads(Path(str(a)+'.checkpoint.json').read_text())["payload"])
        assert all(c['lineage'] == 40 for c in checkpoint['creatures']), 'ticks mislabeled as genetic generations'
        assert all(len(c['traits']) == 6 and len(c['weights']) == 43 for c in checkpoint['creatures'])
        assert all(isinstance(w, int) for c in checkpoint['creatures'] for w in c['weights'])
        assert all(c['energy'] >= 0 and c['body'] > 0 for c in checkpoint['creatures'])
        assert len(checkpoint['creatures']) <= checkpoint['config']['population']
        assert len(Path(str(a)+'.csv').read_text().splitlines()) == len(expected['history']) + 1
        print('PASS energy ledger, genetic lineage depth, population bounds and exports')
        for extra in (['--population', 0], ['--width', 1], ['--ticks', 0], ['--mutation-rate', 2], ['--report', 0], ['--unknown', 1], ['--seed']):
            result = run(binary, 'run', *extra, '--out', work/'invalid')
            assert result.returncode != 0, extra
        # Crossing a process boundary must preserve evolution exactly.
        direct, chunked = work/'direct', work/'chunked'
        result = run(binary, '_worker', 'fresh', '--generations', 520, '--stop-at', 520, '--report', 100, '--out', direct)
        assert result.returncode == 0, result.stderr
        result = run(binary, 'run', '--generations', 520, '--report', 100, '--out', chunked)
        assert result.returncode == 0, result.stderr
        assert comparable(summary(direct)) == comparable(summary(chunked)), 'process boundary changed evolution'
        assert Path(str(direct)+'.genomes.json').read_bytes() == Path(str(chunked)+'.genomes.json').read_bytes()
        print('PASS process-isolated execution matches uninterrupted evolution')
        assert run(binary).returncode == 0
        assert run(binary, 'bogus').returncode == 2
        result = run(binary, 'resume', str(b)+'.checkpoint.json', '--generations', 10)
        assert result.returncode != 0
        print('PASS invalid options, help and backwards resume rejection')


if __name__ == '__main__':
    main()
