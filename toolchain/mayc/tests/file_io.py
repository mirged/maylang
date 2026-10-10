#!/usr/bin/env python3
"""Exact file bytes beyond 1 MiB, empty files and read/write failures."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'toolchain/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-file-io-') as directory:
        work = Path(directory)
        payload = bytes(range(256)) * 8193 + b'last byte\x00\xff'
        (work/'input').write_bytes(payload); (work/'empty').write_bytes(b'')
        source = work/'io.may'
        source.write_text(f'''
write_file({json.dumps(str(work/'copy'))}, read_file({json.dumps(str(work/'input'))}));
write_file({json.dumps(str(work/'empty-copy'))}, read_file({json.dumps(str(work/'empty'))}));
print(may {{ read_file({json.dumps(str(work))}); false }} otherwise {{ true }});
print(may {{ write_file("/dev/full", "failure"); false }} otherwise {{ true }});
''')
        for target in ['x86_64-linux', 'clang-llvm'] if args.llvm else ['x86_64-linux']:
            binary=work/target
            result=subprocess.run([str(args.compiler.resolve()),'--target',target,str(source),'-o',str(binary)],capture_output=True,timeout=120)
            assert result.returncode == 0,result.stderr.decode()
            result=subprocess.run([str(binary)],capture_output=True,timeout=30)
            assert result.returncode == 0 and result.stdout == b'true\ntrue\n',result
            assert (work/'copy').read_bytes() == payload
            assert (work/'empty-copy').read_bytes() == b''
            print('PASS binary file sizes, empty files and failures on '+target,flush=True)


if __name__ == '__main__':
    main()
