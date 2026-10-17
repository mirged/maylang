#!/usr/bin/env python3
"""Exercise internal callable effect rows without enabling callback syntax."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from backends import HERE, ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    compiler = compiler_binary(parser.parse_args().compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-function-rows-') as directory:
        work = Path(directory)
        binary = work / 'type_rows'
        result = subprocess.run([str(compiler), str(HERE / 'behavior/type_rows.may'), '-o', str(binary)],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        assert (result.returncode, result.stdout, result.stderr) == (0, 'behavior function type rows: passed\n', ''), result
        # Ordinary generic higher-order programs retain their current value
        # typing while rows on unannotated callable interfaces stay unknown.
        source = work / 'generic.may'
        source.write_text('fun apply<T>(f: Fn(T) -> T, value: T) -> T { return f(value); } '
            'fun increment(n: Int) -> Int { return n + 1; } '
            'print(apply(increment, 41));')
        result = subprocess.run([str(compiler), str(source), '-o', str(binary)],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        assert (result.returncode, result.stdout, result.stderr) == (0, '42\n', ''), result
    print('behavior function types: passed')


if __name__ == '__main__':
    main()
