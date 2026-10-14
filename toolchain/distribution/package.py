#!/usr/bin/env python3
"""Build a complete Linux x86-64 toolchain archive with provenance/checksums."""
import argparse
from datetime import date
import gzip
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

generate_installer = runpy.run_path(str(Path(__file__).with_name('build_installer.py')))['generate']

ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], cwd=ROOT).decode().strip()


def release_provenance(tag, version, commit):
    if tag is None:
        return None
    if tag != 'v' + version:
        raise ValueError(f'release tag {tag!r} must match compiler version v{version}')
    if run('git', 'rev-parse', f'refs/tags/{tag}^{{commit}}') != commit:
        raise ValueError('release tag must point to the checked-out source commit')
    if run('git', 'status', '--porcelain'):
        raise ValueError('release packaging requires a clean source checkout')
    return tag


def release_metadata(version):
    metadata = json.loads((ROOT / 'RELEASE.json').read_text())
    if metadata.get('version') != version:
        raise ValueError('RELEASE.json version must match the compiler version')
    if not re.fullmatch(r'[A-Z][a-z]+', metadata.get('codename', '')):
        raise ValueError('release codename must be a capitalized word')
    stamp = metadata.get('date', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp):
        raise ValueError('release date must use YYYY-MM-DD')
    date.fromisoformat(stamp)
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, help='use an already verified source-built compiler')
    parser.add_argument('--release-tag', help='require a clean checkout at v<compiler-version>')
    parser.add_argument('--installer-output', type=Path, help='also emit self-contained C and shell installers here')
    args = parser.parse_args()
    if args.compiler is None:
        subprocess.run(['sh', 'toolchain/rust/build.sh'], cwd=ROOT, check=True)
        compiler = ROOT/'toolchain/mayc/build/bin/mayc_new'
    else:
        compiler = args.compiler.resolve()
        if compiler.name == 'mayc_new' and compiler.parent == ROOT/'toolchain/mayc':
            compiler = ROOT/'toolchain/mayc/build/bin/mayc_new'
    version = run(compiler, '--version').removeprefix('mayc ')
    metadata = release_metadata(version)
    commit = run('git', 'rev-parse', 'HEAD')
    tag = release_provenance(args.release_tag, version, commit)
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', run('git', 'show', '-s', '--format=%ct', 'HEAD')))
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='maylang-package-') as directory:
        bundle = Path(directory)/f'maylang-{version}-x86_64-linux'
        bin_dir = bundle/'bin'; bin_dir.mkdir(parents=True)
        shutil.copy2(compiler, bin_dir/'mayc')
        for name, source in [('runtime.may', ROOT/'toolchain/mayc/runtime.may'),
                             ('native.may', ROOT/'toolchain/mayc/native.may'),
                             ('prelude.may', ROOT/'stdlib/prelude.may')]:
            shutil.copy2(source, bin_dir/name)
        shutil.copytree(ROOT/'toolchain/mayc/runtime', bin_dir/'runtime', ignore=shutil.ignore_patterns('build', '__pycache__'))
        shutil.copytree(ROOT/'stdlib', bundle/'stdlib', ignore=shutil.ignore_patterns('build', '__pycache__'))
        shutil.copytree(ROOT / 'example_projects/apps/mayboard', bundle / 'example_projects/apps/mayboard',
                        ignore=shutil.ignore_patterns('.may', 'build', '__pycache__'))
        for tool in ('maypkg', 'maylsp', 'may', 'mayfmt', 'may-installer'):
            source = ROOT / 'toolchain/distribution/installer.may' if tool == 'may-installer' else ROOT / f'toolchain/{tool}/main.may'
            subprocess.run([str(compiler), str(source), '-o', str(bin_dir/tool)], cwd=ROOT, check=True, timeout=180)
        (bundle/'VERSION').write_text(version+'\n')
        shutil.copy2(ROOT / 'RELEASE.json', bundle / 'RELEASE.json')
        shutil.copy2(ROOT / 'CHANGELOG.md', bundle / 'CHANGELOG.md')
        (bundle/'README.txt').write_text('Add this bundle\'s bin directory to PATH. Keep the entire bundle together.\nCompiler host: Linux x86-64. Full runtime: Linux x86-64 only.\nUse mayc --help, may help, mayfmt file.may and maylsp with an LSP-capable editor.\nmaypkg remains available for older projects.\nRun the complete desktop app: cd example_projects/apps/mayboard && may run.\nUI needs a C compiler, X11 headers and a TrueType font; windows need X11/XWayland.\nUse may run -- --demo --snapshot /tmp/mayboard.png for a headless preview.\nUpgrade by extracting a new bundle and changing PATH.\n')
        (bundle/'provenance.json').write_text(json.dumps({
            'version':version, 'commit':commit, 'tag':tag,
            'release':metadata,
            'dirty':bool(run('git','status','--porcelain')),
            'host':'x86_64-linux', 'bootstrap':'Rust -> C -> self-hosted native',
            'bootstrap_tools': {'rustc': run('rustc', '--version'),
                                'cc': run(os.environ.get('CC', 'cc'), '--version').splitlines()[0]},
            'source_date_epoch':epoch,
            'compiler_sha256':hashlib.sha256(compiler.read_bytes()).hexdigest(),
        }, indent=2)+'\n')
        files = sorted(path for path in bundle.rglob('*') if path.is_file())
        (bundle/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle)}\n' for path in files))
        if args.installer_output:
            generate_installer(bundle, args.installer_output.resolve())
        temporary = output.with_suffix(output.suffix+'.tmp')
        with temporary.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as archive:
            for path in [bundle, *sorted(bundle.rglob('*'))]:
                info = archive.gettarinfo(str(path), arcname=str(path.relative_to(bundle.parent)))
                info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=epoch
                info.mode = 0o755 if path.is_dir() or path.parent == bin_dir and path.name in ('mayc','maypkg','maylsp','may','mayfmt','may-installer') else 0o644
                if path.is_file():
                    with path.open('rb') as content: archive.addfile(info, content)
                else: archive.addfile(info)
        temporary.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name+'.sha256').write_text(f'{digest}  {output.name}\n')
    print(output)
    print('SHA256 '+digest)


if __name__ == '__main__':
    main()
