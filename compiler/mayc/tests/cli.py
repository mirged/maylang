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
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
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
        assert 'Linux x86-64' in lines[-1] and 'llvm' not in result.stdout, lines
        rows = [line.split('\t') for line in lines[1:-1]]
        assert rows == [['x86_64-linux', 'elf', 'full']], rows
        assert sorted(path.name for path in work.iterdir()) == ['mayc']
        source = work / 'hello.may'
        source.write_text('print(42);\n')
        output = work / 'x86_64-linux'
        command = [str(compiler), '--target', 'x86_64-linux', str(source), '-o', str(output)]
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stderr
        implicit = output.read_bytes()
        result = subprocess.run([*command, '--runtime', 'full'], cwd=work, env=env, capture_output=True, timeout=120)
        assert result.returncode == 0 and output.read_bytes() == implicit, result
        assert implicit.startswith(b'\x7fELF'), implicit[:4]
        result = subprocess.run([str(output)], capture_output=True, timeout=30)
        assert result.returncode == 0 and result.stdout == b'42\n', result
        bad_output = work / 'invalid'
        # Other targets and the core runtime are frozen (frozen/README.md).
        for target in ('x86_64-nodeos', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows'):
            result = subprocess.run([str(compiler), '--target', target, str(source), '-o', str(bad_output)],
                                    cwd=work, env=env, capture_output=True, timeout=30)
            message = f'target {target} is frozen; Maylang currently supports x86_64-linux'.encode()
            assert result.returncode != 0 and message in result.stderr and not bad_output.exists(), result
        result = subprocess.run([str(compiler), '--runtime', 'core', str(source), '-o', str(bad_output)],
                                cwd=work, env=env, capture_output=True, timeout=30)
        assert result.returncode != 0 and b'runtime core is frozen' in result.stderr and not bad_output.exists(), result
        result = subprocess.run([str(compiler), '--target', 'unknown-target', str(source),
                                 '-o', str(bad_output)], cwd=work, env=env,
                                capture_output=True, timeout=30)
        assert result.returncode != 0 and b'unknown target' in result.stderr, result
        assert not bad_output.exists()
        # mayc is its own toolchain: the LLVM IR backend was removed.
        for flags, message in ((['--target', 'clang-llvm'], b'clang-llvm target was removed'),
                               (['--emit-llvm'], b'--emit-llvm was removed')):
            result = subprocess.run([str(compiler), *flags, str(source), '-o', str(bad_output)], cwd=work,
                                    env=env, capture_output=True, timeout=30)
            assert result.returncode != 0 and message in result.stderr and not bad_output.exists(), result
        print('PASS source-free target discovery, runtime defaults, invalid, frozen and removed targets')

        # A bare PATH command and a symlink must find sidecars at the real
        # executable, even outside the checkout and without shell overrides.
        installed = work / 'installed tools'
        installed.mkdir()
        shutil.copy2(compiler, installed / 'mayc')
        for name in ('native.may', 'prelude.may'):
            shutil.copy2(compiler.parent / name, installed / name)
        shutil.copytree(compiler.parent / 'runtime', installed / 'runtime')
        links = work / 'links'
        links.mkdir()
        (links / 'mayc-link').symlink_to(installed / 'mayc')
        clean_env = {key: value for key, value in os.environ.items()
                     if key not in ('MAYC', 'MAYLANG_STDLIB')}
        clean_env['PATH'] = str(installed) + os.pathsep + clean_env.get('PATH', '')
        for invocation in ('mayc', str(links / 'mayc-link'), './installed tools/mayc'):
            for runtime in ('full',):
                output = work / 'relocated-hello'
                result = subprocess.run([invocation, '--runtime', runtime, str(source),
                                         '-o', str(output)], cwd=work, env=clean_env,
                                        capture_output=True, timeout=120)
                assert result.returncode == 0, (invocation, runtime, result.stderr)
                result = subprocess.run([str(output)], capture_output=True, timeout=30)
                assert result.returncode == 0 and result.stdout == b'42\n', result
        print('PASS PATH, symlink and relative invocation locate runtime sidecars')


if __name__ == '__main__':
    main()
