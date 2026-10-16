#!/usr/bin/env python3
"""Exercise list type/index traps and valid mutations on full/core runtimes."""
import argparse
from pathlib import Path
import resource
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-list-guards-') as directory:
        work = Path(directory)

        def check(name, text, options, *, output=None, failure=None):
            nonlocal count
            source = work / (name + '.may')
            source.write_text(text)
            binary = work / name
            result = subprocess.run([str(compiler), *options, str(source), '-o', str(binary)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, (name, result)
            result = subprocess.run([str(binary)], cwd=work, capture_output=True, text=True,
                                    timeout=10, preexec_fn=no_core_dump)
            if failure:
                assert result.returncode == 70 and failure in result.stdout + result.stderr, (name, result)
                assert 'unreachable' not in result.stdout, (name, result)
            else:
                assert (result.returncode, result.stdout, result.stderr) == (0, output, ''), (name, result)
            count += 1

        targets = [('full', ()), ('core', ('--runtime', 'core'))]
        if args.llvm:
            targets.append(('llvm', ('--target', 'clang-llvm')))
        for target, options in targets:
            values = [('nil', 'nil'), ('zero', '0'), ('bool', 'true'), ('string', '"x"')]
            if target != 'core':
                values += [('float', '1.5'), ('map', '{}'), ('function', 'fun() -> Int { return 1; }')]
            for label, value in values:
                operations = ['push(bad, 1)', 'pop(bad)']
                if target == 'core':
                    operations.append('slice(bad, 0, 1)')
                for operation in operations:
                    name = operation.split('(')[0]
                    check(f'{target}_{name}_{label}', f'let bad: Any = {value}; {operation}; print("unreachable");',
                          options, failure='expected List')
            for label, index in [('negative', '-1'), ('end', '2'), ('far', '1000000'),
                                 ('bool', 'true'), ('nil', 'nil'), ('string', '"x"')]:
                check(f'{target}_set_{label}', f'let xs: Any = [1, 2]; let index: Any = {index}; '
                      'xs[index] = 9; print("unreachable");', options, failure='invalid list assignment')
            for label, index in [('bool', 'true'), ('nil', 'nil'), ('string', '"x"')]:
                check(f'{target}_get_{label}', f'let xs: Any = [1, 2]; let index: Any = {index}; '
                      'print(xs[index]); print("unreachable");', options, failure='index')
                check(f'{target}_string_get_{label}', f'let text: Any = "abc"; let index: Any = {index}; '
                      'print(text[index]); print("unreachable");', options, failure='index')
            check(f'{target}_set_nonlist', 'let bad: Any = 0; bad[0] = 1; print("unreachable");',
                  options, failure='assignment')
            check(f'{target}_valid', '''let xs: Any = [1, 2]; let alias: Any = xs;
xs[1] = 7; push(alias, 3); let last: Any = pop(alias);
print(xs, last, len(xs), xs[-1], xs[2]);
let empty: Any = []; let missing: Any = pop(empty); push(empty, 42);
print(missing, empty, slice(xs, -1, 100));
let text: Any = "aλ"; print(text[1], text[-1], text[2]);
''', options, output='[1, 7] 3 2 nil nil\nnil [42] [1, 7]\nλ nil nil\n')
            if target != 'core':
                check(f'{target}_float_index', 'let xs: Any = [1]; let i: Any = 0.5; xs[i] = 2;',
                      options, failure='invalid list assignment')
                check(f'{target}_float_get', 'let xs: Any = [1]; let i: Any = 0.5; print(xs[i]);',
                      options, failure='index')
                check(f'{target}_map_keys', 'let m: Any = {}; m[false] = 1; m[1.5] = 2; print(m[false], m[1.5]);',
                      options, output='1 2\n')
                check(f'{target}_recovery', '''let xs: Any = [1, 2];
let caught: Any = may { xs[2] = 3; false } otherwise { err.kind == "type" };
print(caught, xs);
fun answer() -> Int { return 42; }
fun apply(f: Fn() -> Int ! pure) -> Int ! pure { return f(); }
let f: Fn() -> Int ! pure = answer; let erased: Any = f;
let protected: Any = may { push(erased, 1); false } otherwise { err.kind == "type" };
print(protected, apply(f));
''', options, output='true [1, 2]\ntrue 42\n')
    print(f'list guards: {count} passed')


if __name__ == '__main__':
    main()
