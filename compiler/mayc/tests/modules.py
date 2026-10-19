#!/usr/bin/env python3
"""Exercise module identities, visibility and import parsing in both modes."""
import argparse
import os
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
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
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
        for name, origin in {'runtime.may': ROOT / 'compiler/mayc/runtime.may',
                             'native.may': ROOT / 'compiler/mayc/native.may',
                             'prelude.may': ROOT / 'stdlib/prelude.may'}.items():
            (install / name).symlink_to(origin)
        (install / 'runtime').symlink_to(ROOT / 'compiler/mayc/runtime')
        (install / 'stdlib').mkdir()
        (install / 'stdlib/string.may').write_text('pub fun marker() -> Int { return 42; }\n')
        source = work / 'relocated.may'
        source.write_text('import "string" as strings;\nprint(strings.marker());\n')
        binary = work / 'relocated'
        result = subprocess.run([str(relocated), str(source), '-o', str(binary)],
                                cwd=work, capture_output=True, timeout=60,
                                env={key: value for key, value in os.environ.items() if key != 'MAYLANG_STDLIB'})
        assert result.returncode == 0, result.stderr
        result = subprocess.run([str(binary)], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == b'42\n', result
        count += 1
        print('PASS modules relocated compiler standard library', flush=True)
        overrides = work / 'override'; overrides.mkdir()
        (overrides / 'string.may').write_text('pub fun marker() -> Int { return 73; }\n')
        result = subprocess.run([str(relocated), str(source), '-o', str(binary)],
                                cwd=work, capture_output=True, timeout=60,
                                env={**os.environ, 'MAYLANG_STDLIB': str(work / 'missing') + ':' + str(overrides)})
        assert result.returncode == 0, result.stderr
        assert subprocess.check_output([str(binary)]) == b'73\n'
        count += 1
        print('PASS modules explicit standard library overrides', flush=True)
        
        # Regression: modules sharing a filename must have unique ELF symbols.
        collision = work / "duplicate-filename-symbols::λ"
        (collision / "alpha").mkdir(parents=True)
        (collision / "beta").mkdir()

        (collision / "alpha/utils.may").write_text(
            "pub let answer: Int = 11;\npub fun value() -> Int { return answer; }\n"
        )
        (collision / "beta/utils.may").write_text(
            "pub let answer: Int = 22;\npub fun value() -> Int { return answer; }\n"
        )

        source = collision / "main.may"
        source.write_text(
            'import "alpha/utils" as a;\n'
            'import "beta/utils" as b;\n'
            'print(a.value(), b.value());\n'
        )

        relocated_project = work / "different-root" / "project"
        shutil.copytree(collision, relocated_project)
        for mode in ("--strict", "--legacy"):
            binary = collision / f"app-{mode[2:]}"
            result = subprocess.run(
                [str(compiler), mode, str(source), "-o", str(binary)],
                cwd=collision,
                capture_output=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr

            execution = subprocess.run(
                [str(binary)], capture_output=True, timeout=10
            )
            assert execution.returncode == 0, execution.stderr
            assert execution.stdout == b"11 22\n", execution.stdout

            nm = subprocess.run(
                ["nm", "--defined-only", str(binary)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )

            function_symbols = []
            for line in nm.stdout.splitlines():
                parts = line.split(maxsplit=2)
                if (
                    len(parts) == 3
                    and parts[1] in ("T", "t")
                    and parts[2].endswith("::value")
                ):
                    function_symbols.append(parts[2])

            assert len(function_symbols) == 2, function_symbols
            assert len(set(function_symbols)) == 2, (
                f"Duplicate ELF symbols: {function_symbols}"
            )
            assert all(
                not name.startswith("/") for name in function_symbols
            ), f"Absolute source path leaked: {function_symbols}"

            moved_binary = relocated_project / f"app-{mode[2:]}"
            subprocess.run([str(compiler), mode, "main.may", "-o", str(moved_binary)],
                           cwd=relocated_project, check=True, capture_output=True, timeout=60)
            assert subprocess.check_output([str(moved_binary)]) == b"11 22\n"
            moved_symbols = subprocess.check_output(
                ["nm", "--defined-only", str(moved_binary)], text=True, timeout=10)
            original_names = sorted(line.split(maxsplit=2)[2] for line in nm.stdout.splitlines())
            moved_names = sorted(line.split(maxsplit=2)[2] for line in moved_symbols.splitlines())
            assert len(original_names) == len(set(original_names)), original_names
            assert original_names == moved_names, (original_names, moved_names)
            assert all(str(work) not in name for name in original_names), original_names

            count += 1
            print(
                f"PASS modules {mode[2:]} duplicate filename and relocated symbols",
                flush=True,
            )

    assert not failures, failures
    print(f'{count} module checks passed', flush=True)


if __name__ == '__main__':
    main()
