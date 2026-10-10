#!/usr/bin/env python3
"""Debug traces survive recovery, tail calls and independent fiber stacks."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',type=Path,default=ROOT/'toolchain/mayc/mayc_new');parser.add_argument('--llvm',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-traces-') as directory:
        work=Path(directory);source=work/'traces.may'
        source.write_text('''
fun leaf() -> Int { fail("failure"); return 0; }
fun middle() -> Int { return leaf(); }
fun parent() -> Str {
    let first: Str = may { middle(); "bad" } otherwise { str(err.stack) };
    let second: Str = may { leaf(); "bad" } otherwise { str(err.stack) };
    print(contains(first, "leaf ("), contains(first, "middle ("), contains(first, "parent ("));
    print(contains(second, "leaf ("), contains(second, "middle ("), contains(second, "parent ("));
    return "done";
}
fun tail(n: Int) -> Int { if(n == 0) { return leaf(); } return tail(n-1); }
print(parent());
print(may { tail(10000); "bad" } otherwise { contains(str(err.stack), "tail (") });
print(may { leaf(); "bad" } otherwise { contains(str(err.stack), "tail (") });
''')
        for target in ['x86_64-linux','clang-llvm'] if args.llvm else ['x86_64-linux']:
            binary=work/target
            result=subprocess.run([str(args.compiler.resolve()),'--debug','--target',target,str(source),'-o',str(binary)],capture_output=True,timeout=120)
            assert result.returncode==0,result.stderr.decode()
            result=subprocess.run([str(binary)],capture_output=True,timeout=30)
            assert result.returncode==0 and result.stdout==b'true true true\ntrue false true\ndone\ntrue\nfalse\n',result
            print('PASS recovery, tail-call depth and source traces on '+target,flush=True)
        source.write_text('fun broken() -> Nil { fail("uncaught"); return nil; } broken();')
        binary=work/'uncaught'
        subprocess.run([str(args.compiler.resolve()),'--debug',str(source),'-o',str(binary)],check=True,timeout=60)
        result=subprocess.run([str(binary)],capture_output=True,timeout=10)
        assert result.returncode==70 and b'at broken (' in result.stdout and b'traces.may:1' in result.stdout,result
        source.write_text('''
fun fiber_a() -> Nil { yield(); print(may { fail("a"); "bad" } otherwise { contains(str(err.stack), "fiber_b (") }); return nil; }
fun fiber_b() -> Nil { yield(); print(may { fail("b"); "bad" } otherwise { contains(str(err.stack), "fiber_a (") }); return nil; }
spawn(fiber_a); spawn(fiber_b); run();
print(may { fail("main"); "bad" } otherwise { contains(str(err.stack), "fiber_a (") });
''')
        binary=work/'fibers'
        subprocess.run([str(args.compiler.resolve()),'--debug',str(source),'-o',str(binary)],check=True,timeout=60)
        result=subprocess.run([str(binary)],capture_output=True,timeout=10)
        assert result.returncode==0 and result.stdout==b'false\nfalse\nfalse\n',result
        print('PASS uncaught output and isolated cooperative fiber traces',flush=True)


if __name__=='__main__':main()
