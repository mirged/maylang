#!/usr/bin/env python3
"""Compiler source reads distinguish empty files, read failures and size limits;
runtime and library sidecars reject duplicate function names."""
import argparse
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    with tempfile.TemporaryDirectory(prefix='mayc-source-files-') as directory:
        work = Path(directory)
        source = work / 'main.may'
        binary = work / 'program'

        def invoke(path, *options, env=None, limit=None):
            def restrict():
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            return subprocess.run([str(compiler), *options, str(path), '-o', str(binary)],
                                  capture_output=True, timeout=60, env=env,
                                  preexec_fn=restrict if limit else None)

        for options in ([], ['--raw']):
            for path in (work / 'missing.may', work):
                binary.write_bytes(b'previous output')
                result = invoke(path, *options)
                assert result.returncode == 1 and b'cannot read' in result.stderr, result
                assert str(path).encode() in result.stderr, result
                assert binary.read_bytes() == b'previous output'
            source.write_text('')
            result = invoke(source, *options)
            assert result.returncode == 0, result
            result = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert (result.returncode, result.stdout, result.stderr) == (0, b'', b''), result

        imported = work / 'library.may'
        imported.mkdir()
        source.write_text('import "library.may";\nprint(42);\n')
        binary.unlink()
        result = invoke(source)
        assert result.returncode == 1 and b'cannot read' in result.stderr, result
        assert str(imported).encode() in result.stderr and not binary.exists(), result
        print('PASS empty sources, missing files and directory read failures preserve outputs')

        limit = 1024 * 1024
        for size in (limit - 1, limit):
            source.write_bytes(b'//' + b' ' * (size - 3) + b'\n')
            result = invoke(source, '--check')
            assert result.returncode == 0, (size, result)
        oversized = b'//' + b' ' * (limit - 2) + b'\nlet bad: Int = "wrong";\n'
        source.write_bytes(oversized)
        for options in ([], ['--raw']):
            binary.write_bytes(b'previous output')
            result = invoke(source, *options)
            assert result.returncode == 1 and b'input file exceeds 1 MiB limit' in result.stderr, result
            assert binary.read_bytes() == b'previous output'
        imported.rmdir()
        imported.write_bytes(oversized)
        source.write_text('import "library.may";\nprint(42);\n')
        result = invoke(source)
        assert result.returncode == 1 and b'input file exceeds 1 MiB limit' in result.stderr, result
        assert binary.read_bytes() == b'previous output'
        print('PASS exact source-size boundary and oversized main/import rejection')

        source.write_text('print(42);\n')
        arena = {**os.environ}
        for value in ('abc', '4095', '12x', '1099511627777', '99999999999999999999'):
            binary.write_bytes(b'previous output')
            result = invoke(source, env={**arena, 'MAYC_ARENA_BYTES': value})
            assert result.returncode == 1 and b'MAYC_ARENA_BYTES must be a byte count' in result.stderr, (value, result)
            assert binary.read_bytes() == b'previous output'
        for options in ([], ['--raw']):
            result = invoke(source, *options, env={**arena, 'MAYC_ARENA_BYTES': '4096'})
            assert result.returncode == 1 and b'source arena exhausted (4096 bytes)' in result.stderr, result
            assert binary.read_bytes() == b'previous output'
        # A 1 TiB arena cannot fit a 4 GiB address-space limit; the compiler itself does.
        result = invoke(source, env={**arena, 'MAYC_ARENA_BYTES': str(1 << 40)}, limit=4 << 30)
        assert result.returncode == 1 and b'cannot map the 1099511627776-byte source arena' in result.stderr, result
        assert binary.read_bytes() == b'previous output'
        result = invoke(source, env={**arena, 'MAYC_ARENA_BYTES': str(16 * 1024 * 1024)}, limit=4 << 30)
        assert result.returncode == 0, result
        assert subprocess.run([str(binary)], capture_output=True, timeout=10).stdout == b'42\n'
        print('PASS bounded source arena: size override, exhaustion and mapping failure diagnostics')

        # Source reads keep only their bytes, so many small modules fit the arena.
        modules = work / 'modules'
        modules.mkdir()
        for index in range(400):
            (modules / f'm{index}.may').write_text(f'fun f{index}() -> Int {{ return {index}; }}\n')
        entry = modules / 'main.may'
        entry.write_text(''.join(f'import "m{index}.may";\n' for index in range(400)) + 'print(f0() + f399());\n')
        result = invoke(entry, env={**arena, 'MAYC_ARENA_BYTES': str(16 * 1024 * 1024)})
        assert result.returncode == 0, result
        assert subprocess.run([str(binary)], capture_output=True, timeout=10).stdout == b'399\n'
        print('PASS source buffers are sized by content: 400 imported modules in a 16 MiB arena')

        # Each module is below the per-file limit; the closure has its own 4 MiB bound.
        closure = work / 'closure'
        closure.mkdir()
        for index in range(5):
            (closure / f'b{index}.may').write_text('//' + ' ' * 1040000 + f'\nfun g{index}() -> Int {{ return {index}; }}\n')
        (closure / 'nested.may').write_text('// nested\nimport "b4.may";\n')
        imports = ''.join(f'import "b{index}.may";\n' for index in range(4))
        (closure / 'fits.may').write_text(imports + 'print(g0() + g3());\n')
        result = invoke(closure / 'fits.may')
        assert result.returncode == 0, result
        assert subprocess.run([str(binary)], capture_output=True, timeout=10).stdout == b'3\n'
        # Code after an import on the same line exercises column padding.
        for name, text in (('over.may', imports + 'import "nested.may"; print(g4());\n'),):
            (closure / name).write_text(text)
            for options in ([], ['--raw'], ['--check']):
                binary.write_bytes(b'previous output')
                result = invoke(closure / name, *options)
                expected = (f'{closure}/b4.may:1: imported sources exceed the 4 MiB expansion limit\n'
                            f'  imported from {closure}/nested.may:2\n'
                            f'  imported from {closure}/{name}:5\n').encode()
                assert result.returncode == 1 and result.stderr == expected, (name, options, result)
                assert binary.read_bytes() == b'previous output'
        print('PASS aggregate import closures are bounded with the import chain in the diagnostic')

        sidecar_duplicates(compiler, work)


def definition_line(path, name):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if re.match(rf'fun {name}\(', line):
            return number
    raise AssertionError(f'{name} is not defined in {path}')


def sidecar_duplicates(compiler, work):
    """A second definition of a runtime or library function is an error (#114)."""
    launcher = compiler
    built = launcher.parent / 'build/bin/mayc_new'
    executable = built if built.exists() else launcher
    source = work / 'duplicates.may'
    source.write_text('print([...[1, 2], 3]);\n')
    binary = work / 'duplicates'
    checkout = ROOT / 'compiler/mayc'
    cases = (
        ('runtime/fat_linux.may', 'fun rt_extend(p: Any, extra: Any) -> Any { return 0; }\n',
         'rt_extend', 'runtime/fat.may', 'runtime/fat_linux.may'),
        ('native.may', 'fun inc(x: Any) -> Any { return x; }\n',
         'inc', 'prelude.may', 'native.may'),
        ('native.may', 'fun rt_len(t: Any, v: Any) -> Any { return 0; }\n',
         'rt_len', 'runtime/fat.may', 'native.may'),
    )
    for sidecar, extra, name, first, second in cases:
        copy = work / f'sidecars-{name}'
        copy.mkdir()
        shutil.copy2(executable, copy / 'mayc')
        shutil.copytree(checkout / 'runtime', copy / 'runtime')
        shutil.copy2(checkout / 'native.may', copy / 'native.may')
        shutil.copy2(ROOT / 'stdlib/prelude.may', copy / 'prelude.may')
        line = definition_line(copy / first, name)
        with open(copy / sidecar, 'a') as handle:
            handle.write(extra)
        binary.write_bytes(b'previous output')
        result = subprocess.run([str(copy / 'mayc'), str(source), '-o', str(binary)],
                                capture_output=True, timeout=60, cwd=work)
        error = result.stderr.decode(errors='replace')
        assert result.returncode == 1, (name, result)
        assert f'duplicate runtime function `{name}`; first defined at {first}:{line}' in error, (name, error)
        assert second in error and '^' in error, (name, error)
        assert binary.read_bytes() == b'previous output', name
    print('PASS duplicate runtime and library functions name both definitions')

    # The unmodified sidecars have no duplicates, and user code may still
    # shadow a library function.
    source.write_text('fun repeat(s: Any, n: Any) -> Any { return "mine"; }\nprint(repeat("a", 3), substring("hello", 1, 3), [...[1, 2], 3]);\n')
    result = subprocess.run([str(compiler), str(source), '-o', str(binary)], capture_output=True, timeout=60)
    assert result.returncode == 0, result
    result = subprocess.run([str(binary)], capture_output=True, timeout=10)
    assert result.stdout == b'mine ell [1, 2, 3]\n', result
    print('PASS user functions shadow library functions')


if __name__ == '__main__':
    main()
