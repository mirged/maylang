#!/usr/bin/env python3
"""Check Markdown links, JSON/Python syntax and the native.may mirror without optional packages."""
import ast
import runpy
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]\n]+\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def markdown_prose(content):
    lines = []
    fence = None
    for line in content.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence is not None:
            if (marker and marker[1][0] == fence[0] and
                    len(marker[1]) >= len(fence) and not marker[2].strip()):
                fence = None
        elif marker and (marker[1][0] == '~' or '`' not in marker[2]):
            fence = marker[1]
        else:
            lines.append(line)
            continue
        lines.append('\n' if line.endswith('\n') else '')
    return ''.join(lines)


def problems(paths):
    errors = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.suffix not in ('.py', '.json', '.md'):
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError as error:
            errors.append(f'{relative}: invalid UTF-8: {error}')
            continue
        if path.suffix == '.py':
            try:
                ast.parse(content, filename=str(relative))
            except SyntaxError as error:
                errors.append(f'{relative}:{error.lineno}: {error.msg}')
        if path.suffix == '.json':
            try:
                json.loads(content)
            except json.JSONDecodeError as error:
                errors.append(f'{relative}:{error.lineno}: {error.msg}')
        if path.suffix != '.md':
            continue
        # Code examples can contain Markdown syntax that isn't a document link.
        source = markdown_prose(content)
        inline_code = list(re.finditer(r'`[^`\n]+`', source))
        for match in LINK.finditer(source):
            if any(code.start() < match.start() < code.end() for code in inline_code):
                continue
            target = match[1].strip('<>')
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (ROOT if url.path.startswith('/') else path.parent) / unquote(url.path.lstrip('/'))
            if not destination.exists():
                errors.append(f'{relative}: missing local link {target}')
    return errors


def mirrors():
    # The language server and API docs read stdlib/native.may; the compiler
    # injects compiler/mayc/native.may. Divergence makes editors disagree with
    # the compiler, so the mirror must stay byte-identical.
    active, mirror = ROOT / 'compiler/mayc/native.may', ROOT / 'stdlib/native.may'
    if active.read_bytes() != mirror.read_bytes():
        return [f'{mirror.relative_to(ROOT)}: differs from {active.relative_to(ROOT)}; '
                f'copy the active sidecar over it (cp {active.relative_to(ROOT)} {mirror.relative_to(ROOT)})']
    return []


def checked(names):
    # frozen/ holds code that is kept but not maintained (frozen/README.md),
    # so its links and syntax are not checked.
    return [ROOT / name for name in names if name and not name.startswith('frozen/')]


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                    cwd=ROOT).decode().split('\0')
    paths = checked(names)
    vendor = runpy.run_path(str(ROOT / 'scripts/vendor.py'))
    errors = problems(paths) + mirrors() + [e for d in vendor['DIRECTORIES'] for e in vendor['check'](d)]
    for error in errors:
        print(error, file=sys.stderr)
    print(f'{"FAIL" if errors else "PASS"} repository links, JSON and Python syntax, native mirror, vendored checksums ({len(paths)} files)')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
