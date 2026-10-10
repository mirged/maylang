#!/usr/bin/env python3
"""Check numeric boundaries, binary32 precision and fixed array lengths."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SOURCE='''
fun narrow(n: Int) -> UInt8 { return n; }
let max: UInt8 = 255; let min: Int8 = -128; let wide: UInt32 = 4294967295;
print(max, min, wide);
let too_big: Int = 256;
print(may { narrow(too_big); "bad" } otherwise { str(err.kind) });
mut small: UInt8 = 255;
print(may { small += 1; "bad" } otherwise { str(err.kind) });
let xs: List<UInt8> = [1,2];
print(may { push(xs, too_big); "bad" } otherwise { str(err.kind) });
print(may { xs[0] += too_big; "bad" } otherwise { str(err.kind) });
let aliases: List<Int> = xs; aliases[0] = too_big;
print(may { let value: UInt8 = xs[0]; "bad" } otherwise { str(err.kind) });
let f: Float32 = 16777217.0; let g: Float32 = 0.1;
print(f == 16777216.0, g == 0.10000000149011612);
let fs: List<Float32> = [16777217.0]; print(fs[0] == 16777216.0);
fun array(n: List<Int>) -> [Int; 2] { return n; }
print(may { array([1]); "bad" } otherwise { str(err.kind) });
let good: [Int; 2] = array([1,2]); print(good);
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',type=Path,default=ROOT/'toolchain/mayc/mayc_new');parser.add_argument('--llvm',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-numeric-') as directory:
        work=Path(directory);source=work/'numbers.may';source.write_text(SOURCE)
        for target in ['x86_64-linux','clang-llvm'] if args.llvm else ['x86_64-linux']:
            binary=work/target
            result=subprocess.run([str(args.compiler.resolve()),'--target',target,str(source),'-o',str(binary)],capture_output=True,timeout=120)
            assert result.returncode==0,result.stderr.decode()
            result=subprocess.run([str(binary)],capture_output=True,timeout=10)
            expected=b'255 -128 4294967295\n'+b'arithmetic\n'*5+b'true true\ntrue\narithmetic\n[1, 2]\n'
            assert result.returncode==0 and result.stdout==expected,result
            print('PASS bounds, collection mutation/aliases, binary32 precision and arrays on '+target,flush=True)
        for code, message in [('let n: UInt8 = 256;','outside UInt8 bounds'),('let n: Int8 = -129;','outside Int8 bounds'),('let n: UInt64 = -1;','outside UInt64 bounds'),('let a: [Int; 2] = [1];','fixed array length mismatch')]:
            source.write_text(code)
            result=subprocess.run([str(args.compiler.resolve()),'--check',str(source)],capture_output=True,timeout=60)
            assert result.returncode!=0 and message.encode() in result.stderr,result
        source.write_text('let n: UInt8 = 255; print(n);')
        binary=work/'core'
        subprocess.run([str(args.compiler.resolve()),'--runtime','core',str(source),'-o',str(binary)],check=True,timeout=60)
        assert subprocess.check_output([str(binary)])==b'255\n'
        print('PASS literal rejections and core integer contracts',flush=True)


if __name__=='__main__':main()
