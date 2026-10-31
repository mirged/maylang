#!/usr/bin/env python3
"""C-ABI oracles for typed externs, aliases and first-class bindings."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
C_SOURCE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
int64_t signed64(int64_t n) { return n - 1; }
void *raw_function(void) { return (void *)&signed64; }
uint64_t unsigned64(uint64_t n) { return n + 1; }
int32_t signed32(int32_t n) { return n - 1; }
uint32_t unsigned32(uint32_t n) { return n + 1; }
float narrow(float n) { return n + 0.25f; }
double wide(double n) { return n + 0.5; }
bool invert(bool n) { return !n; }
const char *text(const char *s) { return s; }
const char *null_text(void) { return NULL; }
void *pointer(void *p) { return p; }
static int64_t saved;
void save(int64_t n) { saved = n; }
int64_t read_saved(void) { return saved; }
double mixed(int64_t a, double b, int64_t c, double d, int64_t e, double f,
             int64_t g, double h, int64_t i, double j, int64_t k, double l,
             int64_t m, double n, int64_t o, double p, double q) {
    return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q;
}
'''


def run(argv):
    return subprocess.run([str(a) for a in argv], cwd=ROOT, capture_output=True, timeout=120)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    cc = shutil.which('cc')
    assert cc, 'extern tests require a C compiler'
    targets = ['x86_64-linux']
    with tempfile.TemporaryDirectory(prefix='mayc externs ') as directory:
        work = Path(directory)
        library = work / 'abi oracle.so'
        c_source = work / 'oracle.c'
        c_source.write_text(C_SOURCE)
        result = run([cc, '-shared', '-fPIC', c_source, '-o', library])
        assert result.returncode == 0, result.stderr.decode()
        source = work / 'externs.may'
        source.write_text(f'''extern "{library}" {{
    fun signed64(n: Int) -> Int;
    fun raw_function() -> Ptr;
    fun unsigned64(n: UInt) -> UInt;
    fun signed32(n: Int32) -> Int32;
    fun unsigned32(n: UInt32) -> UInt32;
    fun narrow(n: Float32) -> Float32;
    fun wide(n: Float) -> Float;
    fun invert(n: Bool) -> Bool;
    fun text(s: Str) -> Str;
    fun null_text() -> Str;
    fun pointer(p: Ptr) -> Ptr;
    fun save(n: Int) -> Void;
    fun read_saved() -> Int;
    fun mixed(a: Int, b: Float, c: Int, d: Float, e: Int, f: Float,
              g: Int, h: Float, i: Int, j: Float, k: Int, l: Float,
              m: Int, n: Float, o: Int, p: Float, q: Float) -> Float;
}}
let f: Any = signed32;
print(ccall(raw_function(), [42]));
let raw: Any = extern_c(raw_function()); print(raw(43, 0, 0, 0, 0, 0));
print(signed64(-41), unsigned64(41), signed32(-2147483647), unsigned32(4294967294), f(-6));
print(narrow(1.5), wide(1.5), invert(true), invert(false));
print(text("héλ"), null_text(), pointer(0));
let ignored: Nil = save(42); print(ignored, read_saved());
print(mixed(1,2.0,3,4.0,5,6.0,7,8.0,9,10.0,11,12.0,13,14.0,15,16.0,17.0));
print(may {{ text("a\\0b"); "bad" }} otherwise {{ str(err.kind) }});
let bad: Int = -1;
print(may {{ unsigned64(bad); "bad" }} otherwise {{ str(err.kind) }});
''')
        expected = (b'41\n42\n-42 42 -2147483648 4294967295 -7\n'
                    b'1.75 2.0 false true\nh\xc3\xa9\xce\xbb nil 0\nnil 42\n153.0\ntype\narithmetic\n')
        for target in targets:
            binary = work / target
            result = run([args.compiler.resolve(), '--target', target, source, '-o', binary])
            assert result.returncode == 0, result.stderr.decode()
            result = run([binary])
            assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), (target, result)
            print(f'PASS {target}: scalar C ABI, stack arguments, function values and guards', flush=True)
        # Native-word functions (#92) call integer externs directly with
        # machine words (#94): results keep bit 61 and above, and only UInt
        # ranges are checked, with the fat entry's fault messages.
        c_source.write_text('#include <stdbool.h>\n#include <stdint.h>\n'
                            'int64_t high(int64_t n) { return n << 61; }\n'
                            'uint64_t ident(uint64_t n) { return n; }\n'
                            'uint64_t top_bit(void) { return 1ull << 63; }\n'
                            'void *offset(void *p, int64_t n) { return (char *)p + n; }\n'
                            'bool flip(bool b) { return !b; }\n'
                            'static int64_t saved; void save(int64_t n) { saved = n; }\n'
                            'int64_t read_saved(void) { return saved; }\n'
                            'int64_t digits(int64_t a, uint64_t b, void *c, bool d) '
                            '{ return a * 1000 + (int64_t)b * 100 + (int64_t)(intptr_t)c * 10 + d; }\n')
        words = work / 'words oracle.so'
        result = run([cc, '-shared', '-fPIC', c_source, '-o', words])
        assert result.returncode == 0, result.stderr.decode()
        source.write_text(f'''extern "{words}" {{
    fun high(n: Int) -> Int;
    fun ident(n: UInt) -> UInt;
    fun top_bit() -> UInt;
    fun offset(p: Ptr, n: Int) -> Ptr;
    fun flip(b: Bool) -> Bool;
    fun save(n: Int) -> Void;
    fun read_saved() -> Int;
    fun digits(a: Int, b: UInt, c: Ptr, d: Bool) -> Int;
}}
fun top(n: Int) -> Int {{ return high(n) >> 61; }}
fun moved(n: Int) -> Ptr {{ return offset(high(1), n - high(1)); }}
fun negate(b: Bool) -> Bool {{ return flip(b) and not flip(not b); }}
fun stored(n: Int) -> Int {{ save(n << 62); return read_saved() >> 62; }}
fun mixed(n: Int) -> Int {{ return digits(n, 2, 3, true) + high(1) - high(1); }}
fun passed(n: Int) -> Int {{ return ident(n); }}
fun widest() -> Int {{ return top_bit(); }}
fun outlined(n: Any) -> Int {{ let k: Int = int(n); return (high(k) >> 61) & 7; }}
print(top(3), moved(5), negate(false), stored(1), mixed(1), outlined(3));
print(may {{ passed(-1); "bad" }} otherwise {{ err.message }});
print(may {{ widest(); "bad" }} otherwise {{ err.message }});
print(may {{ high(4); "bad" }} otherwise {{ err.message }});
''')
        for target in targets:
            binary = work / f'words-{target}'
            result = run([args.compiler.resolve(), '--target', target, source, '-o', binary])
            assert result.returncode == 0, result.stderr.decode()
            result = run([binary])
            # With fat values (x86_64-linux) Int holds the 2^63 result of high(4).
            want = (b'3 5 true 1 1231 3\nunsigned argument out of range\n'
                    b'C result exceeds Int range\nbad\n')
            assert (result.returncode, result.stdout, result.stderr) == (0, want, b''), (target, result)
            print(f'PASS {target}: native-word functions call integer externs with machine words', flush=True)
        # Missing unused dependencies must not enter the executable's live graph.
        source.write_text('extern "lib-not-installed-externs.so" { fun unused() -> Int; } print(42);')
        for target in targets:
            binary = work / f'unused-{target}'
            result = run([args.compiler.resolve(), '--target', target, source, '-o', binary])
            assert result.returncode == 0, result.stderr.decode()
            assert b'lib-not-installed-externs.so' not in binary.read_bytes()
            result = run([binary])
            assert (result.returncode, result.stdout, result.stderr) == (0, b'42\n', b''), result
        print('PASS unused extern dependencies are pruned', flush=True)
        # Loading must precede user statements, including calls reached only
        # through closures. Symbols belong to their declared library.
        libraries = []
        for index in (1, 2):
            library = work / f'constructor{index}.so'
            c_source.write_text('#include <unistd.h>\n'
                                f'__attribute__((constructor)) static void init(void) {{ write(1, "loaded{index}\\n", 8); }}\n'
                                f'long same_name(void) {{ return {index}; }}\n')
            result = run([cc, '-shared', '-fPIC', c_source, '-o', library])
            assert result.returncode == 0, result.stderr.decode()
            libraries.append(library)
        source.write_text(f'extern "{libraries[0]}" {{ fun first() -> Int = "same_name"; }}\n'
                          f'extern "{libraries[1]}" {{ fun second() -> Int = "same_name"; }}\n'
                          'print("main"); let f: Any = first; print(f(), second());')
        for target in targets:
            binary = work / f'constructors-{target}'
            result = run([args.compiler.resolve(), '--target', target, source, '-o', binary])
            assert result.returncode == 0, result.stderr.decode()
            result = run([binary])
            lines = result.stdout.splitlines()
            # Native ELF symbol interposition binds duplicate names globally.
            assert result.returncode == 0 and not result.stderr, result
            assert sorted(lines[:2]) == [b'loaded1', b'loaded2'] and lines[2] == b'main', result
            assert lines[3] == b'1 1', result
            print(f'PASS {target}: library constructors run before user statements', flush=True)


if __name__ == '__main__':
    main()
