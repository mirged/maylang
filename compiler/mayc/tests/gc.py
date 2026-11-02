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


RECORDS = r"""
fun gc_rec_expect(actual: Any, expected: Any, code: Any) -> Any {
    if (actual != expected) { syscall(60, code); }
    return 0;
}
fun gc_rec_key_is(keys: Any, index: Any, expected: Any, code: Any) -> Any {
    gc_rec_expect(rt_element_tag(keys, index), 4, code);
    gc_rec_expect(rt_element(keys, index), expected, code);
    return 0;
}
// A record (#134) is one block: a 48-byte map header followed by entries at
// p + 48. It must observe exactly like a map built through rt_map_put, and the
// collector must keep tracing it when it grows its entries out of the block.
fun gc_probe() -> Any {
    let roots: Any = syscall(9, 0, 4096, 3, 34, -1, 0);
    rt_gc_root(roots);
    let kx: Any = rt_from(addr("x"), 1);
    let ky: Any = rt_from(addr("y"), 1);
    let kz: Any = rt_from(addr("z"), 1);
    let kw: Any = rt_from(addr("w"), 1);
    let kv: Any = rt_from(addr("v"), 1);
    let k0: Any = rt_from(addr("k0"), 2);
    let k1: Any = rt_from(addr("k1"), 2);
    let k2: Any = rt_from(addr("k2"), 2);
    let k3: Any = rt_from(addr("k3"), 2);
    let k4: Any = rt_from(addr("k4"), 2);
    let k5: Any = rt_from(addr("k5"), 2);
    let k6: Any = rt_from(addr("k6"), 2);
    let k7: Any = rt_from(addr("k7"), 2);
    let k8: Any = rt_from(addr("k8"), 2);
    let k9: Any = rt_from(addr("k9"), 2);
    // Header shape: count = fields, capacity = 2 * fields, entries at p + 48,
    // no hash table.
    let m: Any = rt_struct_new(2, 3);
    store64(roots, m);
    gc_rec_expect(load64(m), 3, 40);
    gc_rec_expect(load64(m + 8), 6, 41);
    gc_rec_expect(load64(m + 16), m + 48, 42);
    gc_rec_expect(load64(m + 24), 0, 43);
    gc_rec_expect(load64(m + 32), 0, 44);
    rt_struct_set(6, m, 2, 0, 4, kx, 2, 1);
    rt_struct_set(6, m, 2, 1, 4, ky, 2, 2);
    rt_struct_set(6, m, 2, 2, 4, kz, 4, rt_from(addr("persistent"), 10));
    // Every map read path sees the entries: index, lookup, len, keys, values,
    // to_map, identity equality and display.
    gc_rec_expect(rt_index_get(6, m, 4, kx), 1, 45);
    gc_rec_expect(RTAG, 2, 46);
    let valuez: Any = rt_map_lookup(m, 4, kz);
    gc_rec_expect(RTAG, 4, 47);
    gc_rec_expect(load64(rt_values(6, m)), 3, 48);
    gc_rec_expect(rt_element(rt_values(6, m), 2), valuez, 49);
    gc_rec_expect(rt_len(6, m), 3, 50);
    gc_rec_expect(rt_has(6, m, 4, ky), 1, 51);
    gc_rec_expect(rt_has(6, m, 4, kw), 0, 52);
    mut keys: Any = rt_keys(6, m);
    gc_rec_expect(RTAG, 5, 53);
    gc_rec_expect(load64(keys), 3, 54);
    gc_rec_key_is(keys, 0, kx, 55);
    gc_rec_key_is(keys, 1, ky, 56);
    gc_rec_key_is(keys, 2, kz, 57);
    gc_rec_expect(rt_to_map(6, m), m, 58);
    gc_rec_expect(RTAG, 6, 59);
    gc_rec_expect(rt_eq(6, m, 6, m), 1, 60);
    // Display matches an ordinary map with the same entries.
    let equiv: Any = rt_map_new_raw();
    rt_map_put(equiv, 4, kx, 2, 1);
    rt_map_put(equiv, 4, ky, 2, 2);
    rt_map_put(equiv, 4, kz, 4, valuez);
    gc_rec_expect(rt_eq(6, m, 6, equiv), 0, 61);
    store64(roots + 8, equiv);
    gc_rec_expect(rt_str_eq(rt_display(6, m, 0), rt_display(6, equiv, 0)), 1, 62);
    // A collection keeps the in-block entries and the Str value they hold.
    rt_gc();
    gc_rec_expect(rt_candidate(m), m, 63);
    gc_rec_expect(load64(m + 16), m + 48, 64);
    let surviving: Any = rt_map_lookup(m, 4, kz);
    gc_rec_expect(rt_candidate(surviving), surviving, 65);
    gc_rec_expect(RTAG, 4, 66);
    // Mutation through an Any alias updates the existing entry in place.
    rt_map_set(6, m, 4, kx, 2, 41);
    gc_rec_expect(rt_map_lookup(m, 4, kx), 41, 67);
    // remove keeps insertion order and shifts the later entries.
    rt_remove(6, m, 4, ky);
    gc_rec_expect(load64(m), 2, 68);
    keys = rt_keys(6, m);
    gc_rec_key_is(keys, 0, kx, 69);
    gc_rec_key_is(keys, 1, kz, 70);
    gc_rec_expect(rt_map_find(m, 4, ky), -1, 71);
    // merge_into appends a record's entries in order.
    let r: Any = rt_struct_new(2, 1);
    rt_struct_set(6, r, 2, 0, 4, kw, 2, 4);
    rt_merge_into(6, m, 6, r);
    gc_rec_expect(load64(m), 3, 72);
    keys = rt_keys(6, m);
    gc_rec_key_is(keys, 2, kw, 73);
    // Growth moves the entries out of the block. The record header must keep
    // the entries block (and later its hash table) alive: the first prototype
    // traced neither and crashed the compiler it built.
    rt_map_put(m, 4, kv, 2, 5);
    gc_rec_expect(load64(m), 4, 74);
    gc_rec_expect(load64(m + 16) != m + 48, 1, 75);
    rt_gc();
    let moved: Any = load64(m + 16);
    gc_rec_expect(rt_candidate(moved), moved, 76);
    gc_rec_expect(rt_map_lookup(m, 4, kv), 5, 77);
    gc_rec_expect(rt_map_lookup(m, 4, kz), valuez, 78);
    gc_rec_expect(RTAG, 4, 79);
    // A record with more than eight entries that grows gets a hash table; it
    // must survive a collection too.
    let h: Any = rt_struct_new(2, 9);
    store64(roots + 16, h);
    rt_struct_set(6, h, 2, 0, 4, k0, 2, 0);
    rt_struct_set(6, h, 2, 1, 4, k1, 2, 1);
    rt_struct_set(6, h, 2, 2, 4, k2, 2, 2);
    rt_struct_set(6, h, 2, 3, 4, k3, 2, 3);
    rt_struct_set(6, h, 2, 4, 4, k4, 2, 4);
    rt_struct_set(6, h, 2, 5, 4, k5, 2, 5);
    rt_struct_set(6, h, 2, 6, 4, k6, 2, 6);
    rt_struct_set(6, h, 2, 7, 4, k7, 2, 7);
    rt_struct_set(6, h, 2, 8, 4, k8, 2, 8);
    gc_rec_expect(load64(h), 9, 80);
    gc_rec_expect(load64(h + 24), 0, 81);
    gc_rec_expect(load64(h + 32), 0, 82);
    rt_map_put(h, 4, k9, 2, 9);
    gc_rec_expect(load64(h), 10, 83);
    gc_rec_expect(load64(h + 24) != 0, 1, 84);
    gc_rec_expect(load64(h + 32) != 0, 1, 85);
    gc_rec_expect(rt_map_lookup(h, 4, k7), 7, 86);
    rt_gc();
    let table: Any = load64(h + 24);
    gc_rec_expect(rt_candidate(load64(h + 16)), load64(h + 16), 87);
    gc_rec_expect(rt_candidate(table), table, 88);
    gc_rec_expect(rt_map_lookup(h, 4, k9), 9, 89);
    gc_rec_expect(rt_map_lookup(h, 4, k0), 0, 90);
    keys = rt_keys(6, h);
    gc_rec_expect(load64(keys), 10, 91);
    gc_rec_key_is(keys, 9, k9, 92);
    let equiv2: Any = rt_map_new_raw();
    rt_map_put(equiv2, 4, k0, 2, 0);
    rt_map_put(equiv2, 4, k1, 2, 1);
    rt_map_put(equiv2, 4, k2, 2, 2);
    rt_map_put(equiv2, 4, k3, 2, 3);
    rt_map_put(equiv2, 4, k4, 2, 4);
    rt_map_put(equiv2, 4, k5, 2, 5);
    rt_map_put(equiv2, 4, k6, 2, 6);
    rt_map_put(equiv2, 4, k7, 2, 7);
    rt_map_put(equiv2, 4, k8, 2, 8);
    rt_map_put(equiv2, 4, k9, 2, 9);
    store64(roots + 24, equiv2);
    gc_rec_expect(rt_str_eq(rt_display(6, h, 0), rt_display(6, equiv2, 0)), 1, 93);
    syscall(1, 1, addr("PASS record slots, observation and collector tracing\n"), 53);
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
        result = run(RECORDS)
        assert result.returncode == 0 and result.stdout == b'PASS record slots, observation and collector tracing\ndone\n', (result.returncode, result.stdout, result.stderr)
        print(result.stdout.decode().splitlines()[0])


if __name__ == '__main__':
    main()
