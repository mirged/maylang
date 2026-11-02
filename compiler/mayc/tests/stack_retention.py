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
"""
import argparse
import json
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


def instrument_runtime(runtime, heap_mib):
    host = (runtime / 'fat_linux.may').read_text()
    if host.count(SZ_ANCHOR) != 1:
        raise ValueError('runtime/fat_linux.may heap-size anchor changed')
    host = host.replace(SZ_ANCHOR, f'mut sz: Any = {heap_mib * 1024 ** 2};')
    if host.count(SWEEP_ANCHOR) != 1:
        raise ValueError('runtime/fat_linux.may sweep anchor changed')
    host = host.replace(SWEEP_ANCHOR, SWEEP_ANCHOR + '    sr_report();\n')
    return host + '\n' + METER


def run_rusage(command, output, timeout=300):
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
        os.execv(command[0], command)
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


def build_and_run(compiler, source_text, name, heap_mib, extra, workdir):
    runtime = ROOT / 'compiler/mayc/runtime'
    directory = workdir / f'{name}-{heap_mib}'
    directory.mkdir(parents=True)
    binary = directory / 'mayc'
    shutil.copy2(compiler, binary)
    shutil.copytree(runtime, directory / 'runtime')
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
                                                    directory / 'stdout.txt')
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
    options = parser.parse_args()
    if options.modes is None:
        # The large-tree probes need a heap of at least 64 MiB to collect more
        # than once; keep the defaults to the probes that fit the default heaps.
        options.modes = [] if (options.inventory or options.workload) else [
            'records', 'maps', 'lists', 'tree6']
    compiler = compiler_binary(options.compiler)
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
                                            name, heap_mib, extra, workdir)
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
                rows, usage = build_and_run(compiler, text, name, heap_mib, [], workdir)
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
    if options.json:
        Path(options.json).write_text(json.dumps(report, indent=2) + '\n')
        print(f'wrote {options.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
