#!/usr/bin/env python3
"""Formatter idempotence, literal/comment preservation and executable behavior."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
ENV = os.environ.copy()
ENV['MAYLANG_STDLIB'] = str(ROOT / 'stdlib')


def run(*args, expected=0):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=ENV,
                            capture_output=True, timeout=120)
    assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory(prefix='mayfmt-test-') as directory:
    work = Path(directory)
    compiler = Path(ENV.get('MAYC', str(ROOT / 'compiler/mayc/mayc_new'))).resolve()
    formatter = work / 'mayfmt'
    run(compiler, ROOT / 'tools/mayfmt/main.may', '-o', formatter)
    snippets = [
        'fun twice(x:Int)->Int{return x*2;}print(twice(21));',
        'let values:List<Int> =[1,2,3];for x:Int in values{print(x);}',
        'let x:Int=7;print("λ🙂 ${x} { } // \\\" quote");',
        'let text:Str="first  \n  second\nlast";print(text);',
        'let x:Int=2;print("${if(x>1){"yes"}else{"no"}}");',
        '/* outer { /* inner */ } */ let x:Float=1.25e+2; print(x); // tail',
        'fun classify(x:Int)->Str{return if(x>0){"yes"}else{"no"};}print(classify(-1));',
        'enum E{A(n:Int),B}fun f(x:E)->Int{return match(x){A(n)=>n,B()=>0};}print(f(A(42)));',
        'print(2**3);print(sum(1..=3));',
        'let xs: List<List<Int>> = [\n[1,2],\n[3,4],\n]; print(xs);',
        '/* hidden module\nimport "does-not-exist";\n/* nested */\n*/ print(42);',
        'let text:Str="hello\nimport does_not_exist;\nbye";print(text);',
        'print("${1 /* } \" ignored */ + 2}");',
    ]
    for index, text in enumerate(snippets):
        source = work / f'case{index}.may'
        source.write_text(text)
        before = work / 'before'
        after = work / 'after'
        run(compiler, source, '-o', before)
        expected = run(before).stdout
        run(formatter, '--check', source, expected=1)
        assert source.read_text() == text
        run(formatter, source)
        formatted = source.read_text()
        run(formatter, '--check', source)
        run(compiler, source, '-o', after)
        assert run(after).stdout == expected, (index, formatted)
        if index in (2, 3, 4):
            literal = text[text.index('"'):text.rindex('"') + 1]
            assert literal in formatted, (literal, formatted)
    invalid = work / 'invalid.may'
    invalid.write_text('let s: Str = "unterminated')
    original = invalid.read_bytes()
    result = run(formatter, invalid, expected=70)
    assert b'unterminated string' in result.stdout and invalid.read_bytes() == original
    unformatted = work / 'help-untouched.may'
    unformatted.write_text('print( 1 );')
    help_original = unformatted.read_bytes()
    for flags in (['--help'], ['-h'], [work / 'missing.may', '--help'], [unformatted, '-h']):
        result = run(formatter, *flags)
        assert b'usage: mayfmt' in result.stdout and b'--check' in result.stdout, (flags, result.stdout)
    assert unformatted.read_bytes() == help_original
    assert b'usage: mayfmt' in run(formatter, expected=2).stdout
    result = run(formatter, unformatted, '--bogus', expected=70)
    assert b'unknown option --bogus' in result.stdout + result.stderr
    assert unformatted.read_bytes() == help_original
    print('PASS help flags and usage errors')
    print('PASS formatter semantics, typed patterns, Unicode/interpolation, comments, idempotence and safe failure')
