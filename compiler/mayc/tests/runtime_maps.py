#!/usr/bin/env python3
"""String hash collisions, order, replacement/removal, mixed keys and GC."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from backends import compiler_binary, compile_source

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-runtime-maps-') as directory:
        work = Path(directory)
        helpers = work / 'helpers'
        compile_source(compiler, HERE / 'backend/build_helpers.may', helpers)
        result = subprocess.run([str(helpers)], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == b'helpers-ok\n', result
        print('PASS byte copies preserve every bit and symbol caching preserves mutable/UTF-8 bytes', flush=True)
        # Distinct ASCII keys collide under the runtime's polynomial hash.
        def key_hash(key):
            value = 5381
            for byte in key.encode():
                value = (value * 131 + byte) % 2147483647
            return value
        assert key_hash('KmsBdOnXU') == key_hash('kjWKxlbWj')
        small = work / 'small'; small.mkdir()
        shutil.copy2(compiler, small / 'mayc')
        # The full runtime's heap lives in runtime/fat_linux.may.
        shutil.copytree(ROOT / 'compiler/mayc/runtime', small / 'runtime')
        fat = (ROOT / 'compiler/mayc/runtime/fat_linux.may').read_text()
        assert 'mut sz: Any = 268435456;' in fat and '    GCCOUNT = GCCOUNT + 1;' in fat
        fat = fat.replace('mut sz: Any = 268435456;', 'mut sz: Any = 16777216;', 1)
        fat = fat.replace('    GCCOUNT = GCCOUNT + 1;', '    GCCOUNT = GCCOUNT + 1;\n    rt_write(addr("gc\\n"), 3);', 1)
        (small / 'runtime' / 'fat_linux.may').write_text(fat)
        # Keep the public copy-returning helper available under another name
        # so remove() also exercises the backend's in-place runtime intrinsic.
        native = (ROOT / 'compiler/mayc/native.may').read_text().replace('fun remove(', 'fun copied_remove(', 1)
        (small / 'native.may').write_text(native)
        shutil.copy2(ROOT / 'stdlib/prelude.may', small / 'prelude.may')
        source = work / 'maps.may'
        source.write_text('''
let m: Any = {};
for i: Any in 0..1500 { m["key" + str(i)] = i * 7; }
m["KmsBdOnXU"] = 73; m["kjWKxlbWj"] = 91;
for i: Any in 0..1500 { if m["key" + str(i)] != i * 7 { fail("hash lookup"); } }
m["KmsBdOnXU"] = 123;
let without: Any = copied_remove(m, "key17");
if has(without, "key17") or !has(m, "key17") { fail("copy removal"); }
remove(m, "key17");
if m["kjWKxlbWj"] != 91 or m["KmsBdOnXU"] != 123 or has(m, "key17") { fail("collision or removal"); }
let ordered: Any = keys(m);
if ordered[0] != "key0" or ordered[17] != "key18" { fail("iteration order"); }
let identity: Any = [1, 2]; m[identity] = 84;
if m[identity] != 84 or m[[1, 2]] != nil { fail("identity key"); }
m[7] = 56; m[7.0] = 99;
if m[7] != 56 or m[7.0] != 99 { fail("mixed numeric keys"); }
mut n: Any = 0;
while n < 4096 {
    let junk: Any = range(0, 2048);
    if junk[2047] != 2047 { fail("small allocation corruption"); }
    n += 1;
}
for i: Any in 0..1500 { if i != 17 and m["key" + str(i)] != i * 7 { fail("GC lost indexed key"); } }
if m["KmsBdOnXU"] != 123 or m["kjWKxlbWj"] != 91 { fail("GC lost collision"); }
print("maps-ok");
''')
        binary = work / 'maps'
        compile_source(small / 'mayc', source, binary)
        result = subprocess.run([str(binary)], capture_output=True, timeout=40)
        assert result.returncode == 0 and not result.stderr, result
        assert b'gc\n' in result.stdout and result.stdout.replace(b'gc\n', b'') == b'maps-ok\n', result
        print('PASS hash collisions, ordered iteration, replacements/removal, mixed keys and actual collections', flush=True)
        # Records (#134) are one fixed-slot block until a dynamic field write
        # moves their entries out. The record header must keep those entries -
        # and its hash table - alive across real collections: the reverted
        # prototype did not and the compiler built with it crashed.
        source = work / 'records.may'
        source.write_text("""
struct Node { id: Any, next: Any, payload: Any }
struct Wide { a0: Any, a1: Any, a2: Any, a3: Any, a4: Any, a5: Any, a6: Any, a7: Any, a8: Any }
let keep: List<Any> = [];
mut i: Any = 0;
while (i < 4000) {
    let node: Any = Node(i, nil, "p" + str(i));
    node.extra = i;
    if (i % 4 == 0) { push(keep, node); }
    i += 1;
}
mut wide: Any = Wide(0, 1, 2, 3, 4, 5, 6, 7, 8);
wide.a9 = 9;
wide.a10 = 10;
mut n: Any = 0;
while (n < 320) {
    let junk: Any = range(0, 4096);
    if junk[4095] != 4095 { fail("record churn"); }
    n += 1;
}
mut k: Any = 0;
while (k < len(keep)) {
    let node: Any = keep[k];
    let id: Any = k * 4;
    if node.id != id or node.extra != id or node.payload != "p" + str(id) { fail("record lost"); }
    let ks: Any = keys(node);
    if ks[0] != "id" or ks[3] != "extra" { fail("record order"); }
    k += 1;
}
if wide.a0 != 0 or wide.a8 != 8 or wide.a9 != 9 or wide.a10 != 10 { fail("grown record lost"); }
let first: Any = keep[0];
first.later = 123;
mut m: Any = 0;
while (m < 320) {
    let junk: Any = range(0, 4096);
    if junk[4095] != 4095 { fail("record churn 2"); }
    m += 1;
}
if first.later != 123 or first.id != 0 or first.extra != 0 { fail("record regrown lost"); }
print("records-ok");
""")
        binary = work / 'records'
        compile_source(small / 'mayc', source, binary)
        result = subprocess.run([str(binary)], capture_output=True, timeout=40)
        assert result.returncode == 0 and not result.stderr, result
        assert b'gc\n' in result.stdout and result.stdout.replace(b'gc\n', b'') == b'records-ok\n', result
        print('PASS records keep their grown entries and hash table across collections', flush=True)


if __name__ == '__main__':
    main()
