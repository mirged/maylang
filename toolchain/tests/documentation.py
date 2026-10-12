#!/usr/bin/env python3
"""Compile and execute the actual complete snippets in maintained references."""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def snippets():
    expected = {'Hello': 'Hello, Maylang!\n', 'Typed function': '42\n',
                'Mutable accumulator': '6\n', 'Typed closure': '6\n',
                'Comprehension': '[4, 9]\n', 'Optional map lookup': '0\n',
                'Record': '7\n', 'Recovery': '42\n', 'Fault inspection': 'fail demo\n',
                'Match': 'two\n', 'Pipeline': '12\n', 'Math': '12\n',
                'Algorithms': '1\n', 'Collections': 'May\n',
                'CSV': '[["a", "b,c"]]\n', 'Random': None, 'Statistics': '1.5\n',
                'Result': '0\n', 'Tensor': '10.0\n', 'Validation': None}
    imports = {}
    seen = set()
    for line in (ROOT / 'reference/EXAMPLES.md').read_text().splitlines():
        match = re.match(r'- ([\w ]+): `([^`]+)`', line)
        if not match:
            continue
        title, source = match.groups()
        if title.endswith(' import'):
            imports[title.removesuffix(' import')] = source
            continue
        if title.endswith(' call'):
            title = title.removesuffix(' call')
            source = imports.pop(title) + '\n' + source
        assert title in expected, f'Add an output contract for {title}'
        seen.add(title)
        yield title, source, expected[title]
    assert not imports and seen == expected.keys(), (imports, seen ^ expected.keys())
    strict = re.findall(r'```may\n(.*?)\n```', (ROOT / 'docs/STRICT.md').read_text(), re.S)
    assert len(strict) == 4, 'Review added strict-guide examples and their expected output'
    for index, (source, stdout) in enumerate(zip(strict, ['50\n', '', '', ''])):
        yield f'STRICT.md example {index + 1}', source, stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    env = dict(os.environ, MAYLANG_STDLIB=str(ROOT / 'stdlib'))
    with tempfile.TemporaryDirectory(prefix='maylang-docs-') as directory:
        work = Path(directory)
        count = 0
        for title, body, expected in snippets():
            source = work / 'example.may'
            source.write_text(body + '\n')
            binary = work / 'example'
            result = subprocess.run([str(args.compiler.resolve()), str(source), '-o', str(binary)],
                                    cwd=ROOT, env=env, capture_output=True, timeout=120)
            assert result.returncode == 0, (title, result.stderr.decode())
            result = subprocess.run([str(binary)], cwd=work, capture_output=True, timeout=15)
            assert result.returncode == 0 and not result.stderr, (title, result)
            if expected is not None:
                assert result.stdout == expected.encode(), (title, result.stdout, expected)
            else:
                # The PRNG must be seeded and repeatable; structured validation
                # must retain its documented failing field, not just exit zero.
                if title == 'Random':
                    again = subprocess.run([str(binary)], cwd=work, capture_output=True, timeout=15)
                    assert again.returncode == 0 and again.stdout == result.stdout
                    assert 1 <= int(result.stdout) <= 6
                else:
                    assert b'email' in result.stdout, result.stdout
            count += 1
            print(f'PASS {title}', flush=True)
    print(f'PASS {count} runnable strict documentation examples')


if __name__ == '__main__':
    main()
