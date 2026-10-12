#!/usr/bin/env python3
"""Seeded live-graph oracle and heap/free-bin invariants in a reduced heap."""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
INVARIANTS = r'''
fun stress_node(ledger: Any, index: Any, value: Any, first: Any, second: Any) -> Any {
    let node: Any = load64(ledger + index * 8);
    stress_assert(rt_candidate(node) == node and load64(node) == index and load64(node + 8) == value, 33);
    stress_assert(load64(node + 40) == 32 and load64(node + 48) == 5124095576638253 and rt_candidate(node + 56) == 0, 34);
    let copy: Any = load64(node + 32) / 8;
    stress_assert(load8(copy) == 112 and load8(copy + 12) == 187 and load8(copy + 13) == 0, 35);
    if (first >= 0) { stress_assert(load64(node + 16) == load64(ledger + first * 8), 36); }
    if (second >= 0) { stress_assert(load64(node + 24) == load64(ledger + second * 8), 36); }
    return 0;
}
fun stress_assert(condition: Any, code: Any) -> Any {
    if (condition == 0) { syscall(60, code); }
    return 0;
}
fun stress_heap_check() -> Any {
    mut pointer: Any = HEAP; mut free: Any = 0; mut previousFree: Any = 0;
    while (pointer < HP) {
        let size: Any = load64(pointer);
        stress_assert(size >= 16 and size % 8 == 0 and pointer + size <= HP, 20);
        let live: Any = load8(GCSTARTS + (pointer - HEAP) / 8);
        if (live == 1) {
            stress_assert(load64(pointer + 8) == 5124095576638253, 21);
            previousFree = 0;
        } else { stress_assert(live == 0 and previousFree == 0, 22); previousFree = 1; free += 1; }
        mut interior: Any = pointer + 8;
        while (interior < pointer + size) {
            stress_assert(load8(GCSTARTS + (interior - HEAP) / 8) == 0, 23); interior += 8;
        }
        pointer += size;
    }
    stress_assert(pointer == HP and HP <= HEAPEND and free == FREECOUNT, 24);
    mut chained: Any = 0; mut lowest: Any = 257; mut bin: Any = 0;
    while (bin < 257) {
        mut block: Any = load64(FREEBINS + bin * 8);
        if (block != 0 and lowest == 257) { lowest = bin; }
        while (block != 0) {
            stress_assert(block >= HEAP and block + 16 <= HP and block % 8 == 0, 25);
            stress_assert(load8(GCSTARTS + (block - HEAP) / 8) == 0 and load64(block) == bin * 8, 26);
            chained += 1; stress_assert(chained <= free, 27); block = load64(block + 8);
        }
        bin += 1;
    }
    stress_assert(lowest == FREEBIN_LOW, 28);
    mut block: Any = FREELIST;
    while (block != 0) {
        stress_assert(block >= HEAP and block + 16 <= HP and block % 8 == 0, 29);
        stress_assert(load8(GCSTARTS + (block - HEAP) / 8) == 0 and load64(block) > 2048, 30);
        chained += 1; stress_assert(chained <= free, 31); block = load64(block + 8);
    }
    stress_assert(chained == free, 32);
    return 0;
}
'''


def program(seed, steps):
    rng = random.Random(seed)
    nodes = {}
    roots = []
    output = ['fun stress_main() -> Any {', 'STACKTOP = __sp(); rt_init();',
              f'let ledger: Any = syscall(9, 0, {(steps + 16) * 8}, 3, 34, -1, 0);',
              'let roots: Any = syscall(9, 0, 4096, 3, 34, -1, 0);',
              'let zeros: Any = syscall(9, 0, 135168, 3, 34, -1, 0);',
              'mut slot: Any = 0; while (slot < 8) { rt_gc_root(roots + slot * 8); slot += 1; }']

    def reachable():
        found, pending = set(), list(roots)
        while pending:
            index = pending.pop()
            if index not in found:
                found.add(index)
                pending.extend(nodes[index]['edges'])
        return sorted(found)

    # Bound each IR body; the independent oracle remains Python-generated.
    functions = []
    main = output
    for step in range(steps):
        main.append(f'stress_step_{step}(ledger, roots, zeros);')
        output = [f'fun stress_step_{step}(ledger: Any, roots: Any, zeros: Any) -> Any {{']
        index = len(nodes)
        live = reachable()
        edges = [rng.choice(live) for _ in range(2)] if live else []
        value = rng.randrange(1, 1 << 28)
        nodes[index] = {'value': value, 'edges': edges}
        output += ['{', 'let node: Any = rt_alloc(80); rt_copy(node, zeros, 80);', f'store64(node, {index}); store64(node + 8, {value});',
                   f'store64(ledger + {index * 8}, node);']
        for field, child in enumerate(edges):
            output.append(f'store64(node + {16 + field * 8}, load64(ledger + {child * 8}));')
        # An encoded cstr address is the only reference to this independent copy.
        output += ['store64(node + 32, rt_cstr(rt_from(addr("persistent λ"), 13)));',
                   'store64(node + 40, 32); store64(node + 48, 5124095576638253);']
        if len(roots) < 8:
            root_slot = len(roots)
            roots.append(index)
        else:
            root_slot = rng.randrange(8)
            roots[root_slot] = index
        output += [f'store64(roots + {root_slot * 8}, node);', '}']
        if step % 3 == 0 and live:
            changed = rng.choice(reachable())
            child = rng.choice(reachable())
            nodes[changed]['edges'] = [child] + nodes[changed]['edges'][1:]
            output.append(f'store64(load64(ledger + {changed * 8}) + 16, load64(ledger + {child * 8}));')
        # Clear raw garbage so old allocator links cannot retain unrelated
        # allocations through the runtime's intentionally conservative scan.
        output += ['{ mut garbage: Any = 0;', 'while (garbage < 12) { let size: Any = 131072 + garbage * 32; let discarded: Any = rt_alloc(size); rt_copy(discarded, zeros, size); garbage += 1; }', '}']
        if step % 7 == 0 or step == steps - 1:
            output += ['rt_gc(); stress_heap_check();']
            for live_id in reachable():
                model = nodes[live_id]
                edges = model['edges'] + [-1, -1]
                output.append(f'stress_node(ledger, {live_id}, {model["value"]}, {edges[0]}, {edges[1]});')
        functions.extend(output + ['return 0;', '}'])
    output = main
    forced = sum(step % 7 == 0 or step == steps - 1 for step in range(steps))
    output += [f'stress_assert(GCCOUNT > {forced}, 37); return 0;', '}', 'stress_main();']
    return '\n'.join(functions + output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 42, 2026])
    parser.add_argument('--steps', type=int, default=96)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--self-test', action='store_true', help='prove invariant/oracle failures are detected')
    parser.add_argument('--failure-dir', type=Path, default=ROOT / 'tests/compliance/build/gc-stress')
    args = parser.parse_args()
    assert 32 <= args.steps <= 512
    runtime = (ROOT / 'toolchain/mayc/runtime.may').read_text().replace('mut sz: Any = 268435456;', 'mut sz: Any = 4194304;')
    env = os.environ.copy(); env['MAYLANG_STDLIB'] = str(ROOT / 'stdlib')
    results = []
    with tempfile.TemporaryDirectory(prefix='mayc-gc-stress-') as directory:
        work = Path(directory)
        for seed in args.seeds:
            source = work / 'stress.may'; binary = work / 'stress'
            source.write_text(runtime + INVARIANTS + program(seed, args.steps))
            stage = 'compile'
            try:
                result = subprocess.run([str(args.compiler.resolve()), '--raw', '--legacy', str(source), '-o', str(binary)],
                                        env=env, capture_output=True, timeout=120)
                if result.returncode == 0:
                    stage = 'execute'
                    result = subprocess.run([str(binary)], capture_output=True, timeout=45)
                failure = result.returncode != 0
                metadata = {'seed': seed, 'steps': args.steps, 'stage': stage, 'exit': result.returncode,
                            'stdout': result.stdout.decode(errors='replace'), 'stderr': result.stderr.decode(errors='replace')}
            except subprocess.TimeoutExpired as error:
                failure = True
                metadata = {'seed': seed, 'steps': args.steps, 'stage': stage, 'timeout': error.timeout,
                            'stdout': (error.stdout or b'').decode(errors='replace'), 'stderr': (error.stderr or b'').decode(errors='replace')}
            if failure:
                args.failure_dir.mkdir(parents=True, exist_ok=True)
                (args.failure_dir / f'seed-{seed}.may').write_bytes(source.read_bytes())
                (args.failure_dir / f'seed-{seed}.json').write_text(json.dumps(metadata, indent=2) + '\n')
                raise AssertionError(metadata)
            results.append({'seed': seed, 'steps': args.steps, 'passed': True})
            print(f'PASS GC seed {seed}: live-graph oracle, encoded roots and heap/free-bin invariants', flush=True)
        if args.self_test:
            original = runtime + INVARIANTS + program(1, 32)
            mutations = {
                'identity': ('rt_gc(); stress_heap_check();', 'rt_gc(); store8(GCSTARTS + (load64(ledger) - HEAP) / 8, 1); stress_heap_check();', 23),
                'free_count': ('rt_gc(); stress_heap_check();', 'rt_gc(); FREECOUNT += 1; stress_heap_check();', 24),
                'payload': ('rt_gc(); stress_heap_check();', 'rt_gc(); stress_heap_check(); store64(load64(ledger), 999);', 33),
            }
            for label, (before, after, status) in mutations.items():
                source.write_text(original.replace(before, after, 1))
                compiled = subprocess.run([str(args.compiler.resolve()), '--raw', '--legacy', str(source), '-o', str(binary)],
                                          env=env, capture_output=True, timeout=120)
                assert compiled.returncode == 0, compiled.stderr
                result = subprocess.run([str(binary)], capture_output=True, timeout=30)
                assert result.returncode == status, (label, result)
                print(f'PASS GC checker detects injected {label} corruption (exit {status})', flush=True)
        # The compiler copy must carry the reduced runtime, rather than load
        # the checkout's normal sidecar through its installed launcher.
        launcher = args.compiler.resolve()
        subprocess.run([str(launcher), '--version'], env=env, capture_output=True, check=True, timeout=300)
        executable = ROOT / 'toolchain/mayc/build/bin/mayc_new' if launcher == ROOT / 'toolchain/mayc/mayc_new' else launcher
        copied = work / 'mayc'
        shutil.copy2(executable, copied)
        (work / 'runtime.may').write_text(runtime)
        shutil.copy2(ROOT / 'toolchain/mayc/native.may', work / 'native.may')
        shutil.copy2(ROOT / 'stdlib/prelude.may', work / 'prelude.may')
        compiled = subprocess.run([str(copied), str(ROOT / 'toolchain/mayc/tests/library/gc_objects.may'), '-o', str(binary)],
                                  env=env, capture_output=True, timeout=120)
        assert compiled.returncode == 0, compiled.stderr
        result = subprocess.run([str(binary)], capture_output=True, timeout=60)
        assert result.returncode == 0 and b'PASS GC lists/maps/closures' in result.stdout, result
        print(result.stdout.decode(), end='')
    if args.report:
        args.report.write_text(json.dumps({'heap_bytes': 4194304, 'cases': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
