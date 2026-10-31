#!/usr/bin/env python3
"""Check, verify and update vendored third-party files against their manifest.

Each vendored directory holds a ``vendor.json`` that records, for every file,
the upstream repository, the pinned revision, the path at that revision, the
license, a SHA-256 checksum and any local modifications.

  vendor.py check [DIR ...]        offline: every file is listed and matches its checksum
  vendor.py upstream [DIR ...]     download each pinned revision and compare (needs network)
  vendor.py update DIR FILE REV    replace FILE with upstream REV and record it

``check`` runs in ``make check`` and on the extracted release bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = [ROOT / 'stdlib/ui/native/vendor']
FIELDS = ('file', 'repository', 'revision', 'path', 'license', 'sha256', 'modifications')
# Files in a vendored directory that are Maylang's own documentation.
OWN = {'README.md', 'vendor.json'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest(directory):
    return json.loads((directory / 'vendor.json').read_text())


def raw_url(entry, revision=None):
    repository = entry['repository'].removeprefix('https://github.com/')
    return f'https://raw.githubusercontent.com/{repository}/{revision or entry["revision"]}/{entry["path"]}'


def check(directory):
    try:
        entries = manifest(directory)['vendored']
    except (OSError, ValueError, KeyError) as error:
        return [f'{directory}/vendor.json: unreadable manifest ({error})']
    errors = []
    listed = set()
    for entry in entries:
        missing = [field for field in FIELDS if not entry.get(field)]
        if missing:
            errors.append(f'{directory}/vendor.json: {entry.get("file", "?")} lacks {", ".join(missing)}')
            continue
        listed.add(entry['file'])
        path = directory / entry['file']
        if not path.is_file():
            errors.append(f'{path}: listed in vendor.json but missing')
        elif digest(path.read_bytes()) != entry['sha256']:
            errors.append(f'{path}: checksum differs from vendor.json; record the update with '
                          f'scripts/vendor.py update or document the local modification')
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in OWN and path.name not in listed:
            errors.append(f'{path}: vendored file is not listed in vendor.json')
    return errors


def upstream(directory):
    errors = []
    for entry in manifest(directory)['vendored']:
        with urllib.request.urlopen(raw_url(entry), timeout=60) as response:
            data = response.read()
        if entry['modifications'] != 'none':
            print(f'skip {entry["file"]}: locally modified ({entry["modifications"]})')
        elif digest(data) != entry['sha256']:
            errors.append(f'{directory / entry["file"]}: differs from {raw_url(entry)}')
        else:
            print(f'ok {entry["file"]} @ {entry["revision"][:12]}')
    return errors


def update(directory, name, revision):
    data = manifest(directory)
    entry = next((item for item in data['vendored'] if item['file'] == name), None)
    if entry is None:
        return [f'{directory}/vendor.json: no entry for {name}']
    with urllib.request.urlopen(raw_url(entry, revision), timeout=60) as response:
        content = response.read()
    (directory / name).write_bytes(content)
    entry.update(revision=revision, sha256=digest(content), modifications='none')
    entry.pop('version', None)
    (directory / 'vendor.json').write_text(json.dumps(data, indent=4) + '\n')
    print(f'updated {name} to {revision}; review the diff, the license and the version field')
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'upstream'):
        commands.add_parser(name).add_argument('directories', nargs='*', type=Path)
    replace = commands.add_parser('update')
    replace.add_argument('directory', type=Path)
    replace.add_argument('file')
    replace.add_argument('revision')
    options = parser.parse_args()
    if options.command == 'update':
        errors = update(options.directory.resolve(), options.file, options.revision)
    else:
        action = check if options.command == 'check' else upstream
        errors = [error for directory in (options.directories or DIRECTORIES)
                  for error in action(directory.resolve())]
    for error in errors:
        print(error, file=sys.stderr)
    if options.command != 'update':
        print(f'{"FAIL" if errors else "PASS"} vendored files match vendor.json ({options.command})')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
