#!/usr/bin/env python3
"""Compiler source reads distinguish empty files from failed reads."""
import argparse
from pathlib import Path
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

        def invoke(path, *options):
            return subprocess.run([str(compiler), *options, str(path), '-o', str(binary)],
                                  capture_output=True, timeout=60)

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


if __name__ == '__main__':
    main()
