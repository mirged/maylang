#!/usr/bin/env python3
"""Check Markdown links, JSON/Python syntax and the native.may mirror without optional packages."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]\n]+\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def problems(paths):
    errors = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.suffix == '.py':
            try:
                ast.parse(path.read_text(), filename=str(relative))
            except SyntaxError as error:
                errors.append(f'{relative}:{error.lineno}: {error.msg}')
        if path.suffix == '.json':
            try:
                json.loads(path.read_text())
            except json.JSONDecodeError as error:
                errors.append(f'{relative}:{error.lineno}: {error.msg}')
        if path.suffix != '.md':
            continue
        # Code examples can contain Markdown syntax that isn't a document link.
        source = re.sub(r'^```.*?^```[^\n]*', '', path.read_text(), flags=re.M | re.S)
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


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                    cwd=ROOT).decode().split('\0')
    paths = [ROOT / name for name in names if name]
    errors = problems(paths) + mirrors()
    for error in errors:
        print(error, file=sys.stderr)
    print(f'{"FAIL" if errors else "PASS"} repository links, JSON and Python syntax, native mirror ({len(paths)} files)')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
