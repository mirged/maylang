#!/usr/bin/env python3
"""Linear-scan invariants, generated code, ABI, reduced frames and forced GC."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from backends import compiler_binary, compile_source, emulate

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def run(binary, expected):
    result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, timeout=40)
    assert result.returncode == 0 and result.stdout == expected, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--require-emulation', action='store_true')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    try:
        import unicorn
        have_emulation = True
    except ImportError:
        have_emulation = False
    assert have_emulation or not args.require_emulation, 'Unicorn is required'
    with tempfile.TemporaryDirectory(prefix='mayc-regalloc-') as directory:
        work = Path(directory)
        unit = work / 'unit'
        compile_source(compiler, HERE / 'backend/regalloc.may', unit)
        run(unit, b'allocator-ok\n')
        print('PASS live intervals, expiration, furthest-end spills, home reuse, loop pins and call root timing', flush=True)

        source = work / 'calls.may'
        source.write_text('''
fun square(n: Int) -> Int { return n * n; }
fun compute(n: Int) -> Int { return (n + 1) * square(n + 2) + square(n + 3) * (n + 4); }
fun eight(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int, g: Int, h: Int) -> Int {
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h;
}
fun closure(n: Int) -> Any { return |x: Int| -> Int { return x + n; }; }
let callback: Any = closure(7);
print(compute(5), (compute(2) + callback(3)) * (compute(4) + callback(5)));
mut total: Int = 0;
mut n: Int = 0;
while n < 100 {
    total += compute(n);
    n += 1;
}
print(total);
print(may { (compute(1) + callback(2)) * (1 / 0) } otherwise { compute(3) });
print(eight(compute(1), compute(2), compute(3), compute(4), compute(5), compute(6), compute(7), compute(8)));
''')
        compute = lambda n: (n + 1) * (n + 2) ** 2 + (n + 3) ** 2 * (n + 4)
        expected = f'{compute(5)} {(compute(2) + 10) * (compute(4) + 12)}\n{sum(compute(n) for n in range(100))}\n{compute(3)}\n'.encode()
        expected += f'{sum(n * compute(n) for n in range(1, 9))}\n'.encode()
        binary = work / 'calls'
        compile_source(compiler, source, binary)
        run(binary, expected)
        print('PASS direct/indirect calls, nested expressions, loops and exception unwinding', flush=True)

        # Hundreds of virtual temporaries used to exceed the raw 2000-byte
        # frame limit. A live-range allocator needs only a few reused homes.
        source = work / 'large.may'
        updates = ''.join('n = (n + 1) * 1;\n' for _ in range(180))
        source.write_text('fun bump(n: Any) -> Any {\n' + updates + 'return n; }\n' +
                          'fun three(n: Any) -> Any { return n + 3; }\n' +
                          'fun eight(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any, g: Any, h: Any) -> Any {\n' +
                          'return a + 2*b + 3*c + 4*d + 5*e + 6*f + 7*g + 8*h; }\n' +
                          'if (bump(2) + three(4)) * (three(5) + bump(6)) != 189 * 194 { exit(17); }\n' +
                          'if eight(bump(1), bump(2), bump(3), bump(4), bump(5), bump(6), bump(7), bump(8)) != 6684 { exit(18); }\n' +
                          'syscall(64, 1, addr("target-ok\\n"), 10); exit(42);\n')
        for target, arch in [('arm64-linux', 'arm64'), ('riscv64-linux', 'riscv64')]:
            image = compile_source(compiler, source, work / target, '--raw', '--target', target)
            if have_emulation:
                emulate(image, arch)
            print(f'PASS {target}: reusable frames and live values across calls' + ('' if have_emulation else ' (execution skipped)'), flush=True)
        source.write_text(source.read_text().replace('syscall(64,', 'syscall(1,'))
        native = work / 'native'
        image = compile_source(compiler, source, native, '--raw')
        result = subprocess.run([str(native)], capture_output=True, timeout=10)
        assert result.returncode == 42 and result.stdout == b'target-ok\n', result
        # Reserved physical registers must occur in the emitted code, not just
        # in a planner which the backend forgets to consult.
        assert any(bytes([0x49, 0x89, modrm]) in image for modrm in range(0xc4, 0xc8))
        print('PASS x86-64 emits allocated registers and executes call/pressure workload', flush=True)

        # Compile with a test-only 16 MiB runtime to force collections while a
        # freshly created first argument remains live across evaluation of the
        # allocating second argument. Exercise direct and closure calls.
        small = work / 'small'
        small.mkdir()
        shutil.copy2(compiler, small / 'mayc')
        runtime = (ROOT / 'toolchain/mayc/runtime.may').read_text()
        runtime = runtime.replace('mut sz: Any = 268435456;', 'mut sz: Any = 16777216;', 1)
        runtime = runtime.replace('    GCCOUNT = GCCOUNT + 1;', '    GCCOUNT = GCCOUNT + 1;\n    rt_write(addr("gc\\n"), 3);', 1)
        (small / 'runtime.may').write_text(runtime)
        shutil.copy2(ROOT / 'stdlib/prelude.may', small / 'prelude.may')
        shutil.copy2(ROOT / 'stdlib/native.may', small / 'native.may')
        source = work / 'gc.may'
        source.write_text('''
fun make() -> List<Int> { return [73, 91]; }
fun take(xs: List<Int>, ignored: Int) -> Int { return xs[0] + xs[1]; }
fun take6(a: List<Int>, b: List<Int>, c: List<Int>, d: List<Int>, e: List<Int>, f: List<Int>, ignored: Int) -> Int {
    return a[0] + b[0] + c[0] + d[0] + e[0] + f[0];
}
fun churn() -> Int {
    mut n: Int = 0;
    while n < 4096 {
        let junk: List<Int> = range(0, 2048);
        if junk[2047] != 2047 { fail("corrupt temporary"); }
        n += 1;
    }
    return n;
}
let callback: Any = |xs: List<Int>, ignored: Int| -> Int { return xs[0] + xs[1]; };
print(take(make(), churn()));
print(callback(make(), churn()));
print(take6(make(), make(), make(), make(), make(), make(), churn()));
''')
        binary = work / 'gc'
        compile_source(small / 'mayc', source, binary)
        result = subprocess.run([str(binary)], capture_output=True, timeout=60)
        assert result.returncode == 0 and not result.stderr, result
        assert b'gc\n' in result.stdout and result.stdout.replace(b'gc\n', b'') == b'164\n164\n438\n', result
        print('PASS forced GC preserves register and spilled arguments across direct and indirect calls', flush=True)


if __name__ == '__main__':
    main()
