#!/usr/bin/env python3
"""Allocation identity and live graphs across repeated forced collections."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    runtime = (ROOT/'toolchain/mayc/runtime.may').read_text()
    harness = r'''
fun gc_regression() -> Any {
    STACKTOP = __sp();
    rt_init();
    let owner: Any = rt_alloc(128);
    let roots: Any = syscall(9, 0, 4096, 3, 34, -1, 0);
    store64(roots, owner); rt_gc_root(roots);
    // Payload bytes can contain old headers after coalescing/reuse, or simply
    // coincidentally match a header. They must never become allocation roots.
    store64(owner + 16, 32);
    store64(owner + 24, 5124095576638253);
    if (rt_candidate(owner + 32) != 0) { syscall(60, 1); }
    if (rt_candidate(owner) != owner) { syscall(60, 2); }
    let graph: Any = rt_list_new(4);
    store64(roots + 8, graph); rt_gc_root(roots + 8);
    mut round: Any = 0;
    while (round < 100) {
        let text: Any = rt_from(addr("persistent"), 10);
        rt_push(graph, text);
        let garbage: Any = rt_alloc(8192 + round * 8);
        store64(garbage, round);
        rt_gc();
        mut index: Any = 0;
        while (index <= round) {
            let item: Any = rt_list_get(graph, index * 8);
            if (rt_slen(item) != 10 or load8(item + 7) != 112) { syscall(60, 3); }
            index += 1;
        }
        if (load64(owner + 16) != 32) { syscall(60, 4); }
        round += 1;
    }
    if (GCCOUNT != 100) { syscall(60, 5); }
    syscall(1, 1, addr("PASS GC allocation identity and live graphs\n"), 43);
    return 0;
}
gc_regression();
'''
    with tempfile.TemporaryDirectory(prefix='mayc-gc-') as directory:
        work = Path(directory)
        source = work/'gc.may'; source.write_text(runtime + harness)
        binary = work/'gc'
        result = subprocess.run([str(args.compiler.resolve()), '--raw', '--legacy', str(source), '-o', str(binary)], capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode()
        result = subprocess.run([str(binary)], capture_output=True, timeout=30)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        print(result.stdout.decode(), end='')


if __name__ == '__main__':
    main()
