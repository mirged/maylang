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
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    cc = shutil.which('cc')
    assert cc, 'extern tests require a C compiler'
    targets = ['x86_64-linux', 'clang-llvm'] if args.llvm else ['x86_64-linux']
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
            # Native ELF symbol interposition binds duplicate names globally;
            # LLVM's explicit library handles preserve the two declarations.
            assert result.returncode == 0 and not result.stderr, result
            assert sorted(lines[:2]) == [b'loaded1', b'loaded2'] and lines[2] == b'main', result
            assert lines[3] == (b'1 2' if target == 'clang-llvm' else b'1 1'), result
            print(f'PASS {target}: library constructors run before user statements', flush=True)
        if args.llvm:
            for library, symbol in [('lib-not-installed-externs.so', 'missing'), ('libc.so.6', 'missing_externs_symbol')]:
                source.write_text(f'extern "{library}" {{ fun missing() -> Int = "{symbol}"; }} missing();')
                binary = work / 'missing'
                result = run([args.compiler.resolve(), '--target', 'clang-llvm', source, '-o', binary])
                assert result.returncode == 0, result.stderr.decode()
                result = run([binary])
                assert result.returncode == 70 and b'cannot resolve extern' in result.stdout, result
            print('PASS LLVM missing library and symbol produce runtime diagnostics', flush=True)


if __name__ == '__main__':
    main()
