#!/usr/bin/env python3
"""Exercise developer prerequisite failures, environment quoting and CLI shims."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


doctor = module('doctor')
builder = module('build_tools')
checker = module('check_repository')


class DeveloperTests(unittest.TestCase):
    def test_browser_profile_requires_libcurl_development_files(self):
        for code in (0, 1):
            with self.subTest(code=code), \
                    patch.object(doctor.shutil, 'which', return_value='/usr/bin/cc'), \
                    patch.object(doctor, 'probe_c_compiler', return_value=(True, 'cc')), \
                    patch.object(doctor.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], code)) as run:
                checks = doctor.inspect('browser')
                curl = next(entry for entry in checks if entry[0] == 'libcurl development files')
                self.assertEqual(curl[1], code == 0)
                self.assertIn('libcurl4-openssl-dev', curl[2])
                self.assertTrue(any('-lcurl' in call.args[0] and
                                    '#include <curl/curl.h>' in call.kwargs.get('input', '')
                                    for call in run.call_args_list))

    def test_missing_tools_fail_with_instructions(self):
        with patch.object(doctor.shutil, 'which', return_value=None):
            checks = doctor.inspect('build')
        missing = [entry for entry in checks if not entry[1]]
        self.assertTrue({'cargo', 'rustc', 'cc', 'make', 'sha256sum'} <= {item[0] for item in missing})
        self.assertTrue(all(item[2] for item in missing))
        result = subprocess.run(['/usr/bin/python3', str(ROOT / 'scripts/doctor.py')],
                                env={**os.environ, 'PATH': ''}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('MISSING cargo', result.stdout)

    def test_c_compiler_probe_requires_a_working_compiler(self):
        with tempfile.TemporaryDirectory(prefix='may doctor ') as temporary:
            directory = Path(temporary)
            scripts = {
                'working cc': '#!/bin/sh\nexec cc "$@"\n',
                'failing cc': '#!/bin/sh\necho "probe.c: fatal error: no headers" >&2\nexit 3\n',
                'slow cc': '#!/bin/sh\nsleep 5\n',
            }
            for name, body in scripts.items():
                (directory / name).write_text(body)
                (directory / name).chmod(0o755)
            not_executable = directory / 'plain file'
            not_executable.write_text('')
            before = set(Path(tempfile.gettempdir()).glob('maylang-doctor-*'))

            ready, detail = doctor.probe_c_compiler(str(directory / 'working cc'))
            self.assertTrue(ready, detail)
            ready, detail = doctor.probe_c_compiler(str(directory / 'failing cc'))
            self.assertFalse(ready)
            self.assertIn('exit 3', detail)
            self.assertIn('no headers', detail)
            self.assertIn('set CC', detail)
            ready, detail = doctor.probe_c_compiler(str(not_executable))
            self.assertFalse(ready)
            self.assertIn('could not run', detail)
            with patch.object(doctor.subprocess, 'run',
                              side_effect=subprocess.TimeoutExpired('cc', 30)):
                ready, detail = doctor.probe_c_compiler(str(directory / 'slow cc'))
            self.assertFalse(ready)
            self.assertIn('timed out', detail)
            self.assertEqual(set(Path(tempfile.gettempdir()).glob('maylang-doctor-*')), before)

            for cc, code in (('/usr/bin/false', 1), (str(directory / 'working cc'), 0)):
                with self.subTest(cc=cc):
                    result = subprocess.run(['/usr/bin/python3', str(ROOT / 'scripts/doctor.py'),
                                             '--profile', 'build'], env={**os.environ, 'CC': cc},
                                            capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, code, result.stdout)
                    self.assertIn(('OK cc: ' if code == 0 else 'MISSING cc: ') + cc, result.stdout)
            with patch.object(doctor, 'probe_c_compiler') as probe:
                doctor.inspect('editor')
            probe.assert_not_called()

    def test_shell_environment_handles_metacharacters_and_repeated_sourcing(self):
        with tempfile.TemporaryDirectory(prefix="may tools ' $ ") as temporary:
            output = Path(temporary)
            script = output / 'env.sh'
            with patch.object(builder, 'ROOT', output / 'checkout with spaces'):
                script.write_text(builder.environment(output))
            result = subprocess.run(['sh', '-c', '. "$1"; first=$PATH; . "$1"; '
                                     'test "$first" = "$PATH" || exit 9; '
                                     'printf "%s\\n%s\\n%s\\n" "$MAYC" "$MAYLANG_STDLIB" "$PATH"',
                                     'sh', str(script)], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), [str(output / 'bin/mayc'),
                             str(output / 'stdlib'),
                             str(output / 'bin') + ':' + os.environ['PATH']])

    def test_failed_tool_build_preserves_existing_developer_tools(self):
        with tempfile.TemporaryDirectory(prefix='may-build-failure-') as temporary:
            directory = Path(temporary)
            output = directory / 'dev'
            output.mkdir()
            (output / 'env.sh').write_text('previous environment')
            compiler = directory / 'compiler'
            compiler.write_text('fixture')
            with patch.object(builder.subprocess, 'run', side_effect=[None, subprocess.CalledProcessError(1, 'may')]):
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.build(compiler, output)
            self.assertEqual((output / 'env.sh').read_text(), 'previous environment')
            self.assertEqual(list(output.iterdir()), [output / 'env.sh'])
            self.assertFalse(list(directory.glob('.tools-*')))

    def test_repository_check_distinguishes_links_and_code_examples(self):
        with tempfile.TemporaryDirectory(prefix='may-links-') as temporary:
            directory = Path(temporary)
            doc = directory / 'README.md'
            doc.write_text('[missing](absent.md)\n[`source`](valid.py)\n'
                           '`array[i](x)`\n```md\n[example](not-a-real-file)\n```\n')
            source = directory / 'valid.py'
            source.write_text('value = 1\n')
            invalid = directory / 'invalid.json'
            invalid.write_text('{invalid}')
            with patch.object(checker, 'ROOT', directory):
                errors = checker.problems([doc, source, invalid])
            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(any('absent.md' in error for error in errors))
            self.assertTrue(any('invalid.json' in error for error in errors))

    def test_repository_check_requires_identical_native_mirror(self):
        with tempfile.TemporaryDirectory(prefix='may-mirror-') as temporary:
            directory = Path(temporary)
            (directory / 'compiler/mayc').mkdir(parents=True)
            (directory / 'stdlib').mkdir()
            active = directory / 'compiler/mayc/native.may'
            mirror = directory / 'stdlib/native.may'
            active.write_text('fun join() -> Str { return "new"; }\n')
            mirror.write_text(active.read_text())
            with patch.object(checker, 'ROOT', directory):
                self.assertEqual(checker.mirrors(), [])
                mirror.write_text('fun join() -> Str { return "old"; }\n')
                errors = checker.mirrors()
            self.assertEqual(len(errors), 1, errors)
            self.assertIn('stdlib/native.may: differs from compiler/mayc/native.may', errors[0])

    def test_repository_check_reports_invalid_utf8_and_continues(self):
        with tempfile.TemporaryDirectory(prefix='may-encoding-') as temporary:
            directory = Path(temporary)
            paths = [directory / f'invalid{suffix}' for suffix in ('.py', '.json', '.md')]
            for path in paths:
                path.write_bytes(b'\xff')
            doc = directory / 'README.md'
            doc.write_text('[missing](absent.md)\n')
            with patch.object(checker, 'ROOT', directory):
                errors = checker.problems([*paths, doc])
            self.assertEqual(len(errors), 4, errors)
            for path in paths:
                self.assertTrue(any(f'{path.name}: invalid UTF-8' in error for error in errors))
            self.assertTrue(any('absent.md' in error for error in errors))

    def test_repository_check_handles_markdown_fence_variants(self):
        blocks = [
            '~~~md\n[example](absent.md)\n~~~\n',
            '   ```md\n[example](absent.md)\n   ```\n',
            '````md\n```\n[example](absent.md)\n````\n',
            '~~~md\n```\n[example](absent.md)\n~~~\n',
            '~~~md\n~~~ still code\n[example](absent.md)\n~~~\n',
            '~~~md\n[example](absent.md)\n',
        ]
        with tempfile.TemporaryDirectory(prefix='may-fences-') as temporary:
            directory = Path(temporary)
            doc = directory / 'README.md'
            for block in blocks:
                with self.subTest(block=block):
                    doc.write_text('[missing](outside.md)\n' + block)
                    with patch.object(checker, 'ROOT', directory):
                        errors = checker.problems([doc])
                    self.assertEqual(errors, ['README.md: missing local link outside.md'])


if __name__ == '__main__':
    unittest.main()
