#!/usr/bin/env python3
"""Source-free target discovery agrees with actual target emission."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from backends import compiler_binary

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    env = os.environ.copy()
    env['MAYLANG_STDLIB'] = str(ROOT / 'stdlib')
    with tempfile.TemporaryDirectory(prefix='mayc-cli-') as directory:
        work = Path(directory)
        standalone = work / 'mayc'
        shutil.copy2(compiler, standalone)
        result = subprocess.run([str(standalone), '--list-targets'], cwd=work,
                                env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and not result.stderr, result
        lines = result.stdout.splitlines()
        assert lines[0].split('\t') == ['target', 'format', 'default-runtime'], lines
        assert 'Linux x86-64' in lines[-1] and 'experimental' in lines[-1], lines
        rows = [line.split('\t') for line in lines[1:-1]]
        assert len(rows) == 6 and len({row[0] for row in rows}) == 6, rows
        assert sorted(path.name for path in work.iterdir()) == ['mayc']
        source = work / 'hello.may'
        source.write_text('print(42);\n')
        magic = {'elf': b'\x7fELF', 'macho': b'\xcf\xfa\xed\xfe', 'pe': b'MZ'}
        for target, format_name, runtime in rows:
            assert runtime in ('full', 'core'), rows
            output = work / target
            options = ['--emit-llvm'] if format_name == 'llvm' else []
            command = [str(compiler), '--target', target, *options, str(source), '-o', str(output)]
            result = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=120)
            assert result.returncode == 0, (target, result.stderr)
            implicit = output.read_bytes()
            result = subprocess.run([*command, '--runtime', runtime], cwd=work,
                                    env=env, capture_output=True, timeout=120)
            assert result.returncode == 0 and output.read_bytes() == implicit, (target, result)
            if format_name == 'llvm':
                assert b'target triple' in implicit and b'define' in implicit, implicit[:200]
            else:
                assert implicit.startswith(magic[format_name]), (target, implicit[:4])
            if target == 'x86_64-linux':
                result = subprocess.run([str(output)], capture_output=True, timeout=30)
                assert result.returncode == 0 and result.stdout == b'42\n', result
        bad_output = work / 'invalid'
        result = subprocess.run([str(compiler), '--target', 'unknown-target', str(source),
                                 '-o', str(bad_output)], cwd=work, env=env,
                                capture_output=True, timeout=30)
        assert result.returncode != 0 and b'unknown target' in result.stderr, result
        assert not bad_output.exists()
        print('PASS source-free target discovery, emitted formats, runtime defaults and invalid target')


if __name__ == '__main__':
    main()
