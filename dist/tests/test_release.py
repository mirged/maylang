#!/usr/bin/env python3
"""Release provenance checks against real lightweight/annotated Git tags."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('package', Path(__file__).parents[1] / 'package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class ReleaseTests(unittest.TestCase):
    def test_release_identity(self):
        with tempfile.TemporaryDirectory(prefix='maylang-identity-') as directory:
            previous = package.ROOT
            package.ROOT = Path(directory)
            try:
                path = package.ROOT / 'RELEASE.json'
                valid = {'version': '0.10.0', 'codename': 'Aster', 'date': '2026-10-12'}
                path.write_text(json.dumps(valid))
                self.assertEqual(package.release_metadata('0.10.0'), valid)
                invalid = [
                    {'version': '0.9.0'}, {'codename': 'aster'},
                    {'codename': 'Aster\nextra'}, {'date': '2026-02-29'},
                    {'date': '20261012'}, {'date': '2026-10-12-nightly'},
                    {'codename': None}, {'codename': 42},
                    {'date': None}, {'date': 20261012},
                ]
                for replacement in invalid:
                    with self.subTest(replacement=replacement):
                        path.write_text(json.dumps(valid | replacement))
                        with self.assertRaises(ValueError):
                            package.release_metadata('0.10.0')
                for value in (None, [], '0.10.0', 42):
                    with self.subTest(value=value):
                        path.write_text(json.dumps(value))
                        with self.assertRaisesRegex(ValueError, 'must contain an object'):
                            package.release_metadata('0.10.0')
            finally:
                package.ROOT = previous

    def test_release_source_contract(self):
        with tempfile.TemporaryDirectory(prefix='maylang-release-') as directory:
            previous = package.ROOT
            package.ROOT = Path(directory)
            try:
                def git(*args):
                    return package.run('git', *args)
                git('init', '-q')
                git('config', 'user.name', 'Release test')
                git('config', 'user.email', 'release@example.invalid')
                (package.ROOT / 'source').write_text('first')
                git('add', 'source')
                git('commit', '-qm', 'first')
                first = git('rev-parse', 'HEAD')
                git('tag', '-a', 'v1.2.3', '-m', 'version')
                self.assertEqual(package.release_provenance('v1.2.3', '1.2.3', first), 'v1.2.3')
                with self.assertRaises(ValueError):
                    package.release_provenance('v1.2.3', '1.2.4', first)
                (package.ROOT / 'source').write_text('second')
                with self.assertRaises(ValueError):
                    package.release_provenance('v1.2.3', '1.2.3', first)
                git('commit', '-qam', 'second')
                with self.assertRaises(ValueError):
                    package.release_provenance('v1.2.3', '1.2.3', git('rev-parse', 'HEAD'))
                git('tag', 'v1.2.4')
                self.assertEqual(package.release_provenance('v1.2.4', '1.2.4', git('rev-parse', 'HEAD')), 'v1.2.4')
                (package.ROOT / 'untracked').write_text('dirty')
                with self.assertRaises(ValueError):
                    package.release_provenance('v1.2.4', '1.2.4', git('rev-parse', 'HEAD'))
            finally:
                package.ROOT = previous


if __name__ == '__main__':
    unittest.main()
