#!/usr/bin/env python3
"""Record MOSAIC M1 allocation traces (docs/design/MOSAIC_GC.md).

Builds a copy of the compiler whose full runtime carries the hooks in
trace_hooks.may, compiles the GC workloads (tests/gc_workloads.py) with it and
runs each with fd 3 open on a trace file. The shipped runtime is untouched.

Usage:
    python3 compiler/mayc/tests/gc_sim/trace.py --out /tmp/traces --only trees
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from backends import ROOT, compiler_binary  # noqa: E402
import gc_workloads  # noqa: E402

# Workloads that never collect at the default heap are traced under the
# small-heap policy of the M0 baseline so that they have collections at all.
SMALL_HEAP = {'MAYC_GC_MIN': '8388608', 'MAYC_GC_MARGIN': '524288'}
DEFAULT_POLICY = {
    'selfhost': {}, 'trees': {}, 'maylsp': {}, 'random_graph': {}, 'cache_mix': {}, 'cross_mutation': {},
    'hashmap': SMALL_HEAP, 'strings': SMALL_HEAP,
}
RENAMED = ['rt_alloc_kind', 'rt_grow_in_place', 'rt_gc', 'rt_gc_stats_report']


def traced_compiler(compiler, work):
    """A compiler copy whose runtime sidecar records traces."""
    directory = work / 'traced-mayc'
    directory.mkdir()
    binary = directory / 'mayc'
    shutil.copy2(compiler_binary(compiler), binary)
    shutil.copytree(ROOT / 'compiler/mayc/runtime', directory / 'runtime')
    (directory / 'native.may').symlink_to(ROOT / 'compiler/mayc/native.may')
    (directory / 'prelude.may').symlink_to(ROOT / 'stdlib/prelude.may')
    host = directory / 'runtime/fat_linux.may'
    text = host.read_text()
    for name in RENAMED:
        pattern = f'\nfun {name}('
        if text.count(pattern) != 1:
            raise RuntimeError(f'runtime definition of {name} not found exactly once')
        text = text.replace(pattern, f'\nfun {name}_untraced(')
    host.write_text(text + '\n' + (HERE / 'trace_hooks.may').read_text())
    return binary


def record(name, spec, environment, trace_path):
    with open(trace_path, 'wb') as sink:
        def child():
            os.dup2(sink.fileno(), 3)
        stdin = open(spec['stdin'], 'rb') if spec.get('stdin') else subprocess.DEVNULL
        started = time.perf_counter()
        result = subprocess.run(spec['argv'], stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=environment, cwd=ROOT, preexec_fn=child, pass_fds=(sink.fileno(),),
                                timeout=3600)
        elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f'{name} exited {result.returncode}: {result.stderr[:400]!r}')
    expected = gc_workloads.EXPECTED.get(name)
    if expected is not None and result.stdout.decode(errors='replace') != expected:
        raise RuntimeError(f'{name}: unexpected output {result.stdout[:200]!r}')
    return elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--out', type=Path, required=True, help='directory for traces and binaries')
    parser.add_argument('--only', nargs='+', choices=list(DEFAULT_POLICY), default=None)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(DEFAULT_POLICY)
    manifest = {}
    with tempfile.TemporaryDirectory(prefix='mayc-gc-trace-') as temporary:
        work = Path(temporary)
        compiler = traced_compiler(args.compiler, work)
        for name in names:
            spec = gc_workloads.prepare(name, compiler, work)
            binary = Path(spec['argv'][0])
            kept = args.out / f'{name}.bin'
            shutil.copy2(binary, kept)
            environment = {key: value for key, value in os.environ.items() if not key.startswith('MAYC_GC_')}
            environment.update(DEFAULT_POLICY[name])
            trace = args.out / f'{name}.trace'
            elapsed = record(name, spec, environment, trace)
            manifest[name] = {'binary': str(kept), 'trace': str(trace), 'bytes': trace.stat().st_size,
                              'policy': DEFAULT_POLICY[name], 'traced_seconds': round(elapsed, 2)}
            print(f'traced {name}: {trace.stat().st_size / 1048576:.0f} MiB in {elapsed:.1f} s', flush=True)
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')


if __name__ == '__main__':
    main()
