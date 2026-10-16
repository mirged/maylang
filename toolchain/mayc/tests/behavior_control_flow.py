#!/usr/bin/env python3
"""Validate private scalar state, while loops, scopes and effect propagation."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-behavior-control-') as directory:
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

        programs = {
            'empty_control': ('''fun root() -> Int ! pure {
    if (false) {} else {}
    unless (false) {} else {}
    while (false) {}
    return 1;
}
let empty: Map<Str, Int> = {};
for n: Int in 0..2 {}
print(root(), len(empty));
''', '1 0\n'),
            'sum': ('''fun sum_to(n: Int) -> Int ! pure {
    mut total: Int = 0;
    while (n > 0) { total += n; n -= 1; }
    return total;
}
let n: Int = 6; print(sum_to(n), n);
''', '21 6\n'),
            'nested': ('''fun root() -> Int ! {} {
    mut total: Int = 0;
    mut i: Int = 0;
    while (i < 4) {
        i += 1;
        if (i == 2) { continue; }
        mut j: Int = 0;
        while (true) { j += 1; if (j == 3) { break; } total += i; }
    }
    return total;
}
print(root());
''', '16\n'),
            'float': ('''fun root() -> Float ! pure {
    mut value: Float = 1.5;
    mut active: Bool = true;
    while (active) { value *= 2.0; value /= 1.5; active = false; }
    return value;
}
print(root());
''', '2.0\n'),
            'scope': ('''fun root() -> Int ! pure {
    mut x: Int = 1;
    { let x: Int = 9; if (x != 9) { return 0; } }
    while (x < 2) { x = 2; let x: Int = 7; }
    if (true) { x += 3; } else { x = 99; }
    return x;
}
print(root());
''', '5\n'),
            'body_output': ('''fun helper() -> Int {
    mut n: Int = 0;
    while (n < 2) { print(n); n += 1; }
    return n;
}
fun root() -> Int ! {output} { return helper(); }
root();
''', '0\n1\n'),
        }
        targets = [()]
        if args.llvm:
            targets.append(('--target', 'clang-llvm'))
        for target, options in enumerate(targets):
            for name, (text, expected) in programs.items():
                check(f'{name}_{target}', text, output=expected, options=options)

        failures = [
            ('global_write', 'shared = 1; return 0;', 'assignment to global or captured value `shared`'),
            ('global_compound', 'shared += 1; return 0;', 'assignment to global or captured value `shared`'),
            ('global_read', 'mut x: Int = shared; return x;', 'global or captured value `shared`'),
            ('immutable', 'let x: Int = 1; x = 2; return x;', 'immutable local `x`'),
            ('immutable_in_block', 'let x: Int = 1; { x += 1; } return x;', 'immutable local `x`'),
            ('shadow_immutable', 'mut x: Int = 1; { let x: Int = 2; x = 3; } return x;', 'immutable local `x`'),
            ('loop_scope', 'while (false) mut shared: Int = 1; return shared;', 'global or captured value `shared`'),
            ('loop_scope_write', 'while (false) mut shared: Int = 1; shared = 2; return 0;', 'assignment to global'),
            ('branch_scope', 'if (false) mut shared: Int = 1; shared = 2; return 0;', 'assignment to global'),
            ('loop_initializer', 'while (false) { mut shared: Int = shared; } return 0;', 'global or captured value'),
            ('dead_body', 'while (false) { print(1); } return 0;', 'effect `output`'),
            ('after_break', 'while (true) { break; print(1); } return 0;', 'effect `output`'),
            ('after_continue', 'while (true) { continue; print(1); } return 0;', 'effect `output`'),
            ('dead_unknown', 'while (false) { syscall(39); } return 0;', 'MB-EFFECT-001'),
            ('assignment_effect', 'mut x: Int = 0; x = time(); return x;', 'effect `clock`'),
            ('condition_effect', 'while (clock() < 0.0) {} return 0;', 'effect `clock`'),
            ('indirect_mutable', 'mut time: Int = 1; return time();', 'indirect calls'),
            ('indirect_immutable', 'let time: Int = 1; return time();', 'indirect calls'),
            ('wrong_type', 'mut x: Int = 1; x = false; return x;', 'expected Int'),
            ('wrong_condition', 'while (1) {} return 0;', 'expected Bool'),
            ('break_outside', 'break; return 0;', 'enclosing while loop'),
            ('continue_outside', 'continue; return 0;', 'enclosing while loop'),
            ('break_after_loop', 'while (false) {} break; return 0;', 'enclosing while loop'),
            ('collection', 'for x: Int in 0..3 {} return 0;', 'supported scalar behavior subset'),
            ('map_body', 'while (false) {"value": 1} return 0;', 'supported scalar behavior subset'),
            ('empty_map_value', 'let x: Int = {}; return 0;', 'supported scalar behavior subset'),
            ('indexed_write', 'shared[0] = 1; return 0;', 'supported scalar behavior subset'),
            ('member_write', 'shared.value = 1; return 0;', 'supported scalar behavior subset'),
        ]
        for name, body, error in failures:
            check(name, 'mut shared: Int = 7; fun root() -> Int ! pure {' + body + '}', error=error)
        check('condition_call', 'fun predicate() -> Bool { print(1); return false; } '
              'fun root() -> Int ! pure { while (predicate()) {} return 0; }',
              error='call path: root -> predicate -> print]')
        check('callee_loop_depth', 'fun helper() -> Int { break; return 0; } '
              'fun root() -> Int ! pure { while (false) { helper(); } return 0; }',
              error='enclosing while loop')
        check('infinite', 'fun root() -> Int ! pure { while (true) {} return 0; }', options=('--check',))
        check('legacy', programs['sum'][0], error='requires strict', options=('--legacy', '--check'))
        check('raw', programs['sum'][0], options=('--raw', '--check'))

        (work / 'dep.may').write_text('pub fun looped(n: Int) -> Int {'
            'mut out: Int = 0; while (n > 0) { out += n; n -= 1; } return out; }')
        check('import', 'import "dep.may" as d; '
              'fun root() -> Int ! pure { return d.looped(5); } print(root());', output='15\n')

        source = work / 'report.may'
        source.write_text('fun helper() -> Bool { print(1); return false; } '
            'fun root() -> Int ! {clock, output} {'
            'mut value: Int = 0; while (helper()) { value = time(); } return value; }')
        artifact = work / 'preserved'
        artifact.write_bytes(b'keep')
        command = [str(compiler), '--explain-behavior', str(source), '-o', str(artifact)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0 and not result.stderr, result
        summaries = {entry['name']: entry for entry in json.loads(result.stdout)['functions']}
        assert summaries['root']['inferred_effects'] == ['clock', 'output'], summaries
        assert summaries['helper']['inferred_effects'] == ['output'], summaries
        source.write_text(source.read_text().replace('! {clock, output}', '! pure'))
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode != 0 and not result.stdout and 'MB-EFFECT-001' in result.stderr, result
        assert artifact.read_bytes() == b'keep'
    print(f'behavior control flow: {count} passed')


if __name__ == '__main__':
    main()
