#!/usr/bin/env python3
"""Direct calls with register arguments (#132): fallback paths and parity.

A call to a function known at compile time with matching arity passes its
arguments in registers instead of building the argument vector: a fat callee's
parameters start in RDX/RAX, RDI/RSI and R8/R9, and a native-word callee's
payloads start in the SysV argument registers. The `direct_calls.may` fixture
covers the matching-arity path; this suite covers the cases around it:

- the argument-vector fallback for a legacy arity mismatch (extra and missing
  arguments), which valid strict source cannot express;
- a parameter of the wrong runtime type, reached through an `Any` parameter of
  a legacy program, so the callee's dynamic operation paths run;
- dynamic callees (function values) next to direct calls to the same function;
- callees that fault, caught at the call site;
- `--debug` source traces across a chain of direct calls, including an
  uncaught fault;
- arity and parameter type mismatches rejected by the strict checker.

Every case is compiled with and without --no-opt, and the two builds must
behave identically; the register convention must not change what a program
does.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def run(argv):
    return subprocess.run([str(item) for item in argv], cwd=ROOT,
                          capture_output=True, timeout=180)


def behave(compiler, source, options, binary):
    built = run([compiler, *options, source, '-o', binary])
    assert built.returncode == 0, (source.name, built.stdout.decode(), built.stderr.decode())
    ran = run([binary])
    return ran.returncode, ran.stdout, ran.stderr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-direct-calls-') as directory:
        work = Path(directory)
        cases = {
            # One, two and three fat parameters, a native-word body with six
            # parameters and native-word recursion.
            'matching': ('fun one(x: Any) -> Any { return x; }\n'
                         'fun two(a: Any, b: Any) -> Any { return [a, b]; }\n'
                         'fun add(a: Int, b: Int) -> Int { return a + b; }\n'
                         'fun add6(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int) -> Int {\n'
                         '    return a + b + c + d + e + f;\n'
                         '}\n'
                         'fun fib(n: Int) -> Int { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }\n'
                         'print(one(1), two(2, 3), add(4, 5), add6(1, 2, 3, 4, 5, 6), fib(10));\n',
                         (), (0, b'1 [2, 3] 9 21 55\n', b'')),
            # Extra arguments are evaluated and passed, then ignored by the
            # callee's argument-vector path.
            'legacy extra arguments': ('fun one(x: Any) -> Any { return x; }\n'
                                       'print(one(1, 2, 3));\n',
                                       ('--legacy',), (0, b'1\n', b'')),
            # Missing arguments are nil-padded in the argument vector.
            'legacy missing arguments': ('fun two(a: Any, b: Any) -> Any { return [a, b]; }\n'
                                         'print(two(1));\n',
                                         ('--legacy',), (0, b'[1, nil]\n', b'')),
            # A legacy program may pass an Any-typed value to a typed direct
            # callee; its operation paths then check the runtime type.
            'legacy parameter mismatch': ('fun add1(x: Int) -> Int { return x + 1; }\n'
                                          'fun through(x: Any) -> Any { return add1(x); }\n'
                                          'print(through(41));\n'
                                          'print(through("str"));\n',
                                          ('--legacy',), (0, b'42\nstr1\n', b'')),
            # The same function called directly and through a function value:
            # the value call uses the callee's argument-vector entry.
            'dynamic callees': ('fun two(a: Any, b: Any) -> Any { return [a, b]; }\n'
                                'let f: Any = two;\n'
                                'print(two(1, 2), f(3, 4));\n',
                                (), (0, b'[1, 2] [3, 4]\n', b'')),
            # Faults raised in callees reached through direct calls are caught
            # at the call site.
            'callee faults': ('fun overflow(x: Int) -> Int { return x + 9223372036854775807; }\n'
                              'fun divide(a: Int, b: Int) -> Int { return a / b; }\n'
                              'print(may { overflow(1) } otherwise { err.kind });\n'
                              'print(may { divide(7, 0) } otherwise { err.kind });\n',
                              (), (0, b'arithmetic\narithmetic\n', b'')),
        }
        for name, (text, options, expected) in cases.items():
            source = work / (name.replace(' ', '_') + '.may')
            source.write_text(text)
            optimized = behave(compiler, source, options, work / 'optimized')
            plain = behave(compiler, source, options + ('--no-opt',), work / 'plain')
            assert optimized == plain, (name, 'optimized', optimized, '--no-opt', plain)
            assert optimized == expected, (name, 'expected', expected, 'got', optimized)
            print(f'PASS {name}', flush=True)

        # --debug keeps its source traces across direct calls: an uncaught
        # fault in a callee two frames down names both callers.
        source = work / 'debug_traces.may'
        source.write_text('fun inner(x: Any) -> Any { fail("boom"); return x; }\n'
                          'fun outer(x: Any) -> Any { return inner(x); }\n'
                          'print(outer(1));\n')
        options = ('--debug',)
        optimized = behave(compiler, source, options, work / 'debug-optimized')
        plain = behave(compiler, source, options + ('--no-opt',), work / 'debug-plain')
        assert optimized == plain, ('debug traces', optimized, plain)
        status, stdout, stderr = optimized
        assert status == 70 and stderr == b'', (status, stdout, stderr)
        trace = stdout.decode()
        assert trace.startswith('fail: boom\n  at inner ('), trace
        assert trace.count('  at outer (') == 1, trace
        print('PASS debug traces', flush=True)

        # Valid strict source cannot reach the fallback paths: the checker
        # rejects both an arity mismatch and a parameter type mismatch.
        rejects = {
            'arity': ('fun f(x: Int) -> Int { return x; }\nprint(f(1, 2));\n',
                      'argument count mismatch'),
            'parameter type': ('fun f(x: Int) -> Int { return x; }\nprint(f("s"));\n',
                               'expected Int, found Str'),
        }
        for name, (text, message) in rejects.items():
            source = work / (name.replace(' ', '_') + '.may')
            source.write_text(text)
            for extra in ((), ('--no-opt',)):
                built = run([compiler, *extra, source, '-o', work / 'rejected'])
                errors = built.stdout.decode() + built.stderr.decode()
                assert built.returncode != 0 and message in errors, (name, extra, errors)
        print('PASS strict checker rejects the fallback paths', flush=True)
    print('PASS direct calls with register arguments', flush=True)


if __name__ == '__main__':
    main()
