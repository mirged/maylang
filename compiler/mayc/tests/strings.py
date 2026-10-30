#!/usr/bin/env python3
"""Check native string operations against Python's Unicode string oracle."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def literal(value):
    return json.dumps(value, ensure_ascii=False).replace('\\u0000', '\\0')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    options = parser.parse_args()
    rng = random.Random(31)
    cases = [('', ','), ('', ''), ('a,,b,', ','), ('aaaaa', 'aa'),
             ('λ🙂/日本//é/', '/'), ('λ🙂λ🙂', 'λ🙂'), ('a\0λ\0\0🙂\0', '\0')]
    for _ in range(40):
        source = ''.join(rng.choice('ab/λé🙂日本\0\u0301') for _ in range(rng.randrange(1, 100)))
        delimiter = rng.choice(['', '/', 'λ', '🙂', '\0', 'ab', '日本', 'absent'])
        cases.append((source, delimiter))
    statements = []
    expected = []
    for source, delimiter in cases:
        fields = source.split(delimiter) if delimiter else [source]
        start = rng.randrange(len(source) + 1)
        count = rng.randrange(len(source) - start + 1)
        statements.extend([
            f'print(json_stringify(split({literal(source)}, {literal(delimiter)})));',
            f'print(json_stringify(chars({literal(source)})));',
            f'print(json_stringify(substring({literal(source)}, {start}, {count})));',
        ])
        # Compare parsed JSON so escaping choices are independent of the oracle.
        expected.extend([fields, list(source), source[start:start + count]])
    statements.extend([
        'let original: Str = "aλ🙂日本"; let copy: Str = substring(original, 1, 3);',
        'store8(addr(copy), 120); print(original == "aλ🙂日本");',
        'let large: Str = repeat("λ🙂/", 4000);',
        'let pieces: List<Str> = split(large, "/");',
        'print(len(chars(large)), len(pieces), join(pieces, "/") == large);',
        'print(json_stringify([env("MAY_STRING_ENV"), env("MAY_STRING_EMPTY"),',
        'env("STRING_ENV"), env("MAY_STRING_ABSENT"), env("MAY_STRING_LARGE") == repeat("λ🙂", 4000)]));',
    ])
    environment = dict(os.environ, MAY_STRING_ENV='value λ🙂 = spaces', MAY_STRING_EMPTY='',
                       MAY_STRING_LARGE='λ🙂' * 4000)
    environment.pop('STRING_ENV', None)
    environment.pop('MAY_STRING_ABSENT', None)
    with tempfile.TemporaryDirectory(prefix='mayc-strings-') as directory:
        work = Path(directory)
        source = work / 'strings.may'
        source.write_text('\n'.join(statements) + '\n')
        targets = ['x86_64-linux']
        for target in targets:
            binary = work / target
            subprocess.run([str(options.compiler.resolve()), '--target', target, str(source), '-o', str(binary)],
                           cwd=ROOT, check=True, timeout=120)
            result = subprocess.run([str(binary)], env=environment, capture_output=True, text=True, timeout=20)
            assert result.returncode == 0 and not result.stderr, result
            lines = result.stdout.splitlines()
            actual = [json.loads(line) for line in lines[:-3]]
            assert len(actual) == len(expected), (len(actual), len(expected))
            for index, (got, wanted) in enumerate(zip(actual, expected)):
                assert got == wanted, (target, index, got, wanted)
            assert lines[-3:-1] == ['true', '12000 4001 true'], lines[-3:]
            assert json.loads(lines[-1]) == ['value λ🙂 = spaces', '', None, None, True], lines[-1]
            print(f'PASS Unicode/NUL split, codepoint slices/chars, fresh copies and long environment on {target}', flush=True)


if __name__ == '__main__':
    main()
