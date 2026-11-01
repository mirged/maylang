#!/usr/bin/env python3
"""Extract one release's notes from CHANGELOG.md for its GitHub release.

  release_notes.py v0.15.0 [--changelog CHANGELOG.md] [--output FILE]

Prints the body of the `# Maylang <version> — <codename>` section, up to the
next top-level heading, without the heading itself (GitHub shows the version
and codename in the release title). Fails if the section is missing, empty or
appears more than once, so a release never publishes the whole changelog or
the wrong version's notes.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def notes(changelog, tag):
    version = tag.removeprefix('v')
    heading = re.compile(rf'^# Maylang {re.escape(version)}(?: — .+)?$')
    sections, current = [], None
    for line in changelog.splitlines():
        if line.startswith('# '):
            current = [] if heading.match(line) else None
            if current is not None:
                sections.append(current)
        elif current is not None:
            current.append(line)
    if not sections:
        raise ValueError(f'CHANGELOG.md has no "# Maylang {version} — <codename>" section')
    if len(sections) > 1:
        raise ValueError(f'CHANGELOG.md has {len(sections)} sections for {version}')
    body = '\n'.join(sections[0]).strip()
    if not body:
        raise ValueError(f'the CHANGELOG.md section for {version} is empty')
    return body + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tag', help='release tag or version, for example v0.15.0')
    parser.add_argument('--changelog', type=Path, default=ROOT / 'CHANGELOG.md')
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    try:
        text = notes(options.changelog.read_text(), options.tag)
    except ValueError as error:
        print(f'release_notes.py: {error}', file=sys.stderr)
        return 1
    if options.output:
        options.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
