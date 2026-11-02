#!/usr/bin/env python3
"""Retention probe for the conservative collector (#135 stack maps design).

The full runtime reports only the bytes each sweep marked live. This harness
builds the same programs against a copy of the runtime that also prints, after
every sweep, the marked live bytes, the allocation frontier and the next
threshold. Each probe keeps a live set the harness can compute exactly and
generates garbage in a loop, so

    reported live - (known kept set + known true transient live)

is bytes the sweep kept because a conservative word looked like a pointer (or
because a slot that a precise map would call dead still held one). The number
is a lower bound: the transient bound is generous.

Usage:
    python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new
    python3 compiler/mayc/tests/stack_retention.py --heaps 8 16 32 --json /tmp/ret.json
    python3 compiler/mayc/tests/stack_retention.py --workload trees --heaps 16 64 256
    python3 compiler/mayc/tests/stack_retention.py --inventory compiler/mayc/build/bin/mayc_new

The measurement modes used by the collector work are `--xlang` (the eight
roadmap workloads against the instrumented runtime), `--compare` with `--env`
NAME=VALUE (interleaved base versus tuned environment on the same binary) and
`--pair A B` (interleaved CPU/wall comparison of two executables on a pinned
CPU, for default-off policy changes that must not shift code layout).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from backends import ROOT, compiler_binary

# Runtime blocks that are live regardless of the program: rt_init's HSTACK
# (rt_alloc(64 * 64)) and, once any global root is registered, GROOTS
# (rt_alloc(1048576)). Both include the 16-byte header.
HSTACK_BYTES = 4112
GROOTS_BYTES = 1048592
RECORD_2 = 128          # 48 + 2 * 32 payload, 16-byte header: one 2-field record
MAP_2 = 144             # 40-byte map header block + 4-value entry block
LIST_INT_2 = 112        # 32-byte list header block + a capacity-4 Int buffer
TREE_NODE = RECORD_2

METER = r'''
// ---- stack-retention probe meter (test-only runtime copy) -------------------
mut SRBUF: Any = 0;
fun sr_num(v: Any) -> Any {
    mut n: Any = v;
    if (n < 0) { rt_write(addr("-"), 1); n = 0 - n; }
    mut d: Any = 0;
    if (n == 0) { store8(SRBUF, 48); d = 1; }
    while (n > 0) { store8(SRBUF + d, 48 + n % 10); n = n / 10; d += 1; }
    mut i: Any = 0;
    while (i * 2 < d) {
        let c: Any = load8(SRBUF + i);
        store8(SRBUF + i, load8(SRBUF + d - 1 - i));
        store8(SRBUF + d - 1 - i, c);
        i += 1;
    }
    rt_write(SRBUF, d);
    return 0;
}
fun sr_pair(name: Any, length: Any, v: Any) -> Any {
    rt_write(name, length); sr_num(v);
    return 0;
}
fun sr_report() -> Any {
    if (SRBUF == 0) { SRBUF = syscall(9, 0, 4096, 3, 34, 0 - 1, 0); }
    if (SRBUF < 0) { return 0; }
    rt_write(addr("RET"), 3);
    sr_pair(addr(" count="), 7, GCCOUNT);
    sr_pair(addr(" live="), 6, GCLIVE);
    sr_pair(addr(" extent="), 8, HP - HEAP);
    sr_pair(addr(" threshold="), 11, HEAPEND - HEAP);
    sr_pair(addr(" free="), 6, FREECOUNT);
    sr_pair(addr(" roots="), 7, GCOUNT);
    rt_write(addr("\n"), 1);
    return 0;
}
'''

SZ_ANCHOR = 'mut sz: Any = 268435456;'
SWEEP_ANCHOR = '    GCLIVE = live;\n    HEAPEND = rt_threshold(live);\n'

PROBES = {
    # name: source, kept bytes, transient upper bound, has a true global root
    'records': (
        '''struct P { a: Int, b: Int }
let keep: P = P(1, 2);
mut i: Int = 0;
while (i < __ITERS__) { let g: Any = P(i, i + 1); i += 1; }
print("done", keep.a + keep.b);
''', RECORD_2, 0, False, []),
    'records_noopt': (
        '''struct P { a: Int, b: Int }
let keep: P = P(1, 2);
mut i: Int = 0;
while (i < __ITERS__) { let g: Any = P(i, i + 1); i += 1; }
print("done", keep.a + keep.b);
''', RECORD_2, 0, False, ['--no-opt']),
    'records_global': (
        '''struct P { a: Int, b: Int }
let keep: P = P(1, 2);
fun keep_read() -> Int { return keep.a; }
mut i: Int = 0;
while (i < __ITERS__) { let g: Any = P(i, i + 1); i += 1; }
print("done", keep_read(), keep.b);
''', RECORD_2, 0, True, []),
    'maps': (
        '''let keep: Any = {"k": 1};
mut i: Int = 0;
while (i < __ITERS__) { let g: Any = {"a": i, "b": i + 1}; i += 1; }
print("done", len(keep), keep["k"] ?? -1);
''', MAP_2, MAP_2, False, []),
    'lists': (
        '''let keep: List<Int> = [1, 2, 3];
mut i: Int = 0;
while (i < __ITERS__) { let g: List<Int> = [i, i + 1]; i += 1; }
print("done", len(keep));
''', LIST_INT_2, LIST_INT_2, False, []),
    'tree6': (
        '''struct Node { left: Any, right: Any }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
let keep: Node = make(0);
mut i: Int = 0;
while (i < __ITERS__) { let t: Any = make(6); i += 1; }
print("done", value_tag(keep));
''', RECORD_2, 127 * TREE_NODE, False, []),
    'big12_churn': (
        '''struct Node { left: Any, right: Any }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
mut total: Int = 0;
mut i: Int = 0;
while (i < __ITERS__) { let t: Any = make(12); total += value_tag(t); i += 1; }
print("done", total);
''', 0, 4095 * TREE_NODE, False, []),
    'big14_churn': (
        '''struct Node { left: Any, right: Any }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
mut total: Int = 0;
mut i: Int = 0;
while (i < __ITERS__) { let t: Any = make(14); total += value_tag(t); i += 1; }
print("done", total);
''', 0, 16383 * TREE_NODE, False, []),
    'big16_churn': (
        '''struct Node { left: Any, right: Any }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
mut total: Int = 0;
mut i: Int = 0;
while (i < __ITERS__) { let t: Any = make(16); total += value_tag(t); i += 1; }
print("done", total);
''', 0, 131071 * TREE_NODE, False, []),
    'big16_kept': (
        '''struct Node { left: Any, right: Any }
struct P { a: Int, b: Int }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
let keep: Any = make(16);
mut i: Int = 0;
while (i < __ITERS__) { let g: Any = P(i, i + 1); i += 1; }
print("done", value_tag(keep));
''', 131071 * TREE_NODE, 0, False, []),
    'tree8': (
        '''struct Node { left: Any, right: Any }
fun make(d: Int) -> Node {
    if (d == 0) { return Node(nil, nil); }
    return Node(make(d - 1), make(d - 1));
}
let keep: Node = make(0);
mut i: Int = 0;
while (i < __ITERS__) { let t: Any = make(8); i += 1; }
print("done", value_tag(keep));
''', RECORD_2, 1023 * TREE_NODE, False, []),
}

GARBAGE = {'records': RECORD_2, 'records_noopt': RECORD_2, 'records_global': RECORD_2,
           'maps': MAP_2, 'lists': LIST_INT_2, 'tree6': 127 * TREE_NODE, 'tree8': 1023 * TREE_NODE,
           'big12_churn': 4095 * TREE_NODE, 'big14_churn': 16383 * TREE_NODE,
           'big16_churn': 131071 * TREE_NODE, 'big16_kept': RECORD_2}

# xlang workloads, with the true live set the collector should have measured.
WORKLOADS = {
    'trees': {'source': ROOT / 'compiler/mayc/tests/backend/xlang/may/trees.may',
              'fixed': HSTACK_BYTES,
              'kept': 131071 * TREE_NODE,             # long_lived = make(16)
              'transient': 131071 * TREE_NODE},        # the tree being built
    'nbody': {'source': ROOT / 'compiler/mayc/tests/backend/xlang/may/nbody.may',
              'fixed': HSTACK_BYTES, 'kept': 0, 'transient': 0},
    'hashmap': {'source': ROOT / 'compiler/mayc/tests/backend/xlang/may/hashmap.may',
                'fixed': HSTACK_BYTES | GROOTS_BYTES, 'kept': 0, 'transient': 0},
    # The same workload without the 16.8 MiB long-lived tree: the only true
    # live data is the tree being built, so the reported live set separates
    # the current tree from conservative retention.
    'trees_nolived': {'source': ROOT / 'compiler/mayc/tests/backend/xlang/may/trees.may',
                      'kept': 0, 'transient': 131071 * TREE_NODE,
                      'transform': [('let long_lived: Node = make(max_depth);\n', ''),
                                    ('print(total, check(long_lived));', 'print(total);')]},
    # The final List<Bool> buffer: capacity 2**24 bytes for 10M elements.
    'sieve': {'source': ROOT / 'compiler/mayc/tests/backend/xlang/may/sieve.may',
              'fixed': HSTACK_BYTES, 'kept': 48 + 16777248, 'transient': 16777248},
}


def probe_environment(overrides):
    """The child environment: inherited minus the GC tuning variables, plus the
    requested overrides, so a shell setting cannot leak into a measurement."""
    import os
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith('MAYC_GC_')}
    environment.update(overrides)
    return environment


def instrument_runtime(runtime, heap_mib):
    host = (runtime / 'fat_linux.may').read_text()
    if host.count(SZ_ANCHOR) != 1:
        raise ValueError('runtime/fat_linux.may heap-size anchor changed')
    host = host.replace(SZ_ANCHOR, f'mut sz: Any = {heap_mib * 1024 ** 2};')
    if host.count(SWEEP_ANCHOR) != 1:
        raise ValueError('runtime/fat_linux.may sweep anchor changed')
    host = host.replace(SWEEP_ANCHOR, SWEEP_ANCHOR + '    sr_report();\n')
    return host + '\n' + METER


def run_rusage(command, output, environment, timeout=300):
    """Run command, capture stdout to output, return (status, peak RSS KiB,
    elapsed, user, system) seconds."""
    import os
    import time
    started = time.perf_counter()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(fd, 1)
        except OSError:
            os._exit(127)
        os.execve(command[0], command, environment)
        os._exit(127)
    _pid, status, usage = os.wait4(pid, 0)
    elapsed = time.perf_counter() - started
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
    return code, usage.ru_maxrss, elapsed, usage.ru_utime, usage.ru_stime


def parse_sweeps(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith('RET '):
            continue
        row = {}
        for field in line[4:].split():
            key, _, value = field.partition('=')
            row[key] = int(value)
        rows.append(row)
    return rows


def build_and_run(compiler, source_text, name, heap_mib, extra, workdir, environment):
    runtime = ROOT / 'compiler/mayc/runtime'
    directory = workdir / f'{name}-{heap_mib}'
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / 'mayc'
    shutil.copy2(compiler, binary)
    shutil.copytree(runtime, directory / 'runtime', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'compiler/mayc/native.may', directory / 'native.may')
    shutil.copy2(ROOT / 'stdlib/prelude.may', directory / 'prelude.may')
    (directory / 'runtime/fat_linux.may').write_text(instrument_runtime(runtime, heap_mib))
    program = directory / 'probe.may'
    program.write_text(source_text)
    built = subprocess.run([str(binary), *extra, str(program), '-o', str(directory / 'probe')],
                           cwd=ROOT, capture_output=True, timeout=300)
    if built.returncode != 0:
        raise SystemExit(f'{name} heap {heap_mib} MiB: compile failed\n' +
                         (built.stdout + built.stderr).decode(errors='replace'))
    status, rss, elapsed, user, system = run_rusage([str(directory / 'probe')],
                                                    directory / 'stdout.txt', environment)
    if status != 0:
        raise SystemExit(f'{name} heap {heap_mib} MiB: run exited {status}')
    sweeps = parse_sweeps((directory / 'stdout.txt').read_text())
    return sweeps, {'peak_rss_kb': rss, 'elapsed_s': round(elapsed, 3),
                    'user_s': round(user, 3), 'system_s': round(system, 3)}


def retention(rows, kept, transient):
    """Per-sweep retention bounds against the known live set.

    The GROOTS block exists only once the program registered a global root,
    which the meter reports per sweep as `roots`.
    """
    if not rows:
        return {'collections': 0, 'live_min': 0, 'live_median': 0, 'live_max': 0,
                'extent_max': 0, 'threshold_max': 0, 'known_true_min': kept,
                'known_true_max': kept + transient, 'retained_lower_min': 0,
                'retained_lower_max': 0, 'retained_upper_max': 0}
    live = [row['live'] for row in rows]
    fixed = [HSTACK_BYTES + (GROOTS_BYTES if row['roots'] > 0 else 0) for row in rows]
    true_max = max(fixed) + kept + transient
    true_min = min(fixed) + kept
    return {
        'collections': len(rows),
        'live_min': min(live), 'live_median': sorted(live)[len(live) // 2], 'live_max': max(live),
        'extent_max': max(row['extent'] for row in rows),
        'threshold_max': max(row['threshold'] for row in rows),
        'known_true_min': true_min, 'known_true_max': true_max,
        'retained_lower_min': min(l - true_max for l in live),
        'retained_lower_max': max(l - true_max for l in live),
        'retained_upper_max': max(l - true_min for l in live),
    }



def inventory(binary):
    """Approximate the stack-map metadata a precise collector would need.

    Counts function prologues (push rbp; mov rbp, rsp; sub rsp, imm32), their
    frame sizes and the call instructions between consecutive prologues. A
    call is an upper bound on a safepoint: only calls that can reach an
    allocation need a map, but without a call-graph walk every call is counted.
    Two encodings are sized: one byte per 16-byte frame slot per safepoint, and
    a compact two bits per slot (value present / may hold a pointer).
    """
    import struct
    image = Path(binary).read_bytes()
    if image[:4] != b'\x7fELF':
        raise SystemExit(f'{binary}: not an ELF file')
    phoff = struct.unpack_from('<Q', image, 32)[0]
    phentsize, phnum = struct.unpack_from('<HH', image, 54)
    text = None
    for index in range(phnum):
        base = phoff + index * phentsize
        p_type, p_flags = struct.unpack_from('<II', image, base)
        p_offset, _vaddr, _paddr, p_filesz = struct.unpack_from('<QQQQ', image, base + 8)
        if p_type == 1 and p_flags & 1:
            text = image[p_offset:p_offset + p_filesz]
    if text is None:
        raise SystemExit(f'{binary}: no executable segment')
    prologue = b'\x55\x48\x89\xe5\x48\x81\xec'
    frames = []
    position = 0
    while True:
        found = text.find(prologue, position)
        if found < 0:
            break
        frame = struct.unpack_from('<I', text, found + 7)[0]
        frames.append((found, frame))
        position = found + 1
    calls = [i for i in range(len(text) - 4) if text[i] == 0xE8]
    total_slots = 0
    byte_maps = 0
    bit_maps = 0
    call_counts = []
    for index, (start, frame) in enumerate(frames):
        end = frames[index + 1][0] if index + 1 < len(frames) else len(text)
        slots = frame // 16
        also = sum(1 for c in calls if start <= c < end)
        total_slots += slots
        call_counts.append(also)
        byte_maps += also * slots
        bit_maps += also * ((slots + 3) // 4 + 1)
    result = {
        'binary': str(binary), 'code_bytes': len(text),
        'functions': len(frames),
        'frame_bytes_max': max(frame for _start, frame in frames),
        'slots_median': sorted(frame // 16 for _start, frame in frames)[len(frames) // 2],
        'slots_total': total_slots,
        'calls': len(calls),
        'safepoint_map_bytes_1byte': byte_maps,
        'safepoint_map_bytes_2bit': bit_maps,
        'map_share_of_code': round(bit_maps / len(text), 4),
    }
    return result


def compare_workload(compiler, bench, options, workdir, base_environment, tuned_environment):
    """Run one xlang workload alternating base and tuned environments on the
    same binary, so time and RSS differences are not confounded by machine
    load. Reports medians and the per-run samples."""
    source = ROOT / 'compiler/mayc/tests/backend/xlang/may' / f'{bench}.may'
    rows, usage = build_and_run(compiler, source.read_text(), 'xlang-compare-' + bench,
                                options.xlang_heap_mib, [], workdir, base_environment)
    directory = workdir / f'xlang-compare-{bench}-{options.xlang_heap_mib}'
    samples = {'base': [], 'tuned': []}
    outputs = {}
    for index in range(options.runs):
        order = ('base', 'tuned') if index % 2 == 0 else ('tuned', 'base')
        for which in order:
            environment = base_environment if which == 'base' else tuned_environment
            status, rss, elapsed, user, system = run_rusage(
                [str(directory / 'probe')], directory / f'run-{which}-{index}.txt', environment)
            if status != 0:
                raise SystemExit(f'{bench} {which}: run exited {status}')
            text = (directory / f'run-{which}-{index}.txt').read_bytes()
            # The meter's own RET lines are diagnostics, not program output.
            clean = b'\n'.join(line for line in text.splitlines()
                                if not line.startswith(b'RET '))
            outputs.setdefault(which, clean)
            if outputs[which] != clean:
                raise SystemExit(f'{bench} {which}: output changed between runs')
            sweeps = parse_sweeps(text.decode(errors='replace'))
            samples[which].append({'elapsed_s': round(elapsed, 3), 'peak_rss_kib': rss,
                                   'collections': len(sweeps),
                                   'live_max': max((row['live'] for row in sweeps), default=0)})
    if outputs['base'] != outputs['tuned']:
        raise SystemExit(f'{bench}: the policy changed the program output')
    report = {'workload': bench, 'nominal_heap_mib': options.xlang_heap_mib,
              'compiler': str(compiler), 'runs': options.runs,
              'overrides': {name: value for name, value in tuned_environment.items()
                            if name.startswith('MAYC_GC_')}}
    for which in ('base', 'tuned'):
        elapsed = [sample['elapsed_s'] for sample in samples[which]]
        rss = [sample['peak_rss_kib'] for sample in samples[which]]
        report[which] = {'samples': samples[which],
                         'median_elapsed_s': round(sorted(elapsed)[len(elapsed) // 2], 3),
                         'min_elapsed_s': min(elapsed),
                         'peak_rss_kib': max(rss),
                         'collections': max(sample['collections'] for sample in samples[which])}
    report['elapsed_ratio'] = round(report['tuned']['median_elapsed_s'] /
                                    report['base']['median_elapsed_s'], 3)
    report['rss_ratio'] = round(report['tuned']['peak_rss_kib'] /
                                report['base']['peak_rss_kib'], 3)
    return report



def pair_measure(binaries, runs, cpu, overrides):
    """Interleaved paired comparison of two executables.

    Runs A and B alternately on one pinned CPU (when `cpu` is set and allowed),
    records the child CPU time (user+system from wait4) and wall time, and
    reports medians, means, the median ratio and how many samples each side
    won. Pairing removes machine-load drift, which dominates absolute times on
    a shared host.
    """
    import os
    environment = probe_environment(overrides)
    first = Path(binaries[0]).resolve()
    second = Path(binaries[1]).resolve()
    samples = {'a': [], 'b': []}
    import time
    for index in range(runs):
        order = (('a', first), ('b', second)) if index % 2 == 0 else (('b', second), ('a', first))
        for name, binary in order:
            started = time.perf_counter()
            pid = os.fork()
            if pid == 0:  # pragma: no cover - child
                try:
                    if cpu is not None:
                        os.sched_setaffinity(0, {cpu})
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, 1)
                except OSError:
                    os._exit(127)
                os.execve(str(binary), [str(binary)], environment)
                os._exit(127)
            _pid, status, usage = os.wait4(pid, 0)
            elapsed = time.perf_counter() - started
            code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
            if code != 0:
                raise SystemExit(f'{binary}: exited {code}')
            samples[name].append({'cpu_s': usage.ru_utime + usage.ru_stime,
                                  'wall_s': elapsed, 'peak_rss_kib': usage.ru_maxrss})

    def summary(rows):
        cpu = sorted(row['cpu_s'] for row in rows)
        wall = sorted(row['wall_s'] for row in rows)
        return {'samples': rows,
                'cpu_median_s': round(cpu[len(cpu) // 2], 6),
                'cpu_mean_s': round(sum(cpu) / len(cpu), 6),
                'cpu_min_s': round(cpu[0], 6),
                'wall_median_s': round(wall[len(wall) // 2], 6),
                'peak_rss_kib': max(row['peak_rss_kib'] for row in rows)}

    a = summary(samples['a'])
    b = summary(samples['b'])
    wins_a = sum(1 for x, y in zip(samples['a'], samples['b']) if x['cpu_s'] < y['cpu_s'])
    wins_b = sum(1 for x, y in zip(samples['a'], samples['b']) if y['cpu_s'] < x['cpu_s'])
    return {'a': {'binary': str(first), **a},
            'b': {'binary': str(second), **b},
            'runs': runs, 'cpu': cpu,
            'cpu_ratio_b_over_a': round(b['cpu_median_s'] / a['cpu_median_s'], 4),
            'wall_ratio_b_over_a': round(b['wall_median_s'] / a['wall_median_s'], 4),
            'wins_a': wins_a, 'wins_b': wins_b, 'ties': runs - wins_a - wins_b}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--heaps', type=int, nargs='+', default=[8, 16, 32])
    parser.add_argument('--modes', nargs='+', default=None, choices=list(PROBES))
    parser.add_argument('--workload', nargs='+', default=[], choices=list(WORKLOADS))
    parser.add_argument('--iterations', type=int, default=0,
                        help='total garbage bytes target in MiB per probe (default 8x the heap)')
    parser.add_argument('--json', default=None)
    parser.add_argument('--inventory', type=Path, nargs='+', default=[],
                        help='measure stack-map metadata for existing binaries')
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE',
                        help='environment override for the measured programs (repeatable)')
    parser.add_argument('--xlang', action='store_true',
                        help='run the eight roadmap workloads with the instrumented runtime')
    parser.add_argument('--compare', action='store_true',
                        help='with --xlang, interleave the base environment and the --env overrides')
    parser.add_argument('--xlang-heap-mib', type=int, default=256,
                        help='nominal heap for --xlang (default 256, as in production)')
    parser.add_argument('--runs', type=int, default=1,
                        help='samples per workload for --xlang (default 1)')
    parser.add_argument('--pair', type=Path, nargs=2, default=None, metavar=('A', 'B'),
                        help='interleaved paired CPU/wall comparison of two executables')
    parser.add_argument('--pair-runs', type=int, default=120,
                        help='samples per side for --pair (default 120)')
    parser.add_argument('--cpu', type=int, default=None,
                        help='pin paired runs to this CPU (must be allowed)')
    options = parser.parse_args()
    if options.modes is None:
        # The large-tree probes need a heap of at least 64 MiB to collect more
        # than once; keep the defaults to the probes that fit the default heaps.
        options.modes = [] if (options.inventory or options.workload or options.xlang or options.pair) else [
            'records', 'maps', 'lists', 'tree6']
    compiler = compiler_binary(options.compiler)
    overrides = {}
    for entry in options.env:
        name, separator, value = entry.partition('=')
        if separator != '=' or not name:
            raise SystemExit(f'--env expects NAME=VALUE, got {entry!r}')
        overrides[name] = value
    environment = probe_environment(overrides)
    report = {'compiler': str(compiler), 'probes': [], 'workloads': [], 'inventory': []}
    for binary in options.inventory:
        row = inventory(binary)
        report['inventory'].append(row)
        print(f"{binary.name}: {row['functions']} functions, frame max "
              f"{row['frame_bytes_max']} B, slot median {row['slots_median']}, "
              f"{row['calls']} calls, map bytes 1B/slot {row['safepoint_map_bytes_1byte']:,} "
              f"2bit {row['safepoint_map_bytes_2bit']:,} "
              f"({row['map_share_of_code']:.1%} of code)", flush=True)
    with tempfile.TemporaryDirectory(prefix='mayc-retention-') as directory:
        workdir = Path(directory)
        for heap_mib in options.heaps:
            for name in options.modes:
                source, kept, transient, globals_, extra = PROBES[name]
                total = options.iterations or 8 * heap_mib * 1024 ** 2
                iters = max(200, total // GARBAGE[name])
                rows, usage = build_and_run(compiler, source.replace('__ITERS__', str(iters)),
                                            name, heap_mib, extra, workdir, environment)
                rss = usage['peak_rss_kb']
                row = {'probe': name, 'heap_mib': heap_mib, 'iterations': iters,
                       **usage, **retention(rows, kept, transient)}
                report['probes'].append(row)
                print(f"{name:15s} heap {heap_mib:4d} MiB  collections {row['collections']:3d}  "
                      f"live max {row['live_max'] / 1048576:8.2f} MiB  "
                      f"known true {row['known_true_min']}/{row['known_true_max']} B  "
                      f"retained lower {row['retained_lower_max'] / 1024:9.1f} KiB  "
                      f"upper {row['retained_upper_max'] / 1024:9.1f} KiB  "
                      f"peak {rss / 1024:7.1f} MiB", flush=True)
        for name in options.workload:
            spec = WORKLOADS[name]
            text = spec['source'].read_text()
            for old, new in spec.get('transform', []):
                if text.count(old) != 1:
                    raise SystemExit(f'{name}: transform anchor changed: {old!r}')
                text = text.replace(old, new)
            for heap_mib in options.heaps:
                rows, usage = build_and_run(compiler, text, name, heap_mib, [], workdir, environment)
                rss = usage['peak_rss_kb']
                row = {'workload': name, 'heap_mib': heap_mib, **usage,
                       'sweeps': rows, **retention(rows, spec['kept'], spec['transient'])}
                report['workloads'].append(row)
                print(f"{name:15s} heap {heap_mib:4d} MiB  collections {row['collections']:3d}  "
                      f"live min/med/max {row['live_min'] / 1048576:6.2f}/"
                      f"{row['live_median'] / 1048576:6.2f}/{row['live_max'] / 1048576:6.2f} MiB  "
                      f"retained lower {row['retained_lower_max'] / 1048576:6.2f} MiB  "
                      f"extent max {row['extent_max'] / 1048576:6.2f} MiB  "
                      f"peak {rss / 1024:7.1f} MiB  {row['elapsed_s']:.2f}s", flush=True)
    if options.xlang:
        base_environment = probe_environment({})
        for bench in ['fib', 'collatz', 'sieve', 'hashmap', 'strings', 'mandelbrot', 'nbody', 'trees']:
            if options.compare:
                row = compare_workload(compiler, bench, options, workdir,
                                       base_environment, environment)
                report.setdefault('xlang', []).append(row)
                print(f"xlang {bench:11s} base {row['base']['median_elapsed_s']:7.3f}s / "
                      f"tuned {row['tuned']['median_elapsed_s']:7.3f}s  "
                      f"peak {row['base']['peak_rss_kib'] / 1024:7.1f} -> "
                      f"{row['tuned']['peak_rss_kib'] / 1024:7.1f} MiB  "
                      f"collections {row['base']['collections']} -> {row['tuned']['collections']}", flush=True)
                continue
            source = ROOT / 'compiler/mayc/tests/backend/xlang/may' / f'{bench}.may'
            samples = []
            output = None
            for _ in range(options.runs):
                rows, usage = build_and_run(compiler, source.read_text(), 'xlang-' + bench,
                                            options.xlang_heap_mib, [], workdir, environment)
                with open(workdir / f'xlang-{bench}-{options.xlang_heap_mib}' / 'stdout.txt', 'rb') as handle:
                    text = handle.read()
                if output is None:
                    output = text
                elif text != output:
                    raise SystemExit(f'{bench}: output changed between runs')
                samples.append({'usage': usage, 'last_sweep': rows[-1] if rows else None,
                                'collections': len(rows),
                                'live_max': max((row['live'] for row in rows), default=0),
                                'extent_max': max((row['extent'] for row in rows), default=0),
                                'threshold_max': max((row['threshold'] for row in rows), default=0)})
            elapsed = [sample['usage']['elapsed_s'] for sample in samples]
            rss = [sample['usage']['peak_rss_kb'] for sample in samples]
            collections = [sample['collections'] for sample in samples]
            row = {'workload': bench, 'nominal_heap_mib': options.xlang_heap_mib,
                   'samples': samples,
                   'median_elapsed_s': round(sorted(elapsed)[len(elapsed) // 2], 3),
                   'min_elapsed_s': min(elapsed),
                   'peak_rss_kib': max(rss),
                   'collections': max(collections)}
            report.setdefault('xlang', []).append(row)
            print(f"xlang {bench:11s} collections {row['collections']:4d}  "
                  f"time median {row['median_elapsed_s']:7.3f}s  "
                  f"peak RSS {row['peak_rss_kib'] / 1024:7.1f} MiB  "
                  f"live max {row['samples'][0]['live_max'] / 1048576:6.2f} MiB", flush=True)
    if options.pair:
        if options.cpu is not None and options.cpu not in os.sched_getaffinity(0):
            raise SystemExit(f'--cpu {options.cpu} is not in the allowed affinity mask')
        row = pair_measure(options.pair, options.pair_runs, options.cpu, overrides)
        report['pair'] = row
        print(f"pair {Path(row['a']['binary']).name} vs {Path(row['b']['binary']).name}: "
              f"CPU median {row['a']['cpu_median_s']:.4f}s -> {row['b']['cpu_median_s']:.4f}s "
              f"({(row['cpu_ratio_b_over_a'] - 1) * 100:+.2f}%), "
              f"wall {row['wall_ratio_b_over_a']:.3f}x, "
              f"wins A/B/ties {row['wins_a']}/{row['wins_b']}/{row['ties']}", flush=True)
    if options.json:
        Path(options.json).write_text(json.dumps(report, indent=2) + '\n')
        print(f'wrote {options.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
