#!/usr/bin/env python3
"""Embed a verified bundle and its Maylang installer in standalone C/shell files."""
import argparse
import base64
import hashlib
from pathlib import Path
import struct
import os
import subprocess

HERE = Path(__file__).resolve().parent


def generate(bundle, output, native=False):
    entries = sorted(bundle.rglob('*'))
    if any(path.is_symlink() for path in entries):
        raise ValueError('bundle must contain copied regular files/directories, not symlinks')
    files = [path for path in entries if path.is_file()]
    if not (bundle / 'bin/may-installer').is_file():
        raise ValueError('bundle must contain the source-built bin/may-installer')
    payload = bytearray(b'MAYINST1' + struct.pack('<I', len(files)))
    for path in files:
        name = ('bundle/' + str(path.relative_to(bundle))).encode()
        content = path.read_bytes()
        mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
        payload.extend(struct.pack('<III', len(name), mode, len(content)))
        payload.extend(name)
        payload.extend(content)
    encoded = base64.b64encode(payload).decode('ascii')
    literals = '\n'.join('"' + encoded[i:i + 100] + '"' for i in range(0, len(encoded), 100))
    source = (HERE / 'bootstrap.c').read_text().replace('/* MAYLANG_PAYLOAD */', literals)
    output.mkdir(parents=True, exist_ok=True)
    c_file = output / 'maylang-bootstrap.c'
    c_file.write_text(source)
    script = output / 'maylang-install.sh'
    script.write_text('''#!/bin/sh
# Self-contained Linux x86-64 installer. Requires only a POSIX shell and host cc.
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/maylang-bootstrap-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/bootstrap.c" <<'MAYLANG_BOOTSTRAP_C'
''' + source + '''
MAYLANG_BOOTSTRAP_C
"${CC:-cc}" -std=c11 -O2 "$work/bootstrap.c" -o "$work/install"
"$work/install" "$@"
''')
    script.chmod(0o755)
    downloader = output / 'maylang-init.sh'
    downloader.write_bytes((HERE.parents[1] / 'install.sh').read_bytes())
    downloader.chmod(0o755)
    artifacts = [c_file, script, downloader]
    if native:
        binary = output / 'maylang-init-x86_64-linux'
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Os', '-static', '-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=2',
                        '-Wall', '-Wextra', '-Werror', str(c_file), '-o', str(binary)], check=True)
        artifacts.append(binary)
    for path in artifacts:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_name(path.name + '.sha256').write_text(f'{digest}  {path.name}\n')
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', action='store_true', help='also build the prebuilt standalone native installer')
    args = parser.parse_args()
    for path in generate(args.bundle.resolve(), args.output.resolve(), args.native):
        print(path)


if __name__ == '__main__':
    main()
