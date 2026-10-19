#!/usr/bin/env python3
"""Validate effect ceilings, recursive propagation, and unknown-call rejection."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    compiler = compiler_binary(parser.parse_args().compiler)
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-effects-') as directory:
        work = Path(directory)

        def check(name, text, error=None, output=None, options=()):
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

        check('documented_example', (ROOT / 'examples/behavior.may').read_text(), output='42\n')
        check('empty', 'fun f(n: Int) -> Int ! {} { return n*2; } print(f(21));', output='42\n')
        check('output', 'fun f(n: Int) -> Int ! {output} { print(n); return n; } f(42);', output='42\n')
        check('clock', 'fun f() -> Int ! {clock} { return time(); }', options=('--check',))
        check('clock_float', 'fun f() -> Bool ! {clock} { return clock() >= 0.0; } print(f());', output='true\n')
        check('rows_normalize', 'fun f() -> Int ! {output, clock, output,} { print(time()); return 1; }', options=('--check',))
        check('wider_ceiling', 'fun f() -> Int ! {output, clock} { return 42; } print(f());', output='42\n')
        check('transitive', 'fun leaf() -> Int { print(42); return 1; } '
              'fun root() -> Int ! {output} { return leaf(); } root();', output='42\n')
        check('recursive', 'fun a(n: Int) -> Int ! {output} { if(n>0) { return b(n-1); } print(n); return n; } '
              'fun b(n: Int) -> Int { return a(n); } a(2);', output='0\n')
        check('missing_output', 'fun f() -> Int ! {clock} { print(1); return time(); }',
              'effect `output` exceeds declared ceiling [clock]')
        check('missing_clock', 'fun f() -> Int ! {output} { print(time()); return 1; }',
              'effect `clock` exceeds declared ceiling [output]')
        check('pure_clock', 'fun f() -> Int ! pure { return time(); }', 'effect `clock`')
        check('empty_output', 'fun f() -> Int ! {} { print(1); return 0; }', 'effect `output`')
        check('hidden_branch', 'fun f() -> Int ! {} { if(false) { print(1); } return 0; }', 'effect `output`')
        check('cycle_fixed_point',
              'fun a(n: Int) -> Int ! {output} { b(n); print(n); return n; } '
              'fun b(n: Int) -> Int { if(n>0) { return a(n-1); } return 0; } '
              'fun root() -> Int ! pure { return b(0); }', 'call path: root -> b -> a -> print')
        check('callee_ceiling', 'fun root() -> Int ! {output} { return leaf(); } '
              'fun leaf() -> Int ! pure { print(1); return 0; }', 'ceiling [] of `leaf`')
        check('shortest_witness',
              'fun long_path() -> Int ! {output} { return middle(); } '
              'fun root() -> Int ! pure { return long_path() + short_path(); } '
              'fun middle() -> Int { print(1); return 0; } '
              'fun short_path() -> Int { print(2); return 0; }',
              'call path: root -> short_path -> print]')
        check('shortest_witness_propagates',
              'fun long_path() -> Int ! {output} { return middle(); } '
              'fun root() -> Int ! pure { return helper(); } '
              'fun helper() -> Int { return long_path() + short_path(); } '
              'fun middle() -> Int { print(1); return 0; } '
              'fun short_path() -> Int { print(2); return 0; }',
              'call path: root -> helper -> short_path -> print]')
        check('shortest_recursive_witness',
              'fun a(n: Int) -> Int ! {output} { return b(n); } '
              'fun root() -> Int ! pure { return a(1) + short_path(); } '
              'fun b(n: Int) -> Int { if(n>0) { return a(n-1); } print(1); return 0; } '
              'fun short_path() -> Int { print(2); return 0; }',
              'call path: root -> short_path -> print]')
        check('equal_witness_uses_first_call',
              'fun root() -> Int ! pure { return first() + second(); } '
              'fun first() -> Int { print(1); return 0; } '
              'fun second() -> Int { print(2); return 0; }',
              'call path: root -> first -> print]')
        check('argument_effect', 'fun f(x: Int) -> Int { return x; } '
              'fun root() -> Int ! {clock} { return f(print(1)); }', 'effect `output`')
        check('global_primitive', 'let time = fun() -> Int { return 0; }; '
              'fun root() -> Int ! {clock} { return time(); }', 'unknown behavior through a global binding')
        check('local_primitive', 'fun root(time: Int) -> Int ! {clock} { return time(); }', 'indirect calls')
        check('user_primitive_name', 'fun time() -> Int { return 42; } '
              'fun root() -> Int ! pure { return time(); } print(root());', output='42\n')
        for effect in ['network', 'alloc', 'unknown', 'guarded', 'pure']:
            check('unsupported_' + effect, 'fun f() -> Int ! {' + effect + '} { return 1; }', 'unsupported behavior effect')
        for name, body in [('syscall', 'return syscall(39);'), ('indirect', 'return (fun() -> Int { return 0; })();'),
                           ('global', 'return x;'), ('mutation', 'x = 0; return x;')]:
            check('unknown_' + name, 'let x: Int = 42; fun f() -> Int ! {output, clock} {' + body + '}', 'MB-EFFECT-001')
        # These calls type-check without a contract, but none has a behavior
        # rule yet. Even the widest supported ceiling must reject each one.
        # Check only: never execute process, memory, file or scheduler calls.
        primitive_calls = [
            ('read_stdin', 'read_stdin()'), ('env', 'env("HOME")'),
            ('read_file', 'read_file("missing")'), ('write_file', 'write_file("unused", "")'),
            ('file_exists', 'file_exists("missing")'), ('read_dir', 'read_dir(".")'),
            ('input', 'input("")'), ('args', 'args()'),
            ('exit', 'exit(0)'), ('sleep', 'sleep(1)'), ('yield', 'yield()'), ('run', 'run()'),
            ('exec', 'exec(["unused"])'), ('wait', 'wait(1)'),
            ('addr', 'addr(1)'), ('load64', 'load64(0)'), ('store64', 'store64(0, 0)'),
            ('fail', 'fail("failure")'), ('int', 'int(1)'), ('abs', 'abs(1)'),
            ('sqrt', 'sqrt(1)'),
        ]
        for name, call in primitive_calls:
            body = '{ ' + call + '; return 0; }'
            check('unannotated_primitive_' + name, 'fun f() -> Int ' + body, options=('--check',))
            check('unknown_primitive_' + name, 'fun f() -> Int ! {output, clock} ' + body,
                  'MB-EFFECT-001', options=('--check',))
        check('legacy', 'fun f() -> Int ! {output} { print(1); return 1; }', 'requires strict', options=('--legacy', '--check'))
        (work / 'dep.may').write_text('pub fun log(n: Int) -> Int ! {output} { print(n); return n; }')
        check('import_allowed', 'import "dep.may" as d; fun f() -> Int ! {output} { return d.log(42); } f();', output='42\n')
        check('import_ceiling', 'import "dep.may" as d; fun f() -> Int ! {} { return d.log(42); }', 'call path: f -> log -> print')
    print(f'effect rows: {count} passed')


if __name__ == '__main__':
    main()
