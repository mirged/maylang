#!/usr/bin/env python3
"""Exercise the closed scalar ! pure fragment through the active compiler."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-behavior-') as directory:
        work = Path(directory)

        def compile_case(name, source, options=(), error=None):
            path = work / (name + '.may')
            path.write_text(source)
            binary = work / name
            result = subprocess.run([str(compiler), *options, str(path), '-o', str(binary)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=180)
            if error:
                assert result.returncode != 0 and error in result.stderr, (name, result)
                assert not binary.exists(), name
            else:
                assert result.returncode == 0, (name, result.stderr)
            return binary

        source = '''
fun even(n: Int) -> Bool ! pure { if (n == 0) { return true; } return odd(n - 1); }
fun odd(n: Int) -> Bool ! pure { if (n == 0) { return false; } return even(n - 1); }
fun double(n: Int) -> Int ! pure { let x: Int = n * 2; return x; }
print(double(21), even(10), odd(9));
'''
        binary = compile_case('recursive', source)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        assert (result.returncode, result.stdout, result.stderr) == (0, '42 true true\n', ''), result
        compile_case('legacy', source, ('--legacy', '--check'), 'requires strict')
        failures = {
            'io': 'print(1); return 0;',
            'syscall': 'return syscall(39);',
            'allocation': 'let x: Int = len([1]); return x;',
            'mutation': 'mut x: Int = 1; return x;',
            'global': 'return outside;',
            'assignment': 'outside = 2; return 0;',
            'hidden_branch': 'if (false) { print(1); } return 0;',
            'unsealed_call': 'return helper();',
        }
        for name, body in failures.items():
            compile_case(name, 'mut outside: Int = 1; fun helper() -> Int { return 7; } '
                         + 'fun f() -> Int ! pure { ' + body + ' }', ('--check',), 'MB-EFFECT-001')
        compile_case('transitive', 'fun a() -> Int ! pure { return b(); } '
                     'fun b() -> Int ! pure { print(1); return 0; }', ('--check',), 'MB-EFFECT-001')
        compile_case('dynamic', 'fun f(x: Any) -> Int ! pure { return 1; }', ('--check',), 'only Int and Bool')
        compile_case('callback', 'fun f(g: () -> Int) -> Int ! pure { return g(); }', ('--check',), 'only Int and Bool')
        compile_case('bad_contract', 'fun f() -> Int ! deterministic { return 1; }', ('--check',), 'unsupported behavior')
        compile_case('word_not', 'fun f() -> Int not pure { return 1; }', ('--check',), 'requires ! pure')
        for binding in ['let innocent = noisy;', 'let [innocent] = [noisy];',
                        'let {nested: [innocent]} = {"nested": [noisy]};']:
            compile_case('shadowed', 'fun innocent() -> Int ! pure { return 1; } '
                         'fun noisy() -> Int { print(99); return 0; } ' + binding
                         + ' fun caller() -> Int ! pure { return innocent(); }',
                         ('--check',), 'MB-EFFECT-001')
        (work / 'helper.may').write_text('pub fun twice(x: Int) -> Int ! pure { return x*2; }')
        binary = compile_case('imported', 'import "helper.may"; fun f() -> Int ! pure { return twice(21); } print(f());')
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        assert (result.returncode, result.stdout) == (0, '42\n'), result
    print('behavior contracts: passed')


if __name__ == '__main__':
    main()
