#!/usr/bin/env python3
"""Verify stable-release selection and checksum-gated unattended upgrades."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'auto_update.py'
spec = importlib.util.spec_from_file_location('auto_update', SCRIPT)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='maylang-auto-update-test-')
        self.addCleanup(temporary.cleanup)
        self.prefix = Path(temporary.name) / "prefix with ' quotes"
        release = self.prefix / 'releases/old'
        release.mkdir(parents=True)
        (release / 'VERSION').write_text('0.12.2\n')
        (self.prefix / 'current').symlink_to('releases/old')
        self.state = {'format': 'maylang-prefix-v1', 'prefix': str(self.prefix),
                      'components': ['mayc', 'maypkg'], 'profiles': ['/example/.bashrc'],
                      'releases': ['old']}
        self.write_state()
        self.release = {'tag_name': 'v0.13.0', 'draft': False, 'prerelease': False, 'assets': []}

    def write_state(self):
        (self.prefix / '.maylang-install.json').write_text(json.dumps(self.state))

    def assets(self, content=b'fixture installer', checksum=None):
        digest = hashlib.sha256(content).hexdigest()
        data = {updater.ASSET: content, updater.ASSET + '.sha256':
                (checksum or f'{digest}  {updater.ASSET}\n').encode()}
        self.release['assets'] = [{'name': name,
                                  'browser_download_url': f'{updater.RELEASES}/v0.13.0/{name}',
                                  'digest': 'sha256:' + hashlib.sha256(body).hexdigest()}
                                 for name, body in data.items()]
        return {asset['browser_download_url']: data[asset['name']] for asset in self.release['assets']}

    def test_version_order_and_no_downgrade(self):
        self.assertLess(updater.version_key('v0.9.0'), updater.version_key('0.12.2'))
        self.assertLess(updater.version_key('0.13.0-rc.1'), updater.version_key('v0.13.0'))
        for version in ['0.13.0', '0.14.0', '0.14.0-rc.1']:
            (self.prefix / 'current/VERSION').write_text(version)
            with patch.object(updater, 'latest_release', return_value=self.release), \
                    patch.object(updater, 'download_asset') as download, patch('builtins.print'):
                updater.update(self.prefix)
                download.assert_not_called()

    def test_check_only_preserves_installation(self):
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'download_asset') as download, patch('builtins.print'):
            updater.update(self.prefix, check=True)
            download.assert_not_called()
        self.assertEqual((self.prefix / 'current').readlink(), Path('releases/old'))

    def test_upgrade_uses_verified_installer_and_preserves_components(self):
        content = b'''#!/usr/bin/python3
import json, os, pathlib, sys
args = sys.argv[1:]
prefix = pathlib.Path(args[args.index('--prefix') + 1])
assert '--yes' in args and '--no-modify-path' in args and '--plain' in args
assert args[args.index('--components') + 1] == 'mayc,maypkg'
assert 'MAYC' not in os.environ and 'MAYLANG_STDLIB' not in os.environ
(prefix / 'current/VERSION').write_text('0.13.0\\n')
(prefix / 'installer-ran').write_text(json.dumps(args))
'''
        downloads = self.assets(content)
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'request', side_effect=lambda url: io.BytesIO(downloads[url])), \
                patch.dict('os.environ', {'MAYC': '/wrong/compiler', 'MAYLANG_STDLIB': '/wrong/stdlib'}), \
                patch('builtins.print'):
            updater.update(self.prefix)
        self.assertTrue((self.prefix / 'installer-ran').exists())
        self.assertEqual((self.prefix / 'current/VERSION').read_text().strip(), '0.13.0')
        self.assertEqual(json.loads((self.prefix / '.maylang-install.json').read_text()), self.state)

    def test_checksum_failure_never_executes(self):
        downloads = self.assets(checksum='0' * 64 + '  ' + updater.ASSET + '\n')
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'request', side_effect=lambda url: io.BytesIO(downloads[url])), \
                patch.object(subprocess, 'run') as run, patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                updater.update(self.prefix)
            run.assert_not_called()
        self.assertEqual((self.prefix / 'current/VERSION').read_text(), '0.12.2\n')

    def test_asset_digest_and_download_failure_never_execute(self):
        downloads = self.assets()
        self.release['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'request', side_effect=lambda url: io.BytesIO(downloads[url])), \
                patch.object(subprocess, 'run') as run, patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'asset digest'):
                updater.update(self.prefix)
            run.assert_not_called()
        self.release['assets'] = []
        with patch.object(updater, 'latest_release', return_value=self.release), patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'missing the official asset'):
                updater.update(self.prefix)

    def test_release_metadata_rejects_preview_and_invalid_tags(self):
        for change in [{'prerelease': True}, {'draft': True}, {'tag_name': 'v0.13.0-rc.1'},
                       {'tag_name': '../other'}]:
            metadata = json.dumps({**self.release, **change}).encode()
            with patch.object(updater, 'request', return_value=io.BytesIO(metadata)):
                with self.assertRaisesRegex(ValueError, 'not a stable version'):
                    updater.latest_release()
        with patch.object(updater, 'request', return_value=io.BytesIO(json.dumps(self.release).encode())):
            self.assertEqual(updater.latest_release(), self.release)

    def test_unmanaged_install_and_invalid_components_fail_before_network(self):
        for change in [{'format': 'other'}, {'prefix': '/wrong'}, {'components': ['other']},
                       {'components': []}]:
            original = self.state.copy()
            self.state.update(change)
            self.write_state()
            with patch.object(updater, 'latest_release') as latest:
                with self.assertRaises(ValueError):
                    updater.update(self.prefix)
                latest.assert_not_called()
            self.state = original
        self.write_state()
        (self.prefix / 'current').unlink()
        (self.prefix / 'current').symlink_to('/tmp')
        with self.assertRaisesRegex(ValueError, 'managed releases directory'):
            updater.managed_install(self.prefix)

    def test_failed_installer_and_unexpected_version_are_not_success(self):
        downloads = self.assets()
        for outcome in [subprocess.CalledProcessError(1, 'fixture'), None]:
            with patch.object(updater, 'latest_release', return_value=self.release), \
                    patch.object(updater, 'request', side_effect=lambda url: io.BytesIO(downloads[url])), \
                    patch.object(subprocess, 'run', side_effect=outcome), patch('builtins.print'):
                with self.assertRaises((subprocess.CalledProcessError, ValueError)):
                    updater.update(self.prefix)
            self.assertEqual((self.prefix / 'current/VERSION').read_text(), '0.12.2\n')
            self.assertEqual((self.prefix / 'current').readlink(), Path('releases/old'))

    def test_concurrent_update_does_not_start_another(self):
        cache = self.prefix / 'cache'
        with patch('sys.argv', ['auto_update.py', '--prefix', str(self.prefix)]), \
                patch.dict('os.environ', {'XDG_CACHE_HOME': str(cache)}), \
                patch.object(updater.fcntl, 'flock', side_effect=BlockingIOError), \
                patch.object(updater, 'update') as update, patch('builtins.print'):
            updater.main()
            update.assert_not_called()

    def test_download_limit_and_wrong_checksum_filename(self):
        downloads = self.assets()
        destination = self.prefix / 'download'
        with patch.object(updater, 'request', return_value=io.BytesIO(b'x' * 10)):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                updater.download_asset(self.release, updater.ASSET, destination, 5)
        digest = hashlib.sha256(b'fixture installer').hexdigest()
        downloads = self.assets(checksum=f'{digest}  wrong-name\n')
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'request', side_effect=lambda url: io.BytesIO(downloads[url])), \
                patch.object(subprocess, 'run') as run, patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                updater.update(self.prefix)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
