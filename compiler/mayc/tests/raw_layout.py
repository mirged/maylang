#!/usr/bin/env python3
"""Measure RAW code-layout sensitivity (issue #83).

Each placement inserts a cold function of K four-byte statements before the
kernels of raw_performance.may. Functions start 8-byte aligned, so K in steps
of two moves every kernel by 8 bytes; 16 placements span 128 bytes. Every
compiler compiles every placement and all binaries run interleaved.

By default each binary runs all six kernels and the report uses their timers.
--cycles builds one binary per kernel and counts its user-mode core cycles
with `perf stat`, which is insensitive to frequency changes and to the other
kernels. The report records per-placement medians, loop-head addresses and
the spread of each kernel's medians across placements.

No performance threshold is enforced. Pass compilers as NAME=PATH, each copied
together with its runtime sidecars, and optional flags as NAME=PATH=FLAG.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import statistics
import tempfile

from backends import compiler_binary, compile_source
from raw_performance import CHECKSUMS, capture, digest, parse_output

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
KERNELS = {'PRNG': ('prng_bench', 'prng_bench()'), 'Collatz': ('collatz_bench', 'collatz_bench()'),
           'Byte histogram': ('histogram_bench', 'histogram_bench(work)'),
           'Cellular automaton': ('automaton_bench', 'automaton_bench(work)'),
           'Pointer chase': ('pointer_chase_bench', 'pointer_chase_bench(work)'),
           'Random walk': ('walk_bench', 'walk_bench()')}


def padded_source(source, statements, kernel=None):
    body = ''.join('    pad = pad + 1;\n' for _ in range(statements))
    pad = f'fun layout_pad(seed: Any) -> Any {{\n    mut pad: Any = seed;\n{body}    return pad;\n}}\n\n'
    anchor = 'let memory: Any = syscall('
    header = 'write_bytes(addr("------------------------------------------------\\n"), 49);\n'
    main = 'mut total_ns: Any = 0;\n'
    assert source.count(anchor) == 1 and header in source and source.count(main) == 1
    text = source.replace(anchor, pad + anchor).replace(header, header + '\nif memory == 0 { layout_pad(1); }\n', 1)
    if kernel is None:
        return text
    call = KERNELS[kernel][1]
    return text[:text.index(main)] + (
        f'let start: Any = now_ns(timespec);\nlet result: Any = {call};\n'
        f'report(addr("{kernel}"), {len(kernel)}, result, now_ns(timespec) - start, digits);\n'
        'syscall(11, memory, 1048576);\nexit(0);\n')


def layout(binary):
    """Code bytes, function addresses and backward-branch targets per kernel."""
    assembly = capture(['objdump', '-d', '--no-show-raw-insn', binary])
    functions, heads, current, first, last = {}, {}, None, None, 0
    for line in assembly.splitlines():
        symbol = re.match(r'([0-9a-f]+) <(?:module0::)?(\w+)>:', line)
        if symbol:
            current = symbol[2]
            functions[current] = int(symbol[1], 16)
            continue
        instruction = re.match(r'\s*([0-9a-f]+):\s+(\w+)\s+([0-9a-f]+)?', line)
        if not instruction:
            continue
        address = int(instruction[1], 16)
        first = address if first is None else first
        last = address
        if instruction[2].startswith('j') and instruction[3] and int(instruction[3], 16) <= address:
            heads.setdefault(current, []).append(int(instruction[3], 16))
    names = [name for name, _ in KERNELS.values() if name in functions]
    return {'code_span': last - first, 'functions': {name: functions[name] for name in names},
            'loop_heads': {name: heads.get(name, []) for name in names}}


def spread(medians):
    return {'min': min(medians), 'max': max(medians), 'range': max(medians) - min(medians),
            'relative_range': (max(medians) - min(medians)) / min(medians),
            'stdev': statistics.stdev(medians)}


def count_cycles(command, kernel, event, log):
    """One single-kernel run: its checked timer and the process's user cycles."""
    output = capture(['perf', 'stat', '--no-big-num', '-x', ',', '-e', event, '-o', log, '--', *command])
    match = re.search(r'^' + re.escape(kernel) + r'\s+(-?\d+)\s+(\d+)$', output, re.M)
    assert match and int(match[1]) == CHECKSUMS[kernel], output
    cycles = [int(line.split(',')[0]) for line in log.read_text().splitlines() if line.split(',')[0].strip().isdigit()]
    assert len(cycles) == 1, log.read_text()
    return {kernel: cycles[0], 'ns': int(match[2])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', action='append', required=True, help='NAME=PATH[=FLAG]')
    parser.add_argument('--placements', type=int, default=16)
    parser.add_argument('--step', type=int, default=2, help='statements added per placement')
    parser.add_argument('--runs', type=int, default=21)
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--cycles', action='store_true', help='one binary per kernel; count user cycles')
    parser.add_argument('--kernel', action='append', choices=KERNELS, help='with --cycles; default all six')
    parser.add_argument('--cpu', type=int, help='pin every measured binary to this logical CPU')
    parser.add_argument('--output', type=Path, help='JSON report')
    args = parser.parse_args()
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Linux x86-64 required'
    source = (HERE / 'backend/raw_performance.may').read_text()
    compilers = {}
    for spec in args.compiler:
        name, path, *flags = spec.split('=')
        compilers[name] = (compiler_binary(Path(path)), flags)
    kernels = (args.kernel or list(KERNELS)) if args.cycles else [None]
    hybrid = Path('/sys/bus/event_source/devices/cpu_core').exists()
    event = ('cpu_core/cycles/u' if hybrid else 'cycles:u') if args.cycles else None
    counts = [index * args.step for index in range(args.placements)]
    with tempfile.TemporaryDirectory(prefix='mayc-raw-layout-') as directory:
        work = Path(directory)
        binaries, layouts = {}, {}
        for statements in counts:
            for kernel in kernels:
                path = work / f'pad{statements}-{kernel or "all"}.may'.replace(' ', '_')
                path.write_text(padded_source(source, statements, kernel))
                for name, (compiler, flags) in compilers.items():
                    key = (name, statements, kernel)
                    binaries[key] = path.with_name(f'{name}-{path.stem}')
                    compile_source(compiler, path, binaries[key], '--raw', *flags)
                    layouts[key] = layout(binaries[key])
        prefix = ['taskset', '-c', str(args.cpu)] if args.cpu is not None else []
        samples = {key: [] for key in binaries}
        keys = list(binaries)
        for iteration in range(args.warmup + args.runs):
            # Rotate execution order to distribute drift between binaries.
            offset = iteration * 7 % len(keys)
            for key in keys[offset:] + keys[:offset]:
                if event is None:
                    row = {label: row['ns'] for label, row in parse_output(capture(prefix + [binaries[key]])).items()}
                else:
                    row = count_cycles(prefix + [binaries[key]], key[2], event, work / 'perf.csv')
                if iteration >= args.warmup:
                    samples[key].append(row)
        unit = 'cycles' if event else 'ns'
        labels = (args.kernel or list(KERNELS)) if args.cycles else list(CHECKSUMS) + ['Suite']
        results = {}
        for name in compilers:
            placements = []
            for statements in counts:
                entry = {'statements': statements, 'layout': {}, f'median_{unit}': {}, f'samples_{unit}': {}}
                for kernel in kernels:
                    key = (name, statements, kernel)
                    entry['layout'][kernel or 'all'] = layouts[key]
                    for label in ([kernel] if kernel else list(CHECKSUMS)):
                        values = [sample[label] for sample in samples[key]]
                        entry[f'samples_{unit}'][label] = values
                        entry[f'median_{unit}'][label] = statistics.median(values)
                    if kernel is None:
                        entry[f'median_{unit}']['Suite'] = statistics.median(sum(s.values()) for s in samples[key])
                    else:
                        entry.setdefault('median_ns', {})[kernel] = statistics.median(s['ns'] for s in samples[key])
                placements.append(entry)
            results[name] = {'flags': compilers[name][1], 'sha256': digest(compilers[name][0]),
                             'version': capture([compilers[name][0], '--version']), 'placements': placements,
                             f'spread_{unit}': {label: spread([p[f'median_{unit}'][label] for p in placements])
                                                for label in labels}}
            summary = ', '.join(f"{label} {100 * results[name][f'spread_{unit}'][label]['relative_range']:.1f}%"
                                for label in labels)
            print(f'{name}: {unit} spread across placements: {summary}', flush=True)
        if args.output:
            report = {'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      'revision': capture(['git', 'rev-parse', 'HEAD']), 'status': capture(['git', 'status', '--short']),
                      'uname': capture(['uname', '-a']), 'lscpu': capture(['lscpu']), 'cpu': args.cpu,
                      'allowed_cpus': sorted(os.sched_getaffinity(0)), 'runs': args.runs, 'warmup': args.warmup,
                      'mode': unit, 'event': event, 'statement_counts': counts, 'checksums': CHECKSUMS,
                      'results': results,
                      'notes': 'Host is not isolated; no timing thresholds. Placement K inserts K four-byte '
                               'statements in a cold function before every kernel. Cycle counts cover the '
                               'whole single-kernel process, including startup and output.'}
            args.output.resolve().write_text(json.dumps(report, indent=2) + '\n')
            print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
