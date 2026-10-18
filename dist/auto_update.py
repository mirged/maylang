#!/usr/bin/env python3
"""Upgrade a managed Linux installation to the newest stable GitHub release."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from urllib.error import URLError

API = 'https://api.github.com/repos/mirged/maylang/releases/latest'
RELEASES = 'https://github.com/mirged/maylang/releases/download'
ASSET = 'maylang-init-x86_64-linux'
TOOLS = {'mayc', 'may', 'mayfmt', 'maypkg', 'maylsp'}


def version_key(version):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?', version)
    if not match:
        raise ValueError(f'invalid release version: {version!r}')
    return (*map(int, match.groups()[:3]), match[4] is None)


def managed_install(prefix):
    state = json.loads((prefix / '.maylang-install.json').read_text())
    if not isinstance(state, dict) or state.get('format') != 'maylang-prefix-v1' or state.get('prefix') != str(prefix):
        raise ValueError(f'{prefix} is not a matching managed installation')
    components = state.get('components')
    if (not isinstance(components, list) or not components or
            any(not isinstance(name, str) or name not in TOOLS for name in components) or
            len(set(components)) != len(components) or
            'mayc' not in components):
        raise ValueError('installed component list is invalid')
    current = prefix / 'current'
    if not current.is_symlink() or not current.resolve().is_relative_to(prefix / 'releases'):
        raise ValueError('current must point into the managed releases directory')
    version = (current / 'VERSION').read_text().strip()
    version_key(version)
    return version, components


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'Maylang-auto-update', 'Accept': 'application/vnd.github+json',
    }), timeout=30)


def latest_release():
    with request(API) as response:
        release = json.loads(response.read(1024 * 1024))
    if not isinstance(release, dict):
        raise ValueError('invalid GitHub release metadata')
    tag = release.get('tag_name', '')
    if (not isinstance(tag, str) or release.get('draft') or release.get('prerelease') or
            not re.fullmatch(r'v\d+\.\d+\.\d+', tag)):
        raise ValueError('latest release is not a stable version')
    return release


def download_asset(release, name, destination, limit):
    assets = release.get('assets', [])
    if not isinstance(assets, list):
        raise ValueError('invalid GitHub asset metadata')
    asset = next((item for item in assets if isinstance(item, dict) and item.get('name') == name), None)
    url = f'{RELEASES}/{release["tag_name"]}/{name}'
    if not asset or asset.get('browser_download_url') != url:
        raise ValueError(f'release is missing the official asset {name}')
    digest = hashlib.sha256()
    total = 0
    with request(url) as response, destination.open('wb') as output:
        while block := response.read(65536):
            total += len(block)
            if total > limit:
                raise ValueError(f'{name} exceeds its download size limit')
            digest.update(block)
            output.write(block)
    actual = digest.hexdigest()
    if asset.get('digest') and asset['digest'] != 'sha256:' + actual:
        raise ValueError(f'{name} does not match its GitHub asset digest')
    return actual


def update(prefix, check=False):
    installed, components = managed_install(prefix)
    release = latest_release()
    tag = release['tag_name']
    if version_key(installed) >= version_key(tag):
        print(f'Maylang {installed} is current (latest stable: {tag}).')
        return
    if check:
        print(f'Maylang update available: {installed} -> {tag}.')
        return
    print(f'Updating Maylang {installed} -> {tag}.', flush=True)
    with tempfile.TemporaryDirectory(prefix='maylang-auto-update-') as directory:
        work = Path(directory)
        initializer = work / ASSET
        checksum = work / (ASSET + '.sha256')
        actual = download_asset(release, ASSET, initializer, 128 * 1024 * 1024)
        download_asset(release, ASSET + '.sha256', checksum, 4096)
        match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?' + re.escape(ASSET) + r'\s*', checksum.read_text())
        if not match or match[1].lower() != actual:
            raise ValueError('installer checksum mismatch; installation was not changed')
        initializer.chmod(0o700)
        environment = {key: value for key, value in os.environ.items() if key not in ('MAYC', 'MAYLANG_STDLIB')}
        subprocess.run([str(initializer), '--yes', '--prefix', str(prefix), '--no-modify-path',
                        '--plain', '--no-color', '--components', ','.join(components)],
                       env=environment, check=True, timeout=300)
    selected, selected_components = managed_install(prefix)
    if selected != tag.removeprefix('v') or set(selected_components) != set(components):
        raise ValueError('post-update version/component verification failed')
    print(f'Updated Maylang to {selected}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.maylang')
    parser.add_argument('--check', action='store_true', help='check for updates without installing')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('automatic updates currently require Linux x86-64')
    prefix = args.prefix.expanduser().resolve()
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'maylang'
    cache.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(str(prefix).encode()).hexdigest()[:16]
    with (cache / f'update-{identity}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A Maylang update is already running for this prefix.')
            return
        update(prefix, args.check)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, URLError, subprocess.SubprocessError) as error:
        print(f'maylang-auto-update: {error}', file=sys.stderr)
        sys.exit(1)
