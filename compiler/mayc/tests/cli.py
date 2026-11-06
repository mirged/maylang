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
        # Other targets and the core runtime are not supported (docs/design/LINUX_X86_64_FOCUS.md).
        for target in ('x86_64-nodeos', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows'):
            result = subprocess.run([str(compiler), '--target', target, str(source), '-o', str(bad_output)],
                                    cwd=work, env=env, capture_output=True, timeout=30)
            message = f'target {target} is not supported; Maylang currently supports x86_64-linux'.encode()
            assert result.returncode != 0 and message in result.stderr and not bad_output.exists(), result
        result = subprocess.run([str(compiler), '--runtime', 'core', str(source), '-o', str(bad_output)],
                                cwd=work, env=env, capture_output=True, timeout=30)
        assert result.returncode != 0 and b'runtime core is not supported' in result.stderr and not bad_output.exists(), result
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
        print('PASS source-free target discovery, runtime defaults, invalid, unsupported and removed targets')

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

        # The command surface: run/check subcommands, optimization levels,
        # depfiles, colour and help.
        runner = work / 'runner.may'
        runner.write_text('let argv: List<Str> = args();\nprint(argv[1]);\nprint(argv[2]);\nexit(7);\n')
        result = subprocess.run([str(compiler), 'run', str(runner), '--', 'one', 'two three'],
                                cwd=work, env=env, capture_output=True, timeout=120)
        assert result.returncode == 7 and result.stdout == b'one\ntwo three\n', result
        kept = work / 'kept-run'
        result = subprocess.run([str(compiler), 'run', str(runner), '-o', str(kept), '--', 'a', 'b'],
                                cwd=work, env=env, capture_output=True, timeout=120)
        assert result.returncode == 7 and kept.is_file(), result
        bad_run = work / 'bad-run.may'
        bad_run.write_text('let value: Int = "wrong";\n')
        result = subprocess.run([str(compiler), 'run', str(bad_run)], cwd=work, env=env,
                                capture_output=True, timeout=120)
        assert result.returncode != 0 and b'expected Int, found Str' in result.stderr, result
        result = subprocess.run([str(compiler), 'check', str(bad_run)], cwd=work, env=env,
                                capture_output=True, timeout=120)
        assert result.returncode != 0 and not (work / 'bad-run').exists(), result
        result = subprocess.run([str(compiler), 'check', str(source)], cwd=work, env=env,
                                capture_output=True, timeout=120)
        assert result.returncode == 0, result
        for level in ('-O', '-O0', '-O1', '-O2'):
            optimized = work / ('opt' + level)
            result = subprocess.run([str(compiler), level, str(source), '-o', str(optimized)],
                                    cwd=work, env=env, capture_output=True, timeout=120)
            assert result.returncode == 0, (level, result)
            ran = subprocess.run([str(optimized)], capture_output=True, timeout=30)
            assert ran.returncode == 0 and ran.stdout == b'42\n', (level, ran)
        rejected = subprocess.run([str(compiler), '-O3', str(source), '-o', str(work / 'o3')],
                                  cwd=work, env=env, capture_output=True, timeout=30)
        assert rejected.returncode != 0 and b'-O accepts 0, 1 or 2' in rejected.stderr, rejected
        project = work / 'dependencies'
        project.mkdir()
        (project / 'helper.may').write_text('pub fun answer() -> Int { return 5; }\n')
        (project / 'main.may').write_text('import "helper.may" as helper;\nprint(helper.answer());\n')
        depfile = project / 'main.d'
        result = subprocess.run([str(compiler), str(project / 'main.may'), '-o', str(project / 'main'),
                                 '--deps', str(depfile)], cwd=work, env=env, capture_output=True, timeout=120)
        assert result.returncode == 0, result
        recorded = depfile.read_text()
        assert recorded.startswith(str(project / 'main') + ':'), recorded
        assert str(project / 'helper.may') in recorded and 'prelude.may' in recorded, recorded
        colored = subprocess.run([str(compiler), '--color', 'always', str(bad_run), '-o', str(work / 'bad')],
                                 cwd=work, env=env, capture_output=True, timeout=30)
        assert b'\x1b[31m' in colored.stderr and b'error[E_TYPE]' in colored.stderr, colored
        plain = subprocess.run([str(compiler), '--color', 'never', str(bad_run), '-o', str(work / 'bad')],
                               cwd=work, env=env, capture_output=True, timeout=30)
        assert b'\x1b[' not in plain.stderr and b'error[E_TYPE]' in plain.stderr, plain
        help_text = subprocess.run([str(compiler), 'help'], cwd=work, env=env,
                                   capture_output=True, timeout=30).stdout
        for expected in (b'mayc run', b'mayc check', b'--deps', b'-O0', b'--color'):
            assert expected in help_text, expected
        print('PASS run/check subcommands, -O levels, depfiles, colour diagnostics and help')


if __name__ == '__main__':
    main()
