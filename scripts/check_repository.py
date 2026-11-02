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


IMPORT = re.compile(r'^\s*(?:import|from)\s+"([^"]+)"', re.M)

# Vendored sources that must stay attributed in THIRD_PARTY_NOTICES.md. The
# maintained headers are also covered by scripts/vendor.py; the frozen copies
# and the per-directory licenses have no manifest of their own.
VENDORED = [
    'stdlib/ui/native/vendor/sokol_app.h',
    'stdlib/ui/native/vendor/sokol_gfx.h',
    'stdlib/ui/native/vendor/sokol_glue.h',
    'stdlib/ui/native/vendor/stb_image_write.h',
    'stdlib/ui/native/vendor/stb_truetype.h',
    'frozen/platform/maybrowser/native/vendor/stb_image.h',
    'frozen/platform/maybrowser/native/vendor/stb_image_write.h',
    'frozen/platform/maybrowser/native/vendor/stb_truetype.h',
    'examples/apps/maynes/native/vendor/binjnes/LICENSE',
    'examples/apps/maynes/roms/LICENSE',
]


def licenses():
    # GitHub and package consumers read the root LICENSE; the extension needs
    # its own copy inside the VSIX. Keep the manifests and notices in step so
    # a vendored file cannot arrive without attribution.
    errors = []
    root = ROOT / 'LICENSE'
    if not root.is_file():
        return ['LICENSE: missing the repository license']
    notice = root.read_text(errors='replace')
    if 'MIT License' not in notice or 'THE SOFTWARE IS PROVIDED "AS IS"' not in notice:
        errors.append('LICENSE: must keep the standard MIT text so license detectors recognize it')
    editor = ROOT / 'editors/vscode/LICENSE'
    if not editor.is_file() or editor.read_bytes() != root.read_bytes():
        errors.append('editors/vscode/LICENSE: must match the root LICENSE byte for byte')
    try:
        cargo = (ROOT / 'Cargo.toml').read_text(errors='replace')
    except OSError:
        errors.append('Cargo.toml: unreadable')
    else:
        if 'license = "MIT"' not in cargo:
            errors.append('Cargo.toml: workspace.package must declare license = "MIT"')
    try:
        package = json.loads((ROOT / 'editors/vscode/package.json').read_text(errors='replace'))
    except (OSError, ValueError):
        errors.append('editors/vscode/package.json: unreadable')
    else:
        if package.get('license') != 'MIT':
            errors.append('editors/vscode/package.json: must declare "license": "MIT"')
    manifest = ROOT / 'THIRD_PARTY_NOTICES.md'
    if not manifest.is_file():
        errors.append('THIRD_PARTY_NOTICES.md: missing third-party notices')
    else:
        listed = manifest.read_text(errors='replace')
        for name in VENDORED:
            if name not in listed:
                errors.append(f'THIRD_PARTY_NOTICES.md: does not attribute {name}')
    return errors


def tool_boundaries(paths):
    # A tool's src/ directory is private to that tool. Code used by several
    # tools lives in tools/shared/ (tools/shared/README.md), so changing one
    # tool cannot silently break another or the installer.
    errors = []
    tools = (ROOT / 'tools').resolve()
    for path in paths:
        if path.suffix != '.may' or not path.is_file():
            continue
        for target in IMPORT.findall(path.read_text(errors='replace')):
            resolved = (path.parent / target).resolve()
            try:
                parts = resolved.relative_to(tools).parts
            except ValueError:
                continue
            if len(parts) > 2 and parts[1] == 'src':
                owner = tools / parts[0]
                if owner not in path.resolve().parents:
                    errors.append(f'{path.relative_to(ROOT)}: imports {target}, which is private to '
                                  f'tools/{parts[0]}; move shared code to tools/shared/')
    return errors


def checked(names):
    # frozen/ holds code that is kept but not maintained (frozen/README.md),
    # so its links and syntax are not checked.
    return [ROOT / name for name in names if name and not name.startswith('frozen/')]


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                    cwd=ROOT).decode().split('\0')
    paths = checked(names)
    vendor = runpy.run_path(str(ROOT / 'scripts/vendor.py'))
    errors = (problems(paths) + mirrors() + tool_boundaries(paths) + licenses() +
              [e for d in vendor['DIRECTORIES'] for e in vendor['check'](d)])
    for error in errors:
        print(error, file=sys.stderr)
    print(f'{"FAIL" if errors else "PASS"} repository links, JSON and Python syntax, native mirror, '
          f'tool boundaries, licenses and third-party notices, vendored checksums ({len(paths)} files)')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
