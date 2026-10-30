#!/usr/bin/env python3
"""Exercise bundle switching and Bash migration in an isolated installation."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'update.py'


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maylang-update-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'releases with spaces'
        self.root.mkdir()
        self.bashrc = Path(self.temporary.name) / '.bashrc'
        self.bashrc.write_text('export KEEP_ME=yes\n')

    def bundle(self, version):
        path = self.root / f'maylang-{version}-x86_64-linux'
        (path / 'bin/runtime').mkdir(parents=True)
        (path / 'stdlib').mkdir()
        for name in ('mayc', 'may', 'mayfmt', 'maypkg', 'maylsp'):
            (path / 'bin' / name).write_text(f'#!/bin/sh\necho {version}\n')
        for name in ('runtime.may', 'native.may', 'prelude.may', 'runtime/core.may', 'runtime/math.may',
                     'runtime/fat.may', 'runtime/fat_linux.may'):
            (path / 'bin' / name).write_text('// fixture\n')
        (path / 'stdlib/prelude.may').write_text('// fixture\n')
        (path / 'VERSION').write_text(version + '\n')
        return path

    def update(self, *args, success=True):
        result = subprocess.run(['python3', str(SCRIPT), *args, '--root', str(self.root),
                                 '--bashrc', str(self.bashrc)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_latest_migration_switch_and_idempotence(self):
        older = self.bundle('0.9.0')
        newer = self.bundle('0.11.2')
        self.bundle('0.12.0-nightly')
        original = (f'export KEEP_ME=yes\nexport PATH="{older}/bin:$PATH"\n'
                    f'export PATH="$HOME/.maylang/bin:$PATH"\n'
                    f'export MAYLANG_STDLIB="{older}/stdlib"\n'
                    'export PATH="$HOME/.cargo/bin:$PATH"\n')
        self.bashrc.write_text(original)
        self.update()
        self.assertEqual((self.root / 'current').resolve(), newer)
        self.assertEqual(self.bashrc.with_name('.bashrc.maylang-backup').read_text(), original)
        self.assertNotIn(str(older), self.bashrc.read_text())
        self.assertIn('.cargo/bin', self.bashrc.read_text())
        updated = self.bashrc.read_text()
        self.update()
        self.assertEqual(self.bashrc.read_text(), updated)
        shell = subprocess.run(['bash', '--noprofile', '--norc', '-c', '''
source "$1"
test "$KEEP_ME" = yes || exit 10
mayc
maylang-update 0.9.0 >/dev/null || exit 11
mayc
printf '%s\n%s\n' "$MAYLANG_STDLIB" "$PATH"
source "$2"
printf '%s\n' "$PATH"
''', 'bash', str(self.bashrc), str(self.root / 'env.sh')],
            env={**os.environ, 'PATH': f'{older}/bin:{Path.home()}/.maylang/bin:/usr/bin:/bin'},
            capture_output=True, text=True)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        lines = shell.stdout.splitlines()
        self.assertEqual(lines[:2], ['0.11.2', '0.9.0'])
        self.assertEqual(lines[2], str(self.root / 'current/stdlib'))
        self.assertNotIn(str(older), lines[3])
        self.assertEqual(lines[3], lines[4])
        self.assertEqual((self.root / 'current').resolve(), older)

    def test_invalid_bundle_preserves_active_install(self):
        old = self.bundle('1.0.0')
        self.update('1.0.0')
        original = self.bashrc.read_text()
        incomplete = self.bundle('1.1.0')
        (incomplete / 'bin/runtime.may').unlink()
        self.update('1.1.0', success=False)
        self.assertEqual((self.root / 'current').resolve(), old)
        self.assertEqual(self.bashrc.read_text(), original)
        self.update('9.9.9', success=False)

    def test_dry_run_and_directory_selection(self):
        bundle = self.bundle('1.0.0')
        self.update(str(bundle), '--dry-run')
        self.assertFalse((self.root / 'current').exists())
        self.assertFalse((self.root / 'env.sh').exists())
        self.assertEqual(self.bashrc.read_text(), 'export KEEP_ME=yes\n')
        self.update(str(bundle))
        self.assertTrue(os.access(bundle / 'bin/mayc', os.X_OK))

    def test_empty_root_and_non_symlink_current(self):
        self.update(success=False)
        self.bundle('1.0.0')
        (self.root / 'current').mkdir()
        self.update(success=False)
        self.assertFalse((self.root / 'env.sh').exists())

    def test_malformed_managed_blocks_preserve_bashrc(self):
        self.bundle('1.0.0')
        start = '# >>> Maylang managed environment >>>\n'
        end = '# <<< Maylang managed environment <<<\n'
        for content in (start, end, start + start + end + end, end + start):
            with self.subTest(content=content):
                self.bashrc.write_text(content)
                result = self.update(success=False)
                self.assertIn('malformed Maylang managed block', result.stderr)
                self.assertEqual(self.bashrc.read_text(), content)
                self.assertFalse((self.root / 'env.sh').exists())
                self.assertFalse((self.root / 'current').is_symlink())


if __name__ == '__main__':
    unittest.main()
