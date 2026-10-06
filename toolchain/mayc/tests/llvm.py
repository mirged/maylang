#!/usr/bin/env python3
"""Validate Maylang's direct LLVM emitter, driver, and native runtime semantics."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def run(argv, *, env=None):
    return subprocess.run([str(a) for a in argv], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    parser.add_argument('--clang', default=os.environ.get('CLANG', 'clang'))
    parser.add_argument('--case', action='append', default=[], help='run selected behavior cases')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    clang = shutil.which(args.clang)
    environment = dict(os.environ, MAY_BOOTSTRAP='/missing/bootstrap')
    target = [compiler, '--target', 'clang-llvm']
    with tempfile.TemporaryDirectory(prefix='may llvm tests ') as directory:
        work = Path(directory)
        source = work / 'fruit source.may'
        source.write_text('import "string";\n'
            '["apple","banana","cherry"]|>map(capitalize)|>enumerate|>'
            'each(|x:Any|{return print("Fruit ${x[0]}:",x[1])})')
        expected = 'Fruit 0: Apple\nFruit 1: Banana\nFruit 2: Cherry\n'
        ir = work / 'fruit.ll'
        # IR emission is entirely inside mayc; neither external tool is needed.
        missing_tools = dict(environment, CLANG='/missing/clang')
        result = run(target + ['--emit-llvm', source, '-o', ir], env=missing_tools)
        assert result.returncode == 0, result.stderr
        text = ir.read_text()
        assert '; Maylang direct LLVM backend' in text and 'define i32 @main' in text
        assert not os.access(ir, os.X_OK)
        result = run(target + ['--check', source], env=missing_tools)
        assert result.returncode == 0, result.stderr

        invalid = work / 'invalid.may'
        invalid.write_text('let n: Int = "wrong"; print(n);')
        unsupported = work / 'fibers.may'
        unsupported.write_text('spawn(fun(){print("hello");}); run();')
        output = work / 'existing output'
        output.write_text('preserve this file')
        for flags, src in (([], invalid), (['--raw'], source),
                           (['--runtime', 'core'], source),
                           (['--runtime', 'none'], source), ([], unsupported)):
            result = run(target + flags + [src, '-o', output], env=environment)
            assert result.returncode != 0, (flags, src)
            assert output.read_text() == 'preserve this file'
        result = run([compiler, '--emit-llvm', source, '-o', output], env=environment)
        assert result.returncode != 0 and 'requires --target clang-llvm' in result.stderr

        # Inspect the actual direct-IR subprocess route and failure cleanup.
        log = work / 'clang-argv.json'
        fake = work / 'fake clang'
        fake.write_text('#!/usr/bin/python3\nimport json,os,sys\nfrom pathlib import Path\n'
            f'assert os.environ.get("PATH") == {environment.get("PATH")!r}\n'
            f'Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            'src=Path(sys.argv[sys.argv.index("-x")+3])\n'
            'assert src.suffix == ".ll" and "Maylang direct LLVM" in src.read_text()\n'
            'sys.exit(37)\n')
        fake.chmod(0o755)
        result = run(target + [source, '-o', output], env=dict(environment, CLANG=str(fake)))
        assert result.returncode != 0 and 'exit status: 37' in result.stderr, result.stderr
        command = json.loads(log.read_text())
        assert command[:3] == ['-x', 'ir', '-O1'] and '-lm' in command
        assert not Path(command[3]).parent.exists(), 'scratch survived failure'
        assert output.read_text() == 'preserve this file'
        print('PASS direct IR emission, strict diagnostics, and driver failure cleanup')
        if not clang:
            print('SKIP LLVM validation and execution: Clang is not installed')
            return
        environment['CLANG'] = str(Path(clang).resolve())
        linked = work / 'linked-from-ir'
        result = run([clang, '-x', 'ir', '-O1', ir, '-lm', '-o', linked])
        assert result.returncode == 0, result.stderr
        result = run([linked])
        assert (result.returncode, result.stdout, result.stderr) == (0, expected, ''), result
        assembler = next((shutil.which(n) for n in ('llvm-as', 'llvm-as-19') if shutil.which(n)), None)
        if assembler:
            result = run([assembler, ir, '-o', work / 'fruit.bc'])
            assert result.returncode == 0, result.stderr
        fixtures = {
            'fruit': source.read_text(),
            'arithmetic': 'mut n=0; for x in 1..=5 {n+=x*x;} print(n,-17%5);',
            'closure': 'fun c(n:Int){mut x=n;return fun()->Int{x+=1;return x;};}'
                       'let f=c(2);print(f(),f());',
            'nested-capture': 'fun c(){mut x=0;return fun(){return fun(){x+=1;return x;};};}'
                              'let g=c()();print(g(),g());',
            'handler': 'print(may {fail("caught");} otherwise {"ok"});'
                       'print(may {print(may {fail("inner");} otherwise {"in"});fail("out");} otherwise {"outer"});',
            'inferred-handler': 'fun test_may(){let result=may{let bad=10/0;bad}'
                                'otherwise{print("Caught an error: ${err}");};'
                                'print(result);return nil;}test_may();',
            'print-result': 'print(print("hello"));',
            'comprehension': 'fun test_comprehension()->Int{let nums:List<Int> = [1,2,3,4,5,6,7,8,9,10];'
                             'let xs:List<Int> = [x*x for x in nums if x%2==0];print(xs);return 0;}test_comprehension();',
            'float': 'print(1.25+2.5,3.5*2,9.0/2,2.5<3.0,floor(-2.5),ceil(2.5),sqrt(9.0));',
            'unicode': 'print("a\\nλ",chr(9731),len("λ☃"),to_upper("abc"));',
            'map-list': 'let m:Any={"x":[1,2]};m.x[0]=4;push(m.x,3);print(m.x,m.x[0],m?.x);',
            'tailcall': 'fun loop(n:Int,a:Int)->Int{if(n==0){return a;}return loop(n-1,a+n);}print(loop(10000,0));',
            'process': 'print(wait(exec(["/bin/sh","-c","test -n \\"$PATH\\" && exit 7"])));',
            'short-call': 'let f:Any=fun(a:Any,b:Any){return [a,b];}; print(f(1));',
        }
        fixtures['nan'] = 'let n:Any=sqrt(-1.0);print(n==n,n!=n,n<0.0,n<=0.0,n>0.0,n>=0.0,trunc(n));print(trunc(1e308),trunc(-1e308));'
        fixtures['many-args'] = 'fun eight(a:Any,b:Any,c:Any,d:Any,e:Any,f:Any,g:Any,h:Any){return [a,b,c,d,e,f,g,h];}let f:Any=eight;print(eight(1,2,3,4,5,6,7,8),f(11,12,13,14,15,16,17,18));'
        fixtures['gc-capture'] = 'fun exercise(){mut xs:Any=["alive"];let get:Any=fun(){return xs[0];};mut i:Any=0;while(i<3000000){let t:Any=str(i);i+=1;}return get;}let f:Any=exercise();print(f());'
        for name in ('architecture', 'arith_overflow', 'floats', 'edge', 'div_zero', 'closures_adv'):
            fixtures[name] = (ROOT / 'toolchain/mayc/tests' / f'{name}.may').read_text()
        if any(name not in fixtures for name in args.case):
            parser.error("unknown --case name")
        for name, text in fixtures.items():
            if args.case and name not in args.case:
                continue
            fixture = work / f'{name}.may'
            fixture.write_text(text)
            native, binary = work / f'{name}-native', work / f'{name}-llvm'
            result = run([compiler, fixture, '-o', native], env=environment)
            assert result.returncode == 0, (name, result.stderr)
            result = run(target + [fixture, '-o', binary], env=environment)
            assert result.returncode == 0, (name, result.stderr)
            before, after = run([native]), run([binary])
            assert (before.stdout, before.stderr, before.returncode) == (
                after.stdout, after.stderr, after.returncode), (name, before, after)
            print(f'PASS LLVM/native behavior: {name}', flush=True)


if __name__ == '__main__':
    main()
