#!/usr/bin/env python3
"""Check callable source contracts, effect composition and laundering boundaries."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


PURE = 'fun apply(f: Fn(Int) -> Int ! pure, n: Int) -> Int ! pure { return f(n); }\n'
ZERO = 'fun apply(f: Fn() -> Int ! pure) -> Int ! pure { return f(); }\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-callbacks-') as directory:
        work = Path(directory)

        def check(name, text, *, output=None, error=False, options=()):
            nonlocal count
            source = work / (name + '.may')
            source.write_text(text)
            binary = work / name
            result = subprocess.run([str(compiler), *options, str(source), '-o', str(binary)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=180)
            if error:
                assert result.returncode != 0 and not result.stdout, (name, result)
                if isinstance(error, str):
                    assert error in result.stderr, (name, result)
                assert not binary.exists(), name
            else:
                assert result.returncode == 0, (name, result)
                if output is not None:
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    assert (result.returncode, result.stdout, result.stderr) == (0, output, ''), (name, result)
            count += 1

        programs = {
            'pure': (PURE + 'fun twice(n: Int) -> Int { return n * 2; } print(apply(twice, 21));', '42\n'),
            'output': ('fun apply(f: Fn(Int) -> Int ! {output}, n: Int) -> Int ! {output} { return f(n); } '
                'fun log(n: Int) -> Int { print(n); return n; } apply(log, 42);', '42\n'),
            'clock': ('fun apply(f: Fn() -> Float ! {clock}) -> Bool ! {clock} { return f() >= 0.0; } '
                'fun sample() -> Float { return clock(); } print(apply(sample));', 'true\n'),
            'local': ('fun twice(n: Int) -> Int { return n * 2; } '
                'fun root() -> Int ! pure { let f: Fn(Int) -> Int ! pure = twice; return f(21); } print(root());', '42\n'),
            'mutable': ('fun one() -> Int { return 1; } fun two() -> Int { return 2; } '
                'fun root() -> Int ! pure { mut f: Fn() -> Int ! pure = one; f = two; return f(); } print(root());', '2\n'),
            'returned': ('fun twice(n: Int) -> Int { return n * 2; } '
                'fun make() -> Fn(Int) -> Int ! pure ! pure { return twice; } '
                'fun root() -> Int ! pure { let f: Fn(Int) -> Int ! pure = make(); return f(21); } print(root());', '42\n'),
            'higher_order': ('fun zero() -> Int { return 42; } '
                'fun consumer(f: Fn() -> Int ! {output}) -> Int ! {output} { return f(); } '
                'fun run(f: Fn(Fn() -> Int ! pure) -> Int ! {output}) -> Int ! {output} { return f(zero); } '
                'print(run(consumer));', '42\n'),
            'primitive_shadow': ('fun answer() -> Int { return 42; } '
                'fun root(time: Fn() -> Int ! pure) -> Int ! pure { return (time)(); } print(root(answer));', '42\n'),
            'generic_pure': (ZERO + 'fun choose<T>(a: T, b: T) -> T { return b; } '
                'fun one() -> Int { return 1; } fun two() -> Int { return 2; } '
                'let selected: Fn() -> Int ! pure = choose(one, two); print(apply(selected));', '2\n'),
            'recursive': ('fun repeat(f: Fn() -> Int ! {output}, n: Int) -> Int ! {output} {'
                'if (n > 0) { return repeat(f, n - 1); } return f(); } '
                'fun log() -> Int { print(42); return 0; } repeat(log, 2);', '42\n'),
        }
        targets = [()]
        if args.llvm:
            targets.append(('--target', 'clang-llvm'))
        for target, options in enumerate(targets):
            for name, (program, expected) in programs.items():
                check(f'{name}_{target}', program, output=expected, options=options)

        failures = {
            'argument': PURE + 'fun noisy(n: Int) -> Int { print(n); return n; } apply(noisy, 1);',
            'unannotated_boundary': 'fun use(f: Fn() -> Int ! pure) -> Int { return f(); } '
                'fun noisy() -> Int { print(1); return 1; } use(noisy);',
            'local_assignment': 'fun noisy() -> Int { print(1); return 1; } let f: Fn() -> Int ! pure = noisy;',
            'reassignment': 'fun pure() -> Int { return 1; } fun noisy() -> Int { print(1); return 1; } '
                'mut f: Fn() -> Int ! pure = pure; f = noisy;',
            'return': 'fun noisy() -> Int { print(1); return 1; } '
                'fun make() -> Fn() -> Int ! pure { return noisy; }',
            'call_ceiling': 'fun use(f: Fn() -> Int ! {output}) -> Int ! pure { return f(); }',
            'wider_parameter': ZERO + 'fun wide() -> Int ! {output} { return 1; } apply(wide);',
            'clock_to_output': 'fun use(f: Fn() -> Int ! {output}) -> Int { return f(); } '
                'fun sample() -> Int { return time(); } use(sample);',
            'unknown_function': ZERO + 'fun unknown() -> Int { return syscall(39); } apply(unknown);',
            'unknown_type': ZERO + 'fun unknown(x: Any) -> Int { return 1; } apply(unknown);',
            'erased': ZERO + 'fun pure() -> Int { return 1; } let erased: Fn() -> Int = pure; apply(erased);',
            'any': ZERO + 'fun pure() -> Int { return 1; } let erased: Any = pure; apply(erased);',
            'any_return': ZERO + 'fun pure() -> Int { return 1; } fun erased() -> Any { return pure; } apply(erased());',
            'closure': ZERO + 'let f: Fn() -> Int ! pure = fun() -> Int { return 1; }; apply(f);',
            'primitive_value': 'fun use(f: Fn() -> Float ! pure) -> Float ! pure { return f(); } use(pi);',
            'shared_annotation': 'let fs: List<Fn() -> Int ! pure> = [];',
            'shared_inferred': ZERO + 'fun pure() -> Int { return 1; } let fs = [pure]; apply(fs[0]);',
            'shared_generic': ZERO + 'fun box<T>(x: T) -> List<T> { return [x]; } '
                'fun pure() -> Int { return 1; } let fs = box(pure); apply(fs[0]);',
            'shared_record': 'struct Box { f: Fn() -> Int ! pure }',
            'shared_enum': 'enum Box { Some(f: Fn() -> Int ! pure) }',
            'foreign_result': 'extern "unused-callback.so" { fun value() -> Fn() -> Int ! pure; }',
            'foreign_argument': 'extern "unused-callback.so" { fun use(f: Fn() -> Int ! pure) -> Int; }',
            'generic_selection': ZERO + 'fun choose<T>(a: T, b: T) -> T { return b; } '
                'fun pure() -> Int { return 1; } fun noisy() -> Int { print(1); return 1; } '
                'let selected: Fn() -> Int ! pure = choose(pure, noisy); apply(selected);',
            'generic_revalidation': 'fun consume(f: Fn() -> Int ! pure) -> Int { return f(); } '
                'fun combine<T>(f: Fn(T) -> Int, a: T, b: T) -> Int { return f(b); } '
                'fun pure() -> Int { return 1; } fun noisy() -> Int { print(1); return 1; } combine(consume, pure, noisy);',
            'nested_variance': 'fun consume(f: Fn() -> Int ! pure) -> Int ! pure { return f(); } '
                'fun use(f: Fn(Fn() -> Int ! {output}) -> Int ! pure) -> Int { return 0; } use(consume);',
            'unknown_cycle': ZERO + 'fun a() -> Int { return b(); } '
                'fun b() -> Int { syscall(39); return a(); } apply(a);',
            'missing_row': 'fun use(f: Fn() -> Int) -> Int ! pure { return f(); }',
            'unknown_effect': 'fun use(f: Fn() -> Int ! {network}) -> Int { return 0; }',
            'effect_variable': 'fun use(f: Fn() -> Int ! E) -> Int { return 0; }',
        }
        for name, program in failures.items():
            check(name, program, error=True)
        check('legacy', programs['pure'][0], error='requires strict', options=('--legacy', '--check'))
        check('type_only_legacy', 'let f: Fn() -> Int ! pure = 1;', error='requires strict', options=('--legacy', '--check'))
        (work / 'dep.may').write_text('pub fun twice(n: Int) -> Int { return n * 2; }')
        check('import', 'import "dep.may" as d; ' + PURE + 'print(apply(d.twice, 21));', output='42\n')
        check('local_module_shadow', 'import "dep.may" as d; ' + PURE +
              'fun root(d: Int) -> Int ! pure { return apply(d.twice, 1); }', error='shadowed module alias')
        check('global_module_shadow', 'import "dep.may" as d; ' + PURE +
              'fun noisy(n: Int) -> Int { print(n); return n; } '
              'let erased: Fn(Int) -> Int = noisy; let d: Any = {"twice": erased}; apply(d.twice, 1);', error=True)

        source = work / 'report.may'
        source.write_text(programs['pure'][0] + '\nfun ignored() -> Int { return syscall(39); }')
        artifact = work / 'preserved'
        artifact.write_bytes(b'keep')
        command = [str(compiler), '--explain-behavior', str(source), '-o', str(artifact)]
        first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert first.returncode == 0 and not first.stderr, first
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert first.stdout == second.stdout and second.returncode == 0, second
        data = json.loads(first.stdout)
        assert data['scope'] == 'scalar_callable_effects_v1' and data['analysis_roots'] == 'all_source_functions', data
        entries = {entry['name']: entry for entry in data['functions']}
        assert set(entries) == {'apply', 'twice'}, data
        assert all(entry['inferred_effects'] == [] for entry in entries.values()), data
        source.write_text(failures['generic_selection'])
        failed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert failed.returncode != 0 and not failed.stdout, failed
        assert artifact.read_bytes() == b'keep'
    print(f'behavior callbacks: {count} passed')


if __name__ == '__main__':
    main()
