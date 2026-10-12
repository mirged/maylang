#!/usr/bin/env python3
"""Release provenance checks against real lightweight/annotated Git tags."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('package', Path(__file__).parents[1] / 'package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class ReleaseTests(unittest.TestCase):
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
