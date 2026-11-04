#!/usr/bin/env python3
"""Check Float behavior contracts and the audited pure scalar primitives."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
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
            ('math_unknown', 'return to_float(cmp(1, 2));', 'MB-EFFECT-001'),
            ('conversion_unknown', 'return to_float(clamp(1, 0, 2));', 'MB-EFFECT-001'),
            ('int_power_unknown', 'return to_float(2 ** 3);', '`**` requires a Float operand'),
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

        # Audited numeric primitives: one Int or Float argument whose type the
        # behavior checker establishes, an empty row, and the runtime results.
        check('numeric_rules', '''fun half(x: Int) -> Float { return to_float(x) / 2.0; }
fun root(x: Float, n: Int) -> Bool ! pure {
    let a: Float = floor(x) + ceil(x) + round(x) + sqrt(4.0) + float(n) + half(n);
    let b: Int = int(x) + trunc(x * 2.0) + abs(0 - n) + int(n);
    let c: Float = abs(-2.5) + floor(n) + sqrt(n) + round(-2.5);
    return a == 16.0 and b == 15 and c == 6.5;
}
print(root(2.5, 4));
''', output='true\n')
        # Rounding is total on Float; int, trunc and abs raise the same catchable
        # arithmetic fault as overflow, which this fragment does not model as an effect.
        check('numeric_edges', '''fun edges() -> Int ! pure {
    let nan: Float = sqrt(-1.0);
    let big: Float = 1.0e308 * 10.0;
    mut ok: Int = 0;
    if (floor(nan) != floor(nan) and round(nan) != round(nan) and abs(nan) != abs(nan)) { ok += 1; }
    if (floor(big) == big and ceil(0.0 - big) == 0.0 - big and abs(-0.0) == 0.0) { ok += 1; }
    if (int(-3.9) == -3 and trunc(3.9) == 3 and round(0.49999999999999994) == 0.0) { ok += 1; }
    return ok;
}
fun overflow() -> Int ! pure { return abs(-9223372036854775807 - 1); }
fun outside(x: Float) -> Int ! pure { return trunc(x); }
fun invalid(x: Float) -> Int ! pure { return int(sqrt(x)); }
print(edges());
let a: Int = may { overflow() } otherwise { print(err.kind); 0 };
let b: Int = may { outside(1.0e308 * 10.0) } otherwise { print(err.kind); 0 };
let c: Int = may { invalid(-1.0) } otherwise { print(err.kind); 0 };
''', output='3\narithmetic\narithmetic\narithmetic\n')
        for name in ['to_float', 'float', 'int', 'trunc', 'floor', 'ceil', 'round', 'sqrt', 'abs',
                     'sin', 'cos', 'tan', 'ln', 'log2', 'log10', 'exp']:
            for contract in ['', ' ! pure', ' ! {clock, output}']:
                check(f'numeric_{name}_{len(contract)}',
                      f'fun root(x: Float) -> Bool{contract} {{ return to_float({name}(x)) == to_float({name}(x)); }} '
                      'print(root(2.25));', output='true\n')
            # Argument types the checker cannot establish fail closed, including
            # Bool, which strict typing accepts for int and to_float.
            for label, argument in [('bool', 'true'), ('compare', '1 < 2'), ('logic', 'x > 0.0 and true'),
                                    ('callable', 'f'), ('nil_call', 'print(1)')]:
                check(f'numeric_{name}_{label}', 'fun g(x: Int) -> Int { return x; } '
                      'fun root(x: Float) -> Float ! {output} { let f: Fn(Int) -> Int ! pure = g; '
                      f'return to_float({name}({argument})); }}',
                      error='requires an Int or Float argument', options=('--check',))
            check(f'numeric_{name}_arity', f'fun root() -> Float ! pure {{ return to_float({name}(1, 2)); }}',
                  error='expects one argument', options=('--check',))
            check(f'numeric_{name}_argument_effect', 'fun noisy() -> Float { print(1); return 1.0; } '
                  f'fun root() -> Float ! pure {{ return to_float({name}(noisy())); }}',
                  error='call path: root -> noisy -> print]')
            check(f'numeric_{name}_clock',
                  f'fun root() -> Float ! {{clock}} {{ return to_float({name}(clock())); }}',
                  options=('--check',))
            check(f'numeric_{name}_clock_missing',
                  f'fun root() -> Float ! pure {{ return to_float({name}(time())); }}',
                  error='effect `clock`')
            check(f'numeric_{name}_shadow_source', f'fun {name}(x: Float) -> Float {{ print(1); return x; }} '
                  f'fun root() -> Float ! pure {{ return {name}(1.0); }}',
                  error=f'call path: root -> {name} -> print]')
            check(f'numeric_{name}_shadow_global', f'let {name}: Float = 1.0; '
                  f'fun root() -> Float ! pure {{ return to_float({name}(1.0)); }}',
                  error='unknown behavior through a global binding')
            check(f'numeric_{name}_shadow_local',
                  f'fun root({name}: Float) -> Float ! pure {{ return to_float({name}(1.0)); }}',
                  error='indirect calls')
        (work / 'numbers.may').write_text('pub fun sqrt(x: Float) -> Float { print(3); return x; }')
        check('numeric_shadow_import', 'import "numbers.may" as n; '
              'fun root() -> Float ! pure { return n.sqrt(4.0); }', error='call path: root -> sqrt -> print]')
        check('numeric_shadow_unqualified_import', 'import "numbers.may"; '
              'fun root() -> Float ! pure { return sqrt(4.0); }', error='call path: root -> sqrt -> print]')
        # Established result types feed outer arguments; abs keeps its argument's type.
        check('numeric_nested', 'fun root(n: Int) -> Int ! pure { '
              'return int(sqrt(to_float(abs(n)))) + trunc(floor(2.5)); } print(root(-16));', output='6\n')

        # Transcendentals never fault: NaN and infinities pass through or saturate.
        check('transcendental_edges', """fun edges() -> Bool ! pure {
    let nan: Float = sqrt(-1.0);
    let big: Float = 1.0e308 * 10.0;
    let a: Bool = sin(big) != sin(big) and cos(nan) != cos(nan) and tan(big) != tan(big);
    let b: Bool = ln(0.0) == 0.0 - big and ln(-1.0) != ln(-1.0) and log2(8) == 3.0 and log10(1000) == 3.0;
    let c: Bool = exp(1000.0) == big and exp(-1000.0) == 0.0 and exp(0) == 1.0 and ln(big) == big;
    return a and b and c;
}
print(edges());
""", output='true\n')
        # pow takes two numbers and always returns a Float; ** with a Float operand
        # is the same total operation. Int ** Int stays unknown.
        check('pow_rules', """fun root(x: Float, n: Int) -> Bool ! pure {
    let big: Float = 1.0e308 * 10.0;
    let a: Bool = pow(2, 10) == 1024.0 and pow(x, 2) == 6.25 and pow(0.0, -1.0) == big;
    let b: Bool = x ** 2 == 6.25 and 2 ** x > 5.65 and 4.0 ** -1 == 0.25 and n ** 0.5 == 2.0;
    let c: Bool = pow(-8.0, 1.0 / 3.0) != pow(-8.0, 1.0 / 3.0) and pow(1.0, sqrt(-1.0)) == 1.0;
    return a and b and c;
}
print(root(2.5, 4));
""", output='true\n')
        # min/max need two arguments of one type and return one of them: the first
        # on ties, and NaN compares greater than everything.
        check('min_max_rules', """fun root(n: Int, x: Float) -> Bool ! pure {
    let nan: Float = sqrt(-1.0);
    let a: Bool = min(n, 3) == 3 and max(n, 3) == n and min(x, 1.0) == 1.0 and max(0 - x, -9.5) == 0.0 - x;
    let b: Bool = min(nan, 1.0) == 1.0 and min(1.0, nan) != min(1.0, nan) and max(1.0, nan) == 1.0;
    let c: Bool = min(-0.0, 0.0) ** -1.0 < 0.0 and min(0.0, -0.0) ** -1.0 > 0.0;
    let i: Int = min(n, 3) + max(n, 3);
    return a and b and c and i == n + 3;
}
print(root(7, 2.5));
""", output='true\n')
        # bool is truthiness: every Int and Float, including 0, 0.0 and NaN, is true.
        check('bool_rules', """fun root(n: Int) -> Bool ! pure {
    return bool(n) and bool(0) and bool(0.0) and bool(sqrt(-1.0)) and bool(true) and not bool(false) and bool(n < 1);
}
print(root(0));
""", output='true\n')
        for label, body, error in [
            ('min_mixed', 'return to_float(min(1, 2.0));', 'requires arguments of the same type, found Int and Float'),
            ('max_mixed', 'return to_float(max(x, n));', 'requires arguments of the same type, found Float and Int'),
            ('min_bool', 'return to_float(min(true, false));', 'requires Int or Float arguments'),
            ('pow_bool', 'return pow(true, 1.0);', 'requires Int or Float arguments'),
            ('pow_callable', 'return pow(1.0, f);', 'requires Int or Float arguments'),
            ('pow_arity', 'return pow(1.0);', '`pow` expects 2 arguments'),
            ('max_arity', 'return to_float(max(1, 2, 3));', '`max` expects 2 arguments'),
            ('bool_callable', 'if (bool(f)) { return 1.0; } return 0.0;', 'requires an Int, Float or Bool argument'),
            ('bool_arity', 'if (bool(1, 2)) { return 1.0; } return 0.0;', '`bool` expects one argument'),
            ('power_bool', 'return to_float(true ** 2.0);', '`**` requires a Float operand'),
            ('power_unknown', 'return 2.0 ** to_float(cmp(1, 2));', 'MB-EFFECT-001'),
        ]:
            check('numeric_' + label, 'fun g(x: Int) -> Int { return x; } '
                  'fun root(x: Float, n: Int) -> Float ! {output} { let f: Fn(Int) -> Int ! pure = g; ' + body + ' }',
                  error=error, options=('--check',))
        for name, body, noisy in [('pow', 'return pow(2.0, 1.0);', 'return pow(2.0, noisy());'),
                                  ('min', 'return to_float(min(1, 2));', 'return to_float(min(1, noisy()));'),
                                  ('max', 'return to_float(max(1, 2));', 'return to_float(max(1, noisy()));'),
                                  ('bool', 'if (bool(1)) { return 1.0; } return 0.0;',
                                   'if (bool(noisy())) { return 1.0; } return 0.0;')]:
            # Effects in a later argument still count.
            check(f'two_{name}_second_effect', 'fun noisy() -> Int { print(1); return 1; } '
                  f'fun root() -> Float ! pure {{ {noisy} }}',
                  error='call path: root -> noisy -> print]')
            check(f'two_{name}_shadow_global', f'let {name}: Float = 1.0; '
                  f'fun root() -> Float ! pure {{ {body} }}',
                  error='unknown behavior through a global binding')
        for name, decl, body in [
                ('min', 'fun min(a: Int, b: Int) -> Int { print(1); return a; }', 'return to_float(min(1, 2));'),
                ('pow', 'fun pow(a: Float, b: Float) -> Float { print(1); return a; }', 'return pow(1.0, 2.0);'),
                ('bool', 'fun bool(a: Int) -> Bool { print(1); return true; }', 'if (bool(1)) { return 1.0; } return 0.0;')]:
            check(f'two_{name}_shadow_source', decl + f' fun root() -> Float ! pure {{ {body} }}',
                  error=f'call path: root -> {name} -> print]')
        check('power_effect', 'fun noisy() -> Float { print(1); return 1.0; } '
              'fun root() -> Float ! pure { return 2.0 ** noisy(); }', error='call path: root -> noisy -> print]')
        check('power_clock', 'fun root() -> Float ! {clock} { return clock() ** 0.0; } print(root());', output='1.0\n')

        source = work / 'report.may'
        source.write_text('fun root() -> Float ! pure { return pi() + e() + floor(1.5) + sqrt(to_float(abs(-4))); }')
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
