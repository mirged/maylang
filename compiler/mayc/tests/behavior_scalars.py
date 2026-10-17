#!/usr/bin/env python3
"""Check Float behavior contracts and the explicitly pure pi/e primitives."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true', help='also execute with the LLVM backend')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-behavior-scalars-') as directory:
        work = Path(directory)

        def check(name, text, *, output=None, error=None, options=()):
            nonlocal count
            source = work / (name + '.may')
            source.write_text(text)
            binary = work / name
            result = subprocess.run([str(compiler), *options, str(source), '-o', str(binary)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=180)
            if error:
                assert result.returncode != 0 and error in result.stderr, (name, result)
                assert not binary.exists(), name
            else:
                assert result.returncode == 0, (name, result)
                if output is not None:
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    assert (result.returncode, result.stdout, result.stderr) == (0, output, ''), (name, result)
            count += 1

        numeric = '''fun scale(x: Float, n: Int) -> Float {
    let factor: Float = 1.25e2;
    return -x + factor / n;
}
fun root() -> Bool ! pure { return scale(0.5, 2) == 62.0; }
print(root());
'''
        targets = [()]
        if args.llvm:
            targets.append(('--target', 'clang-llvm'))
        for index, options in enumerate(targets):
            check(f'arithmetic_{index}', numeric, output='true\n', options=options)
            check(f'recursive_{index}', '''fun a(n: Int) -> Float {
    if (n == 0) { return 0.5; } return b(n - 1) + 0.5;
}
fun b(n: Int) -> Float { return a(n); }
fun root() -> Float ! {} { return a(3); }
print(root());
''', output='2.0\n', options=options)
            for name, low, high in [('pi', '3.14', '3.15'), ('e', '2.71', '2.72')]:
                body = f'{{ let x: Float = {name}(); return x > {low} and x < {high}; }}'
                for contract in ['', ' ! pure', ' ! {}', ' ! {clock, output}']:
                    check(f'constant_{name}_{index}_{len(contract)}',
                          f'fun root() -> Bool{contract} {body} print(root());',
                          output='true\n', options=options)
            check(f'clock_{index}', '''fun sampled() -> Float { return clock(); }
fun root() -> Bool ! {clock} { let now: Float = sampled(); return now >= 0.0; }
print(root());
''', output='true\n', options=options)

        check('clock_missing', 'fun sampled() -> Float { return clock(); } '
              'fun root() -> Float ! pure { return sampled(); }',
              error='call path: root -> sampled -> clock]')
        check('output_missing', 'fun root(x: Float) -> Float ! {clock} { print(x); return x; }',
              error='effect `output`')
        check('output_allowed', 'fun root(x: Float) -> Float ! {output} { print(x); return x; } root(1.25);',
              output='1.25\n')
        for name in ['pi', 'e']:
            check('shadow_source_' + name, f'fun {name}() -> Float {{ print(1); return 1.0; }} '
                  f'fun root() -> Float ! pure {{ return {name}(); }}',
                  error=f'call path: root -> {name} -> print]')
            check('shadow_pure_' + name, f'fun {name}() -> Float {{ return 42.5; }} '
                  f'fun root() -> Float ! pure {{ return ({name})(); }} print(root());', output='42.5\n')
            check('shadow_global_' + name, f'let {name}: Float = 1.0; '
                  f'fun root() -> Float ! pure {{ return {name}(); }}',
                  error='unknown behavior through a global binding')
            check('shadow_local_' + name,
                  f'fun root({name}: Float) -> Float ! pure {{ return {name}(); }}', error='indirect calls')
            check('shadow_extern_' + name, 'extern "unused-behavior.so" {'
                  f'fun {name}() -> Float; }} '
                  f'fun root() -> Float ! pure {{ return {name}(); }}',
                  error='native and runtime calls have unknown behavior', options=('--check',))
            check('arity_' + name, f'fun root() -> Float ! pure {{ return {name}(1); }}', error='argument')
            check('argument_effect_' + name, 'fun noisy() -> Int { print(1); return 1; } '
                  f'fun root() -> Float ! pure {{ return {name}(noisy()); }}',
                  error='call path: root -> noisy -> print]')
        (work / 'constants.may').write_text('pub fun pi() -> Float { print(3); return 3.0; }')
        check('shadow_import', 'import "constants.may" as c; '
              'fun root() -> Float ! pure { return c.pi(); }', error='call path: root -> pi -> print]')
        check('shadow_unqualified_import', 'import "constants.may"; '
              'fun root() -> Float ! pure { return pi(); }', error='call path: root -> pi -> print]')
        for name, body, error in [
            ('global', 'return shared;', 'global or captured value'),
            ('shared_mutation', 'mut x: Float = 0.0; shared = x; return x;', 'assignment to global'),
            ('math_unknown', 'return sqrt(pi());', 'MB-EFFECT-001'),
            ('conversion_unknown', 'return int(1.5);', 'MB-EFFECT-001'),
            ('wrong_return', 'return true;', 'expected Float'),
        ]:
            check(name, 'let shared: Float = 1.0; fun root() -> Float ! {output, clock} {' + body + '}',
                  error=error)
        for annotation in ['Any', 'Str', 'Float32', 'Float64', 'Float<Int>']:
            check('type_' + annotation.replace('<', '_').replace('>', ''),
                  f'fun root(x: {annotation}) -> Float ! pure {{ return 1.0; }}',
                  error='only Int, Bool and Float')
        check('wrong_int_return', 'fun root() -> Int ! pure { return 1.5; }', error='expected Int')
        check('missing_type', 'fun root(x) -> Float ! pure { return 1.0; }', error='requires explicit')
        check('legacy', numeric, error='requires strict', options=('--legacy', '--check'))
        check('raw', 'fun root(x: Float) -> Float ! pure { return x * 1.5; }', options=('--raw', '--check'))

        source = work / 'report.may'
        source.write_text('fun root() -> Float ! pure { return pi() + e(); }')
        result = subprocess.run([str(compiler), '--explain-behavior', str(source)],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0 and not result.stderr, result
        entries = json.loads(result.stdout)['functions']
        assert len(entries) == 1 and entries[0]['name'] == 'root', entries
        assert entries[0]['inferred_effects'] == entries[0]['declared_effects'] == [], entries
        assert entries[0]['classification'] == 'proven', entries
    print(f'behavior scalars: {count} passed')


if __name__ == '__main__':
    main()
