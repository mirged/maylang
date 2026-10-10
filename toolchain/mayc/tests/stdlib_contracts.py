#!/usr/bin/env python3
"""Exercise typed library contracts, including successful nil payloads."""
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
    compiler = str(args.compiler.resolve())
    with tempfile.TemporaryDirectory(prefix='mayc-library-') as directory:
        work = Path(directory)
        imports = f'import {json.dumps(str(ROOT/"stdlib/result.may"))} as result;\nimport {json.dumps(str(ROOT/"stdlib/io.may"))} as io;\n'
        source = work/'contracts.may'
        source.write_text(imports + f'''
let a: Result<Int, Str> = result.ok(7);
let b: Result<Int, Str> = result.error("bad");
let value: Int = result.unwrap(a);
let missing: Int = result.unwrap_or(b, 9);
let mapped: Result<Str, Str> = result.map_result(a, fun(n: Int) -> Str {{ return str(n); }});
let failed: Result<Str, Str> = result.map_result(b, fun(n: Int) -> Str {{ fail("must not call"); return ""; }});
let chained: Result<Str, Str> = result.and_then(a, fun(n: Int) -> Result<Str, Str> {{ return Ok(str(n)); }});
let gathered: Result<List<Int>, Str> = result.collect([a, result.ok(8)]);
let stopped: Result<List<Int>, Str> = result.collect([a, b]);
let nil_result: Result<Nil, Str> = Ok(nil);
let n: Nil = result.unwrap(nil_result);
let caught: Result<Int, Str> = result.attempt(fun() -> Int {{ fail("caught"); return 1; }});
print(value, missing, result.unwrap(mapped), failed.error ?? "missing", result.unwrap(chained), result.unwrap(gathered), stopped.error ?? "missing", n, caught.error ?? "missing");
io.io_write_lines({json.dumps(str(work/'lines.txt'))}, ["a", "b"]);
let lines: List<Str> = io.io_read_lines({json.dumps(str(work/'lines.txt'))});
print(lines);
''')
        targets = ['x86_64-linux', 'clang-llvm'] if args.llvm else ['x86_64-linux']
        for target in targets:
            binary = work/target
            result = subprocess.run([compiler, '--target', target, str(source), '-o', str(binary)], capture_output=True, timeout=120)
            assert result.returncode == 0, result.stderr.decode()
            result = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert result.returncode == 0 and result.stdout == b'7 9 7 bad 7 [7, 8] bad nil caught\n["a", "b"]\n', result
            print('PASS typed Result and I/O contracts on '+target, flush=True)
        for code in ['let n: Str = result.unwrap(result.ok(1));', 'io.io_read_text(1);', 'io.io_write_lines("x", [1]);']:
            source.write_text(imports + code)
            result = subprocess.run([compiler, '--check', str(source)], capture_output=True, timeout=60)
            assert result.returncode != 0 and b'expected' in result.stderr, result
        print('PASS rejected library contract violations', flush=True)


if __name__ == '__main__':
    main()
