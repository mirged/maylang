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

    def test_distribution_python_compatibility_entrypoints(self):
        for name in ('package', 'update'):
            old = subprocess.run(['python3', str(ROOT / f'toolchain/{name}.py'), '--help'],
                                 capture_output=True, text=True, check=True)
            new = subprocess.run(['python3', str(ROOT / f'toolchain/distribution/{name}.py'), '--help'],
                                 capture_output=True, text=True, check=True)
            self.assertEqual(old.stdout, new.stdout)

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


if __name__ == '__main__':
    unittest.main()
