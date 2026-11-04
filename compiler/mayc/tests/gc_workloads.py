#!/usr/bin/env python3
"""GC workload suite and baseline runner (MOSAIC roadmap M0).

Builds each workload with the selected compiler, runs it with
`MAYC_GC_STATS=1`, and records wall and CPU time (from wait4), peak RSS and
the runtime's final `GC key=value` summary: collections, bytes and objects
allocated, marked bytes and objects, heap bytes swept, total pause and the
p50/p99/max pause. Runs are repeated; the report gives medians, the GC share
of wall time and whether every run printed the same output.

Workloads (docs/design/MOSAIC_GC.md, M0):
    selfhost        mayc compiling compiler/mayc/main.may (largest real heap)
    trees hashmap strings nbody
                    the cross-language programs in backend/xlang/may/
    maylsp          a replayed language-server session: open strict.may, then
                    incremental edits with hover/completion requests and
                    periodic pull diagnostics and document symbols
    random_graph cache_mix cross_mutation
                    adversarial programs in gc_workloads/

Mayboard (named in the roadmap) is not included: a program with C externs
exits through libc, which never reaches the runtime's exit report, and its
snapshot mode renders a single frame.

Usage:
    python3 compiler/mayc/tests/gc_workloads.py --runs 5 --json /tmp/gc.json --markdown /tmp/gc.md
    python3 compiler/mayc/tests/gc_workloads.py --only trees cache_mix --runs 3
    python3 compiler/mayc/tests/gc_workloads.py --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288
    python3 compiler/mayc/tests/gc_workloads.py --self-test

Timings do not gate anything; `--self-test` only checks that every workload
builds, runs, reports and prints its expected output (one run each, without
the slow ones).
"""
import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from backends import ROOT, compiler_binary

TESTS = ROOT / 'compiler/mayc/tests'
XLANG = TESTS / 'backend/xlang/may'
SUITE = TESTS / 'gc_workloads'
LSP_EDITS = 20

# Expected stdout (without GC lines) of the deterministic workloads. The
# adversarial checksums were cross-checked against straight Python ports of the
# three programs, so a collector that frees or corrupts a live object changes
# them.
EXPECTED = {
    'trees': '14592688 131071\n',
    'hashmap': '1632632653\n',
    'strings': '3488890 3788889\n',
    'random_graph': '50242916 1350000\n',
    'cache_mix': '9324816 20000\n',
    'cross_mutation': '533923\n',
}

WORKLOADS = ['selfhost', 'trees', 'hashmap', 'strings', 'nbody', 'maylsp',
             'random_graph', 'cache_mix', 'cross_mutation']
SLOW = {'selfhost', 'maylsp'}
ADVERSARIAL = {'random_graph', 'cache_mix', 'cross_mutation'}
SUMMARY = re.compile(rb'GC collections=[^\n]*')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(compiler):
    runtime = ROOT / 'compiler/mayc/runtime'
    sidecars = {name: sha256(path) for name, path in [
        ('native.may', ROOT / 'compiler/mayc/native.may'),
        ('prelude.may', ROOT / 'stdlib/prelude.may'),
        ('runtime/fat.may', runtime / 'fat.may'),
        ('runtime/fat_linux.may', runtime / 'fat_linux.may'),
        ('runtime/math.may', runtime / 'math.may')]}
    def git(*arguments):
        result = subprocess.run(['git', *arguments], cwd=ROOT, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    cpu = None
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                cpu = line.split(':', 1)[1].strip()
                break
    except OSError:
        pass
    return {'compiler': str(compiler), 'compiler_sha256': sha256(compiler), 'sidecars': sidecars,
            'commit': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain')),
            'host': platform.platform(), 'cpu': cpu}


def lsp_session(path, edits):
    """Framed LSP messages for a replayed editing session of `path`."""
    uri = path.as_uri()
    text = path.read_text()
    lines = text.count('\n')
    frames = []
    counter = [0]

    def frame(method, params, request=False):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if request:
            counter[0] += 1
            message['id'] = counter[0]
        body = json.dumps(message).encode()
        frames.append(b'Content-Length: %d\r\n\r\n' % len(body) + body)

    frame('initialize', {'processId': None, 'rootUri': ROOT.as_uri(), 'capabilities': {}}, True)
    frame('initialized', {})
    frame('textDocument/didOpen', {'textDocument': {'uri': uri, 'languageId': 'maylang', 'version': 1, 'text': text}})
    for n in range(edits):
        line = (n * 37) % lines
        frame('textDocument/didChange', {
            'textDocument': {'uri': uri, 'version': n + 2},
            'contentChanges': [{'range': {'start': {'line': line, 'character': 0},
                                          'end': {'line': line, 'character': 0}},
                                'text': f'// edit {n}\n'}]})
        lines += 1
        frame('textDocument/hover', {'textDocument': {'uri': uri},
                                     'position': {'line': (n * 53) % lines, 'character': 8}}, True)
        frame('textDocument/completion', {'textDocument': {'uri': uri},
                                          'position': {'line': (n * 29) % lines, 'character': 4}}, True)
        if n % 10 == 0:
            frame('textDocument/diagnostic', {'textDocument': {'uri': uri}}, True)
            frame('textDocument/documentSymbol', {'textDocument': {'uri': uri}}, True)
    frame('shutdown', None, True)
    frame('exit', None)
    return b''.join(frames), counter[0]


def compile_program(compiler, source, output, cwd=ROOT):
    result = subprocess.run([str(compiler), str(source), '-o', str(output)], cwd=cwd,
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f'compiling {source} failed:\n{result.stderr}')


def prepare(name, compiler, work):
    """Build workload `name` in `work`; returns its run description."""
    directory = work / name
    directory.mkdir()
    binary = directory / name
    if name == 'selfhost':
        compile_program(compiler, ROOT / 'compiler/mayc/main.may', binary)
        # A compiler outside the checkout needs its sidecars beside it.
        (directory / 'native.may').symlink_to(ROOT / 'compiler/mayc/native.may')
        (directory / 'prelude.may').symlink_to(ROOT / 'stdlib/prelude.may')
        (directory / 'runtime').symlink_to(ROOT / 'compiler/mayc/runtime')
        return {'argv': [str(binary), str(ROOT / 'compiler/mayc/main.may'), '-o', str(directory / 'out')]}
    if name in ('trees', 'hashmap', 'strings', 'nbody'):
        compile_program(compiler, XLANG / f'{name}.may', binary)
        return {'argv': [str(binary)]}
    if name in ADVERSARIAL:
        compile_program(compiler, SUITE / f'{name}.may', binary)
        return {'argv': [str(binary)]}
    if name == 'maylsp':
        compile_program(compiler, ROOT / 'tools/maylsp/main.may', binary)
        session, requests = lsp_session(ROOT / 'compiler/mayc/src/strict.may', LSP_EDITS)
        stdin = directory / 'session.lsp'
        stdin.write_bytes(session)
        return {'argv': [str(binary)], 'stdin': stdin, 'responses': requests}
    raise ValueError(name)


def run_once(spec, environment, cpu, scratch):
    """One run: wall and CPU time from wait4, stdout, exit status."""
    output = scratch / 'stdout'
    stdin = spec.get('stdin')
    started = time.perf_counter()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child
        try:
            if cpu is not None:
                os.sched_setaffinity(0, {cpu})
            source = os.open(str(stdin) if stdin else os.devnull, os.O_RDONLY)
            os.dup2(source, 0)
            sink = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(sink, 1)
            quiet = os.open(os.devnull, os.O_WRONLY)
            os.dup2(quiet, 2)
            os.chdir(str(ROOT))
            os.execve(spec['argv'][0], spec['argv'], environment)
        finally:
            os._exit(127)
    _pid, status, usage = os.wait4(pid, 0)
    elapsed = time.perf_counter() - started
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
    text = output.read_bytes()
    summaries = SUMMARY.findall(text)
    stats = {}
    if summaries:
        stats = {key.decode(): int(value) for key, value in re.findall(rb'(\w+)=(-?\d+)', summaries[-1])}
    plain = SUMMARY.sub(b'', text).replace(b'\n\n', b'\n') if summaries else text
    return {'exit': code, 'wall_s': elapsed, 'cpu_s': usage.ru_utime + usage.ru_stime,
            'peak_rss_kib': usage.ru_maxrss, 'gc': stats, 'output': plain}


def environment_for(overrides, spec):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('MAYC_GC_')}
    environment['MAYC_GC_STATS'] = '1'
    environment.update(overrides)
    return environment


def check_run(name, spec, sample):
    if sample['exit'] != 0:
        raise RuntimeError(f'{name}: exited {sample["exit"]}')
    if not sample['gc']:
        raise RuntimeError(f'{name}: no GC summary line')
    expected = EXPECTED.get(name)
    if expected is not None and sample['output'].decode(errors='replace') != expected:
        raise RuntimeError(f'{name}: unexpected output {sample["output"][:200]!r}')
    if 'responses' in spec:
        responses = sample['output'].count(b'"id":')
        if responses != spec['responses']:
            raise RuntimeError(f'{name}: {responses} responses to {spec["responses"]} requests')


def median(values):
    return statistics.median(values) if values else None


def summarize(name, samples):
    gc = [sample['gc'] for sample in samples]
    def field(key):
        return median([stats.get(key, 0) for stats in gc])
    def constant(key):
        values = {stats.get(key, 0) for stats in gc}
        return values.pop() if len(values) == 1 else sorted(values)
    shares = [stats.get('pause_ns', 0) / 1e9 / sample['wall_s'] for stats, sample in zip(gc, samples)]
    outputs = {hashlib.sha256(sample['output']).hexdigest() for sample in samples}
    return {
        'workload': name, 'runs': len(samples),
        'wall_median_s': round(median([s['wall_s'] for s in samples]), 4),
        'cpu_median_s': round(median([s['cpu_s'] for s in samples]), 4),
        'gc_pause_median_s': round(field('pause_ns') / 1e9, 4),
        'gc_share_median': round(median(shares), 4),
        'pause_p50_median_ms': round(field('pause_p50_ns') / 1e6, 3),
        'pause_p99_median_ms': round(field('pause_p99_ns') / 1e6, 3),
        'pause_max_median_ms': round(field('pause_max_ns') / 1e6, 3),
        'collections': constant('collections'),
        'allocated_bytes': constant('allocated'),
        'allocated_objects': constant('objects'),
        'marked_bytes': constant('marked'),
        'marked_objects': constant('marked_objects'),
        'swept_bytes': constant('swept'),
        'live_after_last_bytes': constant('live'),
        'heap_peak_bytes': constant('peak'),
        'peak_rss_kib': max(s['peak_rss_kib'] for s in samples),
        'outputs_identical': len(outputs) == 1,
        'samples': [{key: value for key, value in sample.items() if key != 'output'} for sample in samples],
    }


def markdown(report):
    def mib(value):
        return '-' if not isinstance(value, int) else f'{value / 1048576:.1f}'
    def count(value):
        return str(value) if not isinstance(value, int) else f'{value:,}'
    lines = ['| Workload | runs | wall (s) | GC pause (s) | GC share | collections | p50 / p99 / max pause (ms) '
             '| allocated (MiB / objects) | marked per collection (objects) | peak RSS (MiB) |',
             '| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |']
    for row in report['workloads']:
        collections = row['collections']
        per = (row['marked_objects'] // collections if isinstance(collections, int) and collections
               and isinstance(row['marked_objects'], int) else '-')
        lines.append(
            f'| {row["workload"]} | {row["runs"]} | {row["wall_median_s"]:.3f} | {row["gc_pause_median_s"]:.3f} '
            f'| {row["gc_share_median"] * 100:.1f}% | {count(collections)} '
            f'| {row["pause_p50_median_ms"]:.1f} / {row["pause_p99_median_ms"]:.1f} / {row["pause_max_median_ms"]:.1f} '
            f'| {mib(row["allocated_bytes"])} / {count(row["allocated_objects"])} | {count(per)} '
            f'| {row["peak_rss_kib"] / 1024:.1f} |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--only', nargs='+', choices=WORKLOADS, default=None)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--cpu', type=int, default=None, help='pin each run to this CPU')
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE',
                        help='extra environment for every run (for example MAYC_GC_MIN=8388608)')
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--markdown', type=Path, default=None)
    parser.add_argument('--self-test', action='store_true',
                        help='one run of every fast workload, checking outputs and summaries')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler).resolve()
    overrides = dict(item.split('=', 1) for item in args.env)
    names = args.only or [name for name in WORKLOADS if not (args.self_test and name in SLOW)]
    runs = 1 if args.self_test else args.runs
    report = {'identity': identity(compiler), 'environment': overrides, 'runs': runs, 'cpu': args.cpu,
              'workloads': []}
    with tempfile.TemporaryDirectory(prefix='mayc-gc-workloads-') as temporary:
        work = Path(temporary)
        for name in names:
            spec = prepare(name, compiler, work)
            environment = environment_for(overrides, spec)
            samples = []
            try:
                for _ in range(runs):
                    sample = run_once(spec, environment, args.cpu, work / name)
                    check_run(name, spec, sample)
                    samples.append(sample)
                row = summarize(name, samples)
                if not row['outputs_identical']:
                    raise RuntimeError(f'{name}: output differs between runs')
            except Exception:
                # Keep what was measured so far.
                if args.json:
                    args.json.write_text(json.dumps(report, indent=1) + '\n')
                raise
            report['workloads'].append(row)
            print(f'{"PASS" if args.self_test else "RAN "} {name}: {row["wall_median_s"]:.3f} s, '
                  f'{row["collections"]} collections, GC {row["gc_share_median"] * 100:.1f}%', flush=True)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    table = markdown(report)
    if args.markdown:
        args.markdown.write_text(table)
    if not args.self_test:
        print(table, end='')


if __name__ == '__main__':
    main()
