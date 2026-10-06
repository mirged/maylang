#!/usr/bin/env python3
"""Exercise module identities, visibility and import parsing in both modes."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from backends import compiler_binary

ROOT = Path(__file__).resolve().parents[3]
LIBRARY = '''pub struct Point { x: Int }
pub enum Choice { Some(value: Int), Empty }
enum HiddenChoice { Hidden(value: Int) }
struct HiddenPoint { x: Int }
let secret: Int = 11;
pub let answer: Int = 7;
pub fun value() -> Int { return secret; }
fun hidden() -> Int { return 9; }
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    failures = []
    count = 0
    with tempfile.TemporaryDirectory(prefix='mayc-modules-') as directory:
        work = Path(directory)
        library = work / 'library.may'
        library.write_text(LIBRARY)
        (work / 'nested.dir').mkdir()
        (work / 'nested.dir/library.may').write_text(LIBRARY)
        (work / 'other.may').write_text('pub fun value() -> Int { return 22; }\n')
        (work / 'implicit.may').write_text('fun value() -> Int { return 33; }\n')
        (work / 'bridge.may').write_text('import "library" as lib;\npub fun bridge() -> Int { return lib.value(); }\n')
        passing = {
            'alias': ('import "library" as lib;\nprint(lib.value(), lib.answer);', '11 7\n'),
            'plain': ('import "library";\nprint(value(), answer, library.value());', '11 7 11\n'),
            'selective': ('from "library" import value, answer;\nprint(value(), answer);', '11 7\n'),
            'absolute': (f'import "{library}" as lib;\nprint(lib.value());', '11\n'),
            'dotted_directory': ('import "nested.dir/library" as lib;\nprint(lib.value());', '11\n'),
            'normalized_path': ('import "nested.dir/.././library" as lib;\nprint(lib.value());', '11\n'),
            'quoted_comment': ('import "library" as lib; // "comment"\nprint(lib.value());', '11\n'),
            'selective_comment': ('from "library" import answer; // "comment"\nprint(answer);', '7\n'),
            'tabs': ('import\t"library"\tas\tlib;\nprint(lib.value());', '11\n'),
            'selective_tabs': ('from\t"library"\timport\tanswer;\nprint(answer);', '7\n'),
            'compact': ('import"library" as lib;\nprint(lib.value());', '11\n'),
            'keyword_prefix': ('mut imported: Int = 1;\nmut fromage: Int = 2;\nimported = 7;\nfromage = 9;\nprint(imported, fromage);', '7 9\n'),
            'isolated_aliases': ('import "library" as a;\nimport "other" as b;\nprint(a.value(), b.value());', '11 22\n'),
            'implicit_exports': ('import "implicit" as lib;\nprint(lib.value());', '33\n'),
            'transitive': ('import "bridge" as b;\nprint(b.bridge());', '11\n'),
            'same_module_twice': (f'import "library" as a;\nimport "{library}" as b;\nprint(a.value(), b.value());', '11 11\n'),
            'same_plain_module_twice': (f'import "library";\nimport "{library}";\nprint(value());', '11\n'),
            'stdlib_alias': ('import "string" as strings;\nprint(strings.capitalize("hello"));', 'Hello\n'),
            'stdlib_plain': ('import "string";\nprint(capitalize("hello"));', 'Hello\n'),
            'stdlib_selective': ('from "string" import capitalize;\nprint(capitalize("hello"));', 'Hello\n'),
            'stdlib_duplicate_paths': (f'import "string" as a;\nimport "{ROOT / "stdlib/string.may"}" as b;\nprint(a.capitalize("hi"), b.capitalize("bye"));', 'Hi Bye\n'),
            'public_record': ('import "library" as lib;\nlet p: lib.Point = lib.Point(3);\nprint(p.x);', '3\n'),
        }
        rejected = {
            'private_function': ('import "library" as lib;\nprint(lib.hidden());', 'hidden'),
            'private_global': ('import "library" as lib;\nprint(lib.secret);', 'secret'),
            'private_constructor': ('import "library" as lib;\nprint(lib.HiddenPoint(3));', 'HiddenPoint'),
            'private_variant': ('import "library" as lib;\nprint(lib.Hidden(3));', 'Hidden'),
            'private_plain': ('import "library";\nprint(hidden());', 'hidden'),
            'private_selective': ('from "library" import hidden;\nprint(hidden());', 'hidden'),
            'unselected_name': ('from "library" import answer;\nprint(value());', 'value'),
            'alias_only': ('import "library" as lib;\nprint(value());', 'value'),
            'ambiguous_import': ('import "library";\nimport "other";\nprint(value());', 'ambiguous imported name'),
            'transitive_private': ('import "bridge";\nprint(value());', 'value'),
            'missing_quote': ('import "library;\nprint(1);', 'invalid import path'),
            'empty_path': ('import "";\nprint(1);', 'invalid import path'),
            'bare_import': ('import\nprint(1);', 'invalid import path'),
        }
        strict_pass = {
            'public_enum_alias': ('import "library" as lib;\nlet choice: lib.Choice = lib.Some(3);\nlet empty: lib.Choice = lib.Empty();\nprint(choice, empty);', '{"tag": "Some", "value": 3} {"tag": "Empty"}\n'),
            'public_enum_plain': ('import "library";\nlet choice: Choice = Some(3);\nprint(choice);', '{"tag": "Some", "value": 3}\n'),
            'public_enum_selective': ('from "library" import Choice, Some;\nlet choice: Choice = Some(3);\nprint(choice);', '{"tag": "Some", "value": 3}\n'),
        }
        strict_reject = {
            'private_record_type': ('import "library" as lib;\nfun f(p: lib.HiddenPoint) -> Int { return 1; }', 'HiddenPoint'),
            'private_enum_type': ('import "library" as lib;\nfun f(p: lib.HiddenChoice) -> Int { return 1; }', 'HiddenChoice'),
            'unselected_enum_type': ('from "library" import Some;\nlet p: Choice = Some(3);', 'Choice'),
        }
        for mode in ('--strict', '--legacy'):
            positives = passing | (strict_pass if mode == '--strict' else {})
            negatives = rejected | (strict_reject if mode == '--strict' else {})
            for reject, cases in ((False, positives), (True, negatives)):
                for name, (code, expected) in cases.items():
                    source = work / f'{mode[2:]}-{name}.may'
                    source.write_text(code + '\n')
                    binary = source.with_suffix('')
                    result = subprocess.run([str(compiler), mode, source.name, '-o', str(binary)],
                                            cwd=work, capture_output=True, timeout=60)
                    if reject:
                        ok = result.returncode > 0 and not binary.exists() and expected in result.stderr.decode()
                    else:
                        ok = result.returncode == 0
                        if ok:
                            result = subprocess.run([str(binary)], capture_output=True, timeout=10)
                            ok = result.returncode == 0 and result.stdout == expected.encode()
                    count += 1
                    print(f'{"PASS" if ok else "FAIL"} modules {mode[2:]} {name}', flush=True)
                    if not ok:
                        failures.append((mode, name, result.returncode, result.stdout, result.stderr))
        # Expansion itself must contain one copy, regardless of import spelling.
        source = work / 'deduplicate.may'
        source.write_text(f'import "library";\nimport "{library}";\n')
        result = subprocess.run([str(compiler), '--dump-expanded', source.name], cwd=work,
                                capture_output=True, timeout=60)
        assert result.returncode == 0 and result.stdout.count(b'pub fun value()') == 1, result
        count += 1
        print('PASS modules deduplicate source origins', flush=True)
        # Resolve the installed stdlib without depending on the checkout or cwd.
        install = work / 'install'
        install.mkdir()
        relocated = install / 'mayc'
        shutil.copy2(compiler_binary(compiler), relocated)
        for name, origin in {'runtime.may': ROOT / 'toolchain/mayc/runtime.may',
                             'native.may': ROOT / 'toolchain/mayc/native.may',
                             'prelude.may': ROOT / 'stdlib/prelude.may'}.items():
            (install / name).symlink_to(origin)
        (install / 'stdlib').mkdir()
        (install / 'stdlib/string.may').write_text('pub fun marker() -> Int { return 42; }\n')
        source = work / 'relocated.may'
        source.write_text('import "string" as strings;\nprint(strings.marker());\n')
        binary = work / 'relocated'
        result = subprocess.run([str(relocated), str(source), '-o', str(binary)],
                                cwd=work, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        result = subprocess.run([str(binary)], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == b'42\n', result
        count += 1
        print('PASS modules relocated compiler standard library', flush=True)
    assert not failures, failures
    print(f'{count} module checks passed', flush=True)


if __name__ == '__main__':
    main()
