#!/usr/bin/env python3
"""Nested comments agree across native/LLVM, modules and interpolations."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
parser.add_argument('--llvm', action='store_true')
args = parser.parse_args()
env = os.environ.copy()
env['MAYLANG_STDLIB'] = str(ROOT / 'stdlib')
options = ['--target', 'clang-llvm'] if args.llvm else []
with tempfile.TemporaryDirectory(prefix='mayc-comments-') as directory:
    root = Path(directory)
    source = root / 'main.may'
    library = root / 'library.may'
    library.write_text('/* hidden\nimport "missing";\n/* nested */\n*/\npub fun answer() -> Int { return 42; }\n')
    source.write_text('import "library.may" as library;\n/* } " /* nested */ still a comment */\nprint(library.answer());\nprint("${1 /* } \\\" ignored */ + 2}");\nlet text: Str = "start\nimport hidden;\nend";\nprint(text);\n')
    binary = root / 'program'
    result = subprocess.run([str(args.compiler.resolve()), *options, str(source), '-o', str(binary)],
                            env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, timeout=30)
    assert result.returncode == 0 and result.stdout == b'42\n3\nstart\nimport hidden;\nend\n', result
    source.write_text('import "library.may" as library; import "math" as math; print(library.answer() + math.gcd(6, 9));\n')
    result = subprocess.run([str(args.compiler.resolve()), *options, str(source), '-o', str(binary)], env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, timeout=30)
    assert result.returncode == 0 and result.stdout == b'45\n', result
    source.write_text('from "library.may" import answer; print(answer());\n')
    result = subprocess.run([str(args.compiler.resolve()), *options, str(source), '-o', str(binary)], env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert subprocess.check_output([str(binary)], timeout=30) == b'42\n'
    broken = 'import "library.may" as library; let broken: Int = "text";\n'
    source.write_text(broken)
    result = subprocess.run([str(args.compiler.resolve()), *options, '--diagnostics', 'json', '--check', str(source)], env=env, capture_output=True, timeout=30)
    report = json.loads(result.stderr)
    assert result.returncode != 0 and 'expected Int, found Str' in str(report), result
    diagnostic = report['diagnostics'][0]
    assert diagnostic['range']['start'] == {'line': 1, 'column': broken.index('let') + 1}, diagnostic
    source.write_text('print(1);\n/* unterminated /* nested */\n')
    result = subprocess.run([str(args.compiler.resolve()), *options, '--diagnostics', 'json', '--check', str(source)],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode != 0, result
    report = json.loads(result.stderr)
    assert 'unterminated block comment' in json.dumps(report) and 'lex' in json.dumps(report), report
    print('PASS nested comments, hidden imports, interpolation and unterminated diagnostics' + (' (LLVM)' if args.llvm else ' (native)'))
