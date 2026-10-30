#!/usr/bin/env python3
"""Inspect stripped code/data/loader entries and execute retained graph edges."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


DEAD = 'unreachable-function-literal-9c528a'


def run(argv):
    return subprocess.run([str(a) for a in argv], cwd=ROOT,
                          capture_output=True, timeout=180)


def symbols(binary):
    result = run(['readelf', '--wide', '--symbols', binary])
    assert result.returncode == 0 and not result.stderr, result.stderr
    return {line.split()[-1] for line in result.stdout.decode().splitlines()
            if ' FUNC ' in line}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-reachability-') as directory:
        work = Path(directory)

        def compile_case(name, text, options=()):
            source = work / (name + '.may'); source.write_text(text)
            output = work / name
            result = run([compiler, *options, source, '-o', output])
            assert result.returncode == 0, (name, result.stderr.decode())
            assert DEAD.encode() not in output.read_bytes(), name
            return source, output

        def execute(binary, expected):
            result = run([binary])
            assert (result.returncode, result.stdout, result.stderr) == (0, expected, b''), result

        unused = f'fun dead_a()->Str{{return "{DEAD}";}}\n' \
                 'fun dead_b()->Int{return dead_c();}\nfun dead_c()->Int{return dead_b();}\n' \
                 f'fun dead_outer()->Any{{return fun(){{return "{DEAD}";}};}}\n'
        (work / 'init.may').write_text('print("import initialized");\n' + unused)
        fixtures = {
            'direct': ('fun kept(n:Int)->Int{return n+1;}print(kept(41));', b'42\n'),
            'function-value': ('fun kept(n:Int)->Int{return n+1;}'
                               'let fs:List<Any> = [kept];print((fs[0])(41));', b'42\n'),
            'closure': ('fun kept(n:Int)->Int{return n+1;}'
                        'fun make(n:Int)->Any{return fun()->Int{return kept(n);};}'
                        'let f:Any=make(41);print(f());', b'42\n'),
            'recursion': ('fun even(n:Int)->Bool{return if n==0{true}else{odd(n-1)};}'
                          'fun odd(n:Int)->Bool{return if n==0{false}else{even(n-1)};}'
                          'print(even(20),odd(20));', b'true false\n'),
            'initialization': ('import "init.may";\n'
                               'fun kept()->Int{print("global initialized");return 42;}'
                               'let n:Int=kept();print(n);', b'import initialized\nglobal initialized\n42\n'),
            'handler': ('print(may{let n:Int=1; n/0}otherwise{42});', b'42\n'),
            'float': ('print(1.25+2.5,2.0**3.0);', b'3.75 8.0\n'),
            'unused-extern': ('extern "lib-not-installed-reachability.so"{'
                              'fun missing()->Int32="missing_reachability_symbol";}'
                              'print(42);', b'42\n'),
        }
        for name, (text, expected) in fixtures.items():
            source, binary = compile_case(name, unused + text)
            execute(binary, expected)
            names = symbols(binary)
            assert not any(n.endswith(('::dead_a', '::dead_b', '::dead_c', '::dead_outer', '::missing')) for n in names), names
            assert 'rt_spawn' not in names and 'rt_json_parse' not in names, names
            if name in ('direct', 'function-value', 'closure', 'initialization'):
                assert any(n.endswith('::kept') for n in names), names
            if name == 'unused-extern':
                assert b'lib-not-installed-reachability.so' not in binary.read_bytes()
                assert b'missing_reachability_symbol' not in binary.read_bytes()
                assert b'INTERP' not in run(['readelf', '-l', binary]).stdout
            print('PASS retained edges and stripped code/data: ' + name, flush=True)

        # Keep used loader slots and ABI conversions, but drop an unavailable
        # symbol in the same library and an entirely unavailable second library.
        text = ('extern "libc.so.6"{fun cabs(n:Int32)->Int32="abs";'
                'fun missing()->Int32="missing_reachability_symbol";}'
                'extern "lib-not-installed-reachability.so"{fun other()->Int32;}'
                'let f:Any=cabs;print(cabs(-42),f(-7));')
        _, binary = compile_case('used-extern', text)
        execute(binary, b'42 7\n')
        image = binary.read_bytes()
        assert b'lib-not-installed-reachability.so' not in image
        assert b'missing_reachability_symbol' not in image
        assert b'INTERP' in run(['readelf', '-l', binary]).stdout
        print('PASS used foreign calls/function values and pruned loader dependencies', flush=True)

        core = unused + 'fun kept(n:Int)->Int{return n+1;}print(kept(41));'
        for target in ('x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows'):
            _, binary = compile_case('core-' + target, core, ['--runtime', 'core', '--target', target])
            if target.endswith('linux'):
                names = symbols(binary)
                assert 'rt_split' not in names and 'rt_contains' not in names, names
            if target == 'x86_64-linux':
                execute(binary, b'42\n')
            print('PASS core runtime stripping: ' + target, flush=True)

        raw = f'fun dead()->Any{{return addr("{DEAD}");}}' \
              'fun kept(n:Any)->Any{return n+1;}if kept(41)!=42{exit(1);}exit(0);'
        for target in ('x86_64-linux', 'arm64-linux', 'riscv64-linux'):
            _, binary = compile_case('raw-' + target, raw, ['--raw', '--target', target])
            assert not any(n.endswith('::dead') for n in symbols(binary))
            if target == 'x86_64-linux':
                execute(binary, b'')
        print('PASS raw direct-call reachability and stripped literals', flush=True)

        # Checking remains whole-program: unreachable errors are not hidden.
        invalid = work / 'invalid.may'
        invalid.write_text('fun unused()->Int{return "wrong";}print(42);')
        for options in ([], ['--check']):
            output = work / 'invalid-output'
            result = run([compiler, *options, invalid, '-o', output])
            assert result.returncode != 0 and b'expected Int' in result.stderr and not output.exists(), result
        print('PASS unreachable declarations still receive strict diagnostics', flush=True)


if __name__ == '__main__':
    main()
