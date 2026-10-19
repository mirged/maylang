#!/usr/bin/env python3
"""Retain GC limit experiments, codegen, resource usage and checksum timings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import statistics
import subprocess
import time
import traceback

from backends import ROOT, compiler_binary
from gc_stress import INVARIANTS

HERE = Path(__file__).resolve().parent / 'limits'
METER = r'''
mut LIMIT_ALLOCS: Any = 0;
mut LIMIT_REQUESTED: Any = 0;
mut LIMIT_HIGH: Any = 0;
mut LIMIT_GC_NS: Any = 0;
mut LIMIT_MARK_HIGH: Any = 0;
mut LIMIT_CLOCK: Any = 0;
mut LIMIT_BUFFER: Any = 0;
fun limits_now() -> Any {
    if (LIMIT_CLOCK == 0) { LIMIT_CLOCK = syscall(9, 0, 4096, 3, 34, -1, 0); }
    syscall(228, 1, LIMIT_CLOCK);
    return load64(LIMIT_CLOCK) * 1000000000 + load64(LIMIT_CLOCK + 8);
}
fun limits_metric(name: Any, value: Any) -> Any {
    if (LIMIT_BUFFER == 0) { LIMIT_BUFFER = syscall(9, 0, 4096, 3, 34, -1, 0); }
    rt_write(addr("LIMIT "), 6);
    mut length: Any = 0;
    while (load8(name + length) != 0) { length += 1; }
    rt_write(name, length); rt_write(addr(" "), 1);
    mut number: Any = value;
    if (number < 0) { rt_write(addr("-"), 1); number = 0 - number; }
    mut digits: Any = 0;
    if (number == 0) { store8(LIMIT_BUFFER, 48); digits = 1; }
    while (number > 0) {
        store8(LIMIT_BUFFER + digits, 48 + number % 10); number = number / 10; digits += 1;
    }
    while (digits > 0) { digits -= 1; rt_write(LIMIT_BUFFER + digits, 1); }
    rt_write(addr("\n"), 1); return 0;
}
fun limits_report() -> Any {
    mut pointer: Any = HEAP; mut free_bytes: Any = HEAPEND - HP;
    mut largest_free: Any = HEAPEND - HP;
    while (pointer < HP) {
        let size: Any = load64(pointer) - load64(pointer) % 2;
        if (size < 16 or size % 8 != 0 or pointer + size > HP) { break; }
        if (load8(GCSTARTS + (pointer - HEAP) / 8) == 0) {
            free_bytes += size; if (size > largest_free) { largest_free = size; }
        }
        pointer += size;
    }
    limits_metric("heap_bytes", HEAPEND - HEAP);
    limits_metric("allocations", LIMIT_ALLOCS);
    limits_metric("requested_bytes", LIMIT_REQUESTED);
    limits_metric("heap_high_water_bytes", LIMIT_HIGH);
    limits_metric("heap_extent_bytes", HP - HEAP);
    limits_metric("free_bytes", free_bytes);
    limits_metric("largest_free_bytes", largest_free);
    limits_metric("collections", GCCOUNT);
    limits_metric("gc_ns", LIMIT_GC_NS);
    limits_metric("mark_peak_slots", LIMIT_MARK_HIGH);
    limits_metric("root_slots", GCOUNT); return 0;
}
'''


def instrument_runtime(heap_mib, mark_slots=None):
    text = (ROOT / 'compiler/mayc/runtime.may').read_text()
    replacements = {
        'mut sz: Any = 268435456;': f'mut sz: Any = {heap_mib * 1024**2};',
        'fun rt_alloc(n: Any) -> Any {': 'fun rt_alloc(n: Any) -> Any {\n    LIMIT_ALLOCS += 1; LIMIT_REQUESTED += n;',
        '    HP = HP + need;': '    HP = HP + need;\n    if (HP - HEAP > LIMIT_HIGH) { LIMIT_HIGH = HP - HEAP; }',
        '    MARKN = MARKN + 1;': '    MARKN = MARKN + 1;\n    if (MARKN > LIMIT_MARK_HIGH) { LIMIT_MARK_HIGH = MARKN; }',
        '    if (GCFLAG == 0) { return 0; }': '    if (GCFLAG == 0) { return 0; }\n    let limits_started: Any = limits_now();',
        '    GCCOUNT = GCCOUNT + 1;': '    GCCOUNT = GCCOUNT + 1;\n    LIMIT_GC_NS += limits_now() - limits_started;',
        'rt_write(addr("out of memory\\n"), 14);': 'limits_report(); rt_write(addr("out of memory\\n"), 14);',
        'rt_write(addr("GC mark stack exhausted\\n"), 24);': 'limits_report(); rt_write(addr("GC mark stack exhausted\\n"), 24);',
        'rt_write(addr("GC global root table exhausted\\n"), 31);': 'limits_report(); rt_write(addr("GC global root table exhausted\\n"), 31);',
        'fun rt_newline() -> Any {\n    rt_write(addr("\\n"), 1);':
            'fun rt_newline() -> Any {\n    rt_write(addr("\\n"), 1); limits_report();',
    }
    if mark_slots is not None:
        replacements['    MARKMAX = 1048576;'] = f'    MARKMAX = {mark_slots};'
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError(f'runtime instrumentation anchor changed: {old!r}')
        text = text.replace(old, new, 1)
    return text + METER


def execute(command, directory, label, args, *, environment=None, timeout=None):
    """Per-child wait4 usage; kill the process group on timeout, retain all logs."""
    directory.mkdir(parents=True, exist_ok=True)
    stdout = directory / (label + '.stdout')
    stderr = directory / (label + '.stderr')
    seconds = timeout or args.timeout

    def restrict():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (args.memory_mib * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(seconds) + 1, math.ceil(seconds) + 2))
        if args.cpu is not None:
            os.sched_setaffinity(0, {args.cpu})

    start = time.perf_counter_ns()
    timed_out = False
    with stdout.open('wb') as out, stderr.open('wb') as err:
        child = subprocess.Popen(list(map(str, command)), cwd=ROOT, env=environment,
                                 stdout=out, stderr=err, start_new_session=True, preexec_fn=restrict)
        try:
            while True:
                pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    break
                if (time.perf_counter_ns() - start) / 1e9 >= seconds:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(child.pid, 0)
                    break
                time.sleep(.002)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            raise
        child.returncode = os.waitstatus_to_exitcode(status)
    result = {'command': list(map(str, command)), 'exit': child.returncode,
              'category': 'timeout' if timed_out else 'signal' if child.returncode < 0 else 'exited',
              'wall_ms': (time.perf_counter_ns() - start) / 1e6,
              'user_ms': usage.ru_utime * 1000, 'system_ms': usage.ru_stime * 1000,
              'peak_rss_kib': usage.ru_maxrss, 'stdout': str(stdout), 'stderr': str(stderr)}
    (directory / (label + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


def output(result):
    return Path(result['stdout']).read_text(errors='replace')


def require_run(result, expected=None):
    if result['exit'] != 0 or result['category'] != 'exited' or Path(result['stderr']).stat().st_size:
        raise ValueError(f'workload failed; see {result["stderr"]}: {result["category"]}, exit {result["exit"]}')
    if expected is not None and output(result) != str(expected) + '\n':
        raise ValueError(f'checksum mismatch: expected {expected}, got {output(result)!r}')


# Float text conversion lives in the tagged runtime/math.may, which raw
# programs cannot load; the GC workloads never reach it.
RAW_MATH_STUBS = '''
fun __math_parse(text: Any) -> Any { return 0; }
fun __math_format(value: Any) -> Any { return 0; }
'''


def snapshot(original, destination, runtime=None):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, destination / 'mayc')
    source = original.parent
    # A baseline keeps its own sidecars. Never mix a historical runtime with the current one.
    for name in ('native.may', 'prelude.may', 'runtime.may'):
        candidate = source / name
        if not candidate.is_file():
            raise ValueError(f'missing compiler sidecar: {candidate}')
        shutil.copy2(candidate, destination / name)
    shutil.copytree(source / 'runtime', destination / 'runtime', dirs_exist_ok=True)
    if runtime is not None:
        (destination / 'runtime.may').write_text(runtime)
    hashes = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination / 'identity.json').write_text(json.dumps(hashes, indent=2) + '\n')
    return destination / 'mayc'


def inspect_code(binary, directory, args):
    data = {}
    for name, command in [('disassembly', ['objdump', '-d', '-Mintel', '--no-show-raw-insn', binary]),
                          ('symbols', ['readelf', '--wide', '--symbols', binary]),
                          ('sections', ['readelf', '--wide', '--sections', binary])]:
        result = execute(command, directory, name, args)
        if result['exit'] != 0:
            raise ValueError(f'cannot inspect {binary}; see {result["stderr"]}')
        data[name] = output(result)
    functions = {}
    current = None
    names = {}
    ir = directory / 'program.ll'
    if ir.exists():
        names = dict(re.findall(r'^; may-function @(f\d+) (.+)$', ir.read_text(), re.M))
    for line in data['disassembly'].splitlines():
        match = re.match(r'^([0-9a-f]+) <(.+)>:', line)
        if match:
            current = f'{match[2]}::{names[match[2]]}' if match[2] in names else match[2]
            functions[current] = {'address': int(match[1], 16), 'instructions': 0, 'calls': 0,
                                  'divisions': 0, 'stack_references': 0, 'backward_branches': 0}
        instruction = re.match(r'^\s*([0-9a-f]+):\s+(\S+)\s*(.*)', line)
        if current is None or not instruction:
            continue
        row = functions[current]
        mnemonic, operands = instruction.group(2, 3)
        row['instructions'] += 1
        row['calls'] += mnemonic.startswith('call')
        row['divisions'] += mnemonic in ('idiv', 'div')
        row['stack_references'] += '[rbp' in operands or '[rsp' in operands
        branch = re.match(r'([0-9a-f]+)\s*<', operands)
        row['backward_branches'] += bool(mnemonic.startswith('j') and branch and
                                         int(branch[1], 16) < int(instruction[1], 16))
    text = re.search(r'\]\s+\.text\s+PROGBITS\s+\S+\s+\S+\s+([0-9a-fA-F]+)', data['sections'])
    (directory / 'functions.json').write_text(json.dumps(functions, indent=2) + '\n')
    blocks = re.split(r'(?m)^(\w+ <.+>:\n)', data['disassembly'])
    hot = ''.join(header + body for header, body in zip(blocks[1::2], blocks[2::2])
                  if 'probe_' in header or any('probe_' in source_name and f'<{symbol}>:' in header for symbol, source_name in names.items()))
    (directory / 'hot-functions.asm').write_text(hot)
    # Exact ELF symbol sizes are currently zero. Counts refer to objdump symbol
    # intervals, which can include the following function's unlabeled trampoline.
    return {'image_bytes': binary.stat().st_size, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'text_bytes': int(text[1], 16) if text else None,
            'functions': {name: row for name, row in functions.items() if 'probe_' in name},
            'retained_function_symbols': len(functions), 'disassembly': str(directory / 'disassembly.stdout')}


def trunc_div(a, b):
    return (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)


def periodic_total(iterations, period, function):
    cycles, remainder = divmod(iterations, period)
    total, prefix = 0, 0
    for index in range(min(period, iterations)):
        total += function(index)
        if index + 1 == remainder:
            prefix = total
    return total if iterations < period else total * cycles + prefix


def oracle(case, iterations, seed, functions):
    result, value = 0, seed
    if case == 'pressure':
        return None
    if case == 'graph':
        return periodic_total(iterations, 1024, lambda i: (i + seed) % 1024 + functions)
    if case == 'calls':
        return periodic_total(iterations, 1024, lambda i: 36 * ((i + seed) % 1024) + 168)
    if case == 'collections':
        return periodic_total(iterations, 1024, lambda i: 2 * ((i + seed) % 1024) + 10) + periodic_total(iterations, 17, lambda i: i)
    if case == 'contracts':
        return periodic_total(iterations, 8, lambda i: (1, 3, 7, 15, 31, 63, 127, 255)[i])
    period = 1048576
    cycles, remainder = divmod(iterations, period)
    prefix = 0
    for index in range(min(iterations, period)):
        value = (value * 17 + 23) % period
        if case == 'arithmetic':
            signed = value - 524288
            quotient = trunc_div(signed, 8)
            result += quotient + signed - quotient * 8
        elif case == 'branches':
            result += ((value // 16 if value % 16 < 8 else -(value // 16))
                       if value % 2 == 0 else (3 if value % 7 < 3 else -5))
        if index + 1 == remainder:
            prefix = result
    if iterations >= period and value != seed:
        raise ValueError('LCG oracle did not complete its expected period')
    return result if iterations < period else cycles * result + prefix


def generated_source(case, args):
    if case == 'pressure':
        names = [f'a{i}: Int' for i in range(args.pressure)]
        terms = [f'{i + 1} * a{i}' for i in range(args.pressure)]
        values = [f'probe_identity(value + {i})' for i in range(args.pressure)]
        return ('fun probe_identity(n: Int) -> Int { return n * 3 + 1; }\n'
                f'fun probe_join({", ".join(names)}) -> Int {{ return {" + ".join(terms)}; }}\n'
                'fun probe_pressure(iterations: Int, seed: Int) -> Int {\n'
                'mut total: Int = 0; mut i: Int = 0; while i < iterations {\n'
                'let value: Int = (i + seed) % 1024;\n'
                f'total += probe_join({", ".join(values)}); i += 1; }} return total; }}\n'
                'let argv: List<Str> = args(); print(probe_pressure(int(argv[1]), int(argv[2])));\n')
    text = []
    for index in range(args.functions):
        body = 'return n;' if index == args.functions - 1 else f'return generated_{index + 1}(n) + 1;'
        text.append(f'fun generated_{index}(n: Int) -> Int {{ {body} }}')
        text.append(f'fun unused_{index}() -> Str {{ return "GC_CODEGEN_UNREACHABLE_{index}"; }}')
    text += ['fun probe_graph(iterations: Int, seed: Int) -> Int {',
             'mut total: Int = 0; mut i: Int = 0; while i < iterations {',
             'total += generated_0((i + seed) % 1024); i += 1; } return total; }',
             'let argv: List<Str> = args(); print(probe_graph(int(argv[1]), int(argv[2])));']
    return '\n'.join(text)


def run_codegen(args, report, compiler):
    home = args.output / 'codegen'
    compilers = {'current': snapshot(compiler, home / 'current-toolchain')}
    if args.baseline:
        compilers = {'baseline': snapshot(compiler_binary(args.baseline), home / 'baseline-toolchain'), **compilers}
    cases = args.case or ['arithmetic', 'branches', 'calls', 'pressure', 'collections', 'contracts', 'graph']
    for case in cases:
        directory = home / case
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / (case + '.may')
        source.write_text(generated_source(case, args) if case in ('pressure', 'graph') else (HERE / (case + '.may')).read_text())
        iterations = min(args.iterations, 1000) if case == 'graph' else min(args.iterations, 30000) if case == 'collections' else args.iterations
        expected = oracle(case, iterations, args.seed, args.functions - 1)
        if case == 'pressure':
            weights = sum(range(1, args.pressure + 1))
            constant = sum((j + 1) * (3 * j + 1) for j in range(args.pressure))
            expected = periodic_total(iterations, 1024, lambda i: 3 * ((i + args.seed) % 1024) * weights + constant)
        case_report = {'case': case, 'iterations': iterations, 'seed': args.seed, 'expected': expected, 'variants': {}}
        report['codegen'].append(case_report)
        binaries = []
        for name, selected in compilers.items():
            for backend in args.backend:
                label = name + '-' + backend
                variant = directory / label
                variant.mkdir(exist_ok=True)
                binary = variant / 'program'
                ir = variant / 'program.ll'
                compile_result = execute([selected, '--time', '--target', 'x86_64-linux' if backend == 'native' else 'clang-llvm',
                                          *(['--emit-llvm'] if backend == 'llvm-o3' else []),
                                          source, '-o', ir if backend == 'llvm-o3' else binary], variant, 'compile', args, timeout=args.compile_timeout)
                if compile_result['exit'] != 0:
                    case_report['variants'][label] = {'compile': compile_result, 'passed': False}
                    raise ValueError(f'compilation failed: {compile_result["stderr"]}')
                if backend == 'llvm':
                    emitted = execute([selected, '--target', 'clang-llvm', '--emit-llvm', source, '-o', ir],
                                      variant, 'llvm-ir', args, timeout=args.compile_timeout)
                    if emitted['exit'] != 0:
                        raise ValueError(f'IR emission failed: {emitted["stderr"]}')
                linked = None
                if backend == 'llvm-o3':
                    linked = execute([os.environ.get('CLANG', 'clang'), '-x', 'ir', '-O3', ir, '-no-pie', '-lm', '-o', binary],
                                     variant, 'clang-o3', args, timeout=args.compile_timeout)
                    if linked['exit'] != 0:
                        raise ValueError(f'Clang -O3 failed: {linked["stderr"]}')
                    optimized = execute([os.environ.get('CLANG', 'clang'), '-x', 'ir', '-O3', '-S', '-emit-llvm',
                                         ir, '-o', variant / 'program.optimized.ll'],
                                        variant, 'optimized-ir', args, timeout=args.compile_timeout)
                    if optimized['exit'] != 0:
                        raise ValueError(f'optimized IR emission failed: {optimized["stderr"]}')
                if b'GC_CODEGEN_UNREACHABLE_' in binary.read_bytes():
                    raise ValueError(f'unreachable literals survived in {binary}')
                details = inspect_code(binary, variant, args)
                if case == 'graph' and backend == 'native':
                    symbols = json.loads((variant / 'functions.json').read_text())
                    retained = {int(match[1]) for symbol in symbols
                                if (match := re.search(r'(?:^|::)generated_(\d+)$', symbol))}
                    if retained != set(range(args.functions)) or any(re.search(r'(?:^|::)unused_\d+$', symbol) for symbol in symbols):
                        raise ValueError(f'graph symbol table is incomplete or retains dead functions: {variant}')
                    details['verified_graph_symbols'] = len(retained)
                if linked is not None:
                    details['clang_o3'] = linked
                    details['optimized_ir'] = optimized
                result = execute([binary, iterations, args.seed], variant, 'warmup', args)
                require_run(result, expected)
                details.update({'compile': compile_result, 'samples': [], 'passed': False})
                case_report['variants'][label] = details
                binaries.append((label, binary, variant))
        # Interleave versions/backends; reverse order every round to reduce order bias.
        for index in range(args.samples):
            for label, binary, variant in binaries[::1 if index % 2 == 0 else -1]:
                result = execute([binary, iterations, args.seed], variant, f'run-{index}', args)
                require_run(result, expected)
                case_report['variants'][label]['samples'].append(result)
        for label, row in case_report['variants'].items():
            row['median_wall_ms'] = statistics.median(s['wall_ms'] for s in row['samples'])
            row['passed'] = True
            print(f'PASS {case} {label}: {row["median_wall_ms"]:.3f} ms; .text {row["text_bytes"]} bytes', flush=True)
        report['passed'] += 1
        write_report(args, report)


def run_gc(args, report, compiler):
    home = args.output / 'gc'
    for heap in args.heap_mib:
        runtime = instrument_runtime(heap)
        selected = snapshot(compiler, home / f'heap-{heap}/toolchain', runtime)
        cases = [('gc_churn', seed, args.rounds, 0, None) for seed in args.seeds]
        cases += [('gc_fragmentation', args.seed, max(2, args.rounds // 8), 0, None),
                  ('gc_capacity', args.seed, 0, 70, 'out of memory\n'),
                  ('gc_objects', args.seed, max(args.rounds, heap * 8), 0, None)]
        if heap == args.heap_mib[0]:
            cases += [('gc_mark_capacity', args.seed, 0, 70, 'GC mark stack exhausted\n'),
                      ('gc_root_capacity', args.seed, 0, 70, 'GC global root table exhausted\n')]
            if args.self_test:
                cases.append(('injected_corruption', args.seed, 8, 35, None))
        for case, seed, rounds, expected_exit, message in cases:
            if args.gc_case and case not in args.gc_case:
                continue
            directory = home / f'heap-{heap}' / f'{case}-seed-{seed}'
            directory.mkdir(parents=True, exist_ok=True)
            body = (HERE / (('gc_churn' if case == 'injected_corruption' else case) + '.may')).read_text()
            if case == 'injected_corruption':
                body = body.replace('store64(node + 16, round * 17 + LIMIT_SEED);', 'store64(node + 16, -999);')
            custom = instrument_runtime(heap, args.mark_slots) if case == 'gc_mark_capacity' else runtime
            constants = f'let LIMIT_ROUNDS: Any = {rounds}; let LIMIT_SEED: Any = {seed}; let LIMIT_MARK_SLOTS: Any = {args.mark_slots};\n'
            source = directory / (case + '.may')
            source.write_text(body if case == 'gc_objects' else custom + RAW_MATH_STUBS + INVARIANTS + constants + body)
            compile_result = execute([selected, *([] if case == 'gc_objects' else ['--raw', '--legacy']), source, '-o', directory / 'program'],
                                     directory, 'compile', args, timeout=args.compile_timeout)
            row = {'case': case, 'heap_mib': heap, 'seed': seed, 'rounds': rounds, 'compile': compile_result, 'passed': False}
            report['gc'].append(row)
            if compile_result['exit'] != 0:
                raise ValueError(f'GC compile failed: {compile_result["stderr"]}')
            result = execute([directory / 'program', rounds, seed], directory, 'run', args)
            row['run'] = result
            text = output(result)
            metrics = {name: int(value) for name, value in re.findall(r'^LIMIT (\w+) (-?\d+)$', text, re.M)}
            row['metrics'] = metrics
            passed = result['category'] == 'exited' and result['exit'] == expected_exit and not Path(result['stderr']).stat().st_size
            if message:
                passed = passed and text.endswith(message)
                row['expected_limit'] = message.strip()
            if expected_exit == 0:
                passed = passed and metrics.get('heap_bytes') == heap * 1024**2 and metrics.get('collections', 0) > 0
                expected_checksum = (17 * rounds * (rounds - 1) // 2 + seed * rounds
                                     if case == 'gc_churn' else rounds * 64 if case == 'gc_fragmentation' else None)
                if expected_checksum is not None:
                    passed = passed and metrics.get('checksum') == expected_checksum
                else:
                    passed = passed and 'PASS retained objects' in text
            if expected_exit == 70:
                passed = passed and metrics.get('heap_bytes') == heap * 1024**2
                if case == 'gc_root_capacity':
                    passed = passed and metrics.get('root_slots') == 131072
                if case == 'gc_mark_capacity':
                    passed = passed and metrics.get('mark_peak_slots') == args.mark_slots
            row['passed'] = bool(passed)
            row['category'] = 'expected-capacity' if passed and expected_exit == 70 else 'detector-self-test' if passed and expected_exit == 35 else 'passed' if passed else 'failure'
            write_report(args, report)
            if not passed:
                raise ValueError(f'GC failure: {case}, exit {result["exit"]}, {result["category"]}; artifacts: {directory}')
            report['passed'] += 1
            print(f'PASS {case} heap={heap} MiB seed={seed}: {row["category"]}, {metrics.get("collections", 0)} collections', flush=True)
            write_report(args, report)


def write_report(args, report):
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# GC and codegen experiment', '', f'Artifacts: `{args.output}`', '',
             'Whole-process medians include startup. Compilation is measured separately. GC runs use test-only instrumentation.', '',
             '| Workload | Variant | Median ms | .text bytes | Peak RSS KiB |',
             '| --- | --- | ---: | ---: | ---: |']
    for case in report['codegen']:
        for label, row in case['variants'].items():
            if 'median_wall_ms' in row:
                lines.append(f'| {case["case"]} | {label} | {row["median_wall_ms"]:.3f} | {row["text_bytes"]} | '
                             f'{max(r["peak_rss_kib"] for r in row["samples"])} |')
    lines += ['', '| GC case | Heap MiB | Seed | Result | Collections | Requested MiB | GC ms |',
              '| --- | ---: | ---: | --- | ---: | ---: | ---: |']
    for row in report['gc']:
        metric = row.get('metrics', {})
        lines.append(f'| {row["case"]} | {row["heap_mib"]} | {row["seed"]} | {row.get("category", "incomplete")} | '
                     f'{metric.get("collections", 0)} | {metric.get("requested_bytes", 0) / 1024**2:.2f} | '
                     f'{metric.get("gc_ns", 0) / 1e6:.3f} |')
    lines += ['', 'Each case retains source, executable, logs, commands, and resource usage. Codegen variants also retain',
              '`disassembly.stdout`, `hot-functions.asm`, `functions.json`, symbol/section tables and optional LLVM IR.',
              'ELF function sizes are zero: instruction statistics use symbol intervals and may include a neighboring trampoline.', '']
    if report.get('error'):
        lines += ['Failure: ' + report['error'], '']
    (args.output / 'REPORT.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--baseline', type=Path, help='baseline compiler with its own matching sidecars')
    parser.add_argument('--mode', choices=['all', 'gc', 'codegen'], default='all')
    parser.add_argument('--output', type=Path, default=ROOT / 'compiler/mayc/build/limits' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    parser.add_argument('--backend', choices=['native', 'llvm', 'llvm-o3'], nargs='+', default=['native'])
    parser.add_argument('--case', choices=['arithmetic', 'branches', 'calls', 'pressure', 'collections', 'contracts', 'graph'], action='append')
    parser.add_argument('--gc-case', choices=['gc_churn', 'gc_fragmentation', 'gc_capacity', 'gc_objects', 'gc_mark_capacity', 'gc_root_capacity', 'injected_corruption'], action='append')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--iterations', type=int, default=200000)
    parser.add_argument('--pressure', type=int, default=16)
    parser.add_argument('--functions', type=int, default=128)
    parser.add_argument('--heap-mib', type=int, nargs='+', default=[4, 8])
    parser.add_argument('--rounds', type=int, default=64)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 42])
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--mark-slots', type=int, default=64, help='test-only reduced mark frontier for deterministic exhaustion')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--compile-timeout', type=float, default=180)
    parser.add_argument('--memory-mib', type=int, default=2048)
    parser.add_argument('--cpu', type=int, help='pin each child to an allowed Linux CPU')
    args = parser.parse_args()
    if args.gc_case and 'injected_corruption' in args.gc_case:
        args.self_test = True
    for key in ('samples', 'iterations', 'pressure', 'functions', 'rounds', 'mark_slots', 'timeout', 'compile_timeout'):
        if getattr(args, key) <= 0:
            parser.error(f'--{key.replace("_", "-")} must be positive')
    if min(args.heap_mib) < 4 or max(args.heap_mib) > 1024 or args.memory_mib < max(args.heap_mib) * 2:
        parser.error('heap sizes must be 4..1024 MiB and memory limit at least twice the largest heap')
    if args.mark_slots > 1048576 or args.pressure > 256 or args.functions > 4096:
        parser.error('mark slots <= 1048576, pressure <= 256, functions <= 4096')
    if min([args.seed, *args.seeds]) < 0 or max([args.seed, *args.seeds]) > 1000000:
        parser.error('seeds must be 0..1000000')
    if args.cpu is not None and args.cpu not in os.sched_getaffinity(0):
        parser.error('--cpu must be in this process\'s allowed affinity mask')
    args.output = args.output.resolve()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('--output must be empty so previous evidence is preserved')
    args.output.mkdir(parents=True, exist_ok=True)
    compiler = compiler_binary(args.compiler)
    report = {'schema': 1, 'host': platform.platform(), 'cpu': args.cpu,
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
              'configuration': {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
              'timing': 'whole process; compilation separate; one warmup; interleaved samples; child wait4 RSS/CPU usage',
              'gc': [], 'codegen': [], 'passed': 0, 'complete': False}
    report['allowed_cpus'] = sorted(os.sched_getaffinity(0))
    report['cpu_model'] = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                                if line.startswith('model name')), 'unknown')
    for tool in ('objdump', 'readelf', 'clang'):
        if shutil.which(tool):
            report[tool + '_version'] = subprocess.check_output([tool, '--version'], text=True).splitlines()[0]
    write_report(args, report)
    try:
        if args.mode in ('all', 'codegen'):
            run_codegen(args, report, compiler)
        if args.mode in ('all', 'gc'):
            run_gc(args, report, compiler)
        report['complete'] = True
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
        print(f'FAIL {error}', flush=True)
    write_report(args, report)
    print(f'Artifacts: {args.output}', flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
