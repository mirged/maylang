#!/usr/bin/env python3
"""GC allocation identity, retained graphs and global-root capacity."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from backends import compiler_binary

ROOT = Path(__file__).resolve().parents[3]

GRAPH = r"""
fun gc_probe() -> Any {
    let owner: Any = rt_alloc(128);
    let roots: Any = syscall(9, 0, 4096, 3, 34, -1, 0);
    store64(roots, owner); rt_gc_root(roots);
    // Payload bytes can contain old headers after coalescing/reuse, or simply
    // coincidentally match a header. They must never become allocation roots.
    store64(owner + 16, 32);
    store64(owner + 24, 5124095576638253);
    if (rt_candidate(owner + 32) != 0) { syscall(60, 1); }
    if (rt_candidate(owner) != owner) { syscall(60, 2); }
    let graph: Any = rt_list_raw(4);
    store64(roots + 8, graph); rt_gc_root(roots + 8);
    // cstr returns the address of an independently allocated byte copy.
    // Keeping only that address must preserve the copy.
    let copied: Any = rt_cstr(4, rt_from(addr("persistent"), 10));
    rt_mark_word(copied);
    if (load64(copied - 16) % 2 != 1) { syscall(60, 6); }
    store64(roots + 16, copied); rt_gc_root(roots + 16);
    mut round: Any = 0;
    while (round < 100) {
        rt_list_add(graph, 4, rt_from(addr("persistent"), 10));
        let garbage: Any = rt_alloc(8192 + round * 8);
        store64(garbage, round);
        rt_gc();
        mut index: Any = 0;
        while (index <= round) {
            let item: Any = load64(load64(graph + 16) + index * 16 + 8);
            if (load64(item) != 10 or load8(item + 8) != 112) { syscall(60, 3); }
            index += 1;
        }
        if (load64(owner + 16) != 32) { syscall(60, 4); }
        let bytes: Any = load64(roots + 16);
        if (load8(bytes) != 112 or load8(bytes + 10) != 0) { syscall(60, 7); }
        round += 1;
    }
    if (GCCOUNT != 100) { syscall(60, 5); }
    syscall(1, 1, addr("PASS GC allocation identity and live graphs\n"), 44);
    return 0;
}
"""

ROOTS = r"""
fun gc_probe() -> Any {
    let root: Any = syscall(9, 0, 4096, 3, 34, -1, 0);
    let first: Any = GCOUNT;
    rt_gc_root(root);
    let neighbor: Any = rt_alloc(32);
    if (neighbor - 16 != GROOTS + 1048576) { syscall(60, 8); }
    mut count: Any = GCOUNT;
    while (count < 131072) { rt_gc_root(root); count += 1; }
    if (GCOUNT != 131072 or load64(neighbor - 16) != 48) { syscall(60, 3); }
    if (load64(GROOTS + first * 8) != root or load64(GROOTS + 1048568) != root) { syscall(60, 4); }
    // A further registration used to overwrite the next allocation's header.
    rt_gc_root(root);
    syscall(60, if (load64(neighbor - 16) != 48) { 1 } else { 2 });
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'compiler/mayc/mayc_new')
    args = parser.parse_args()
    host = (ROOT/'compiler/mayc/runtime/fat_linux.may').read_text()
    end = '    GCFLAG = 1;\n    return 0;\n}'
    assert host.count(end) == 1
    with tempfile.TemporaryDirectory(prefix='mayc-gc-') as directory:
        work = Path(directory)
        # The probes are raw functions in a copy of the collector's host file
        # (runtime/fat_linux.may), run at the end of rt_init before any
        # compiled code.
        probe = work/'mayc'
        shutil.copy2(compiler_binary(args.compiler), probe)
        shutil.copytree(ROOT/'compiler/mayc/runtime', work/'runtime')
        (work/'native.may').symlink_to(ROOT/'compiler/mayc/native.may')
        (work/'prelude.may').symlink_to(ROOT/'stdlib/prelude.may')
        source = work/'gc.may'; source.write_text('print("done");\n')
        binary = work/'gc'

        def run(probe_source):
            (work/'runtime/fat_linux.may').write_text(host.replace(end, '    GCFLAG = 1;\n    gc_probe();\n    return 0;\n}') + probe_source)
            result = subprocess.run([str(probe), str(source), '-o', str(binary)], capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr.decode()
            return subprocess.run([str(binary)], capture_output=True, timeout=30)

        result = run(GRAPH)
        assert result.returncode == 0 and result.stdout.endswith(b'done\n'), (result.returncode, result.stdout, result.stderr)
        print(result.stdout.decode().splitlines()[0])
        result = run(ROOTS)
        assert result.returncode == 70 and result.stdout == b'GC global root table exhausted\n' and not result.stderr, result
        print('PASS global root capacity fails before writing outside the table')


if __name__ == '__main__':
    main()
