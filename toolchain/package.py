#!/usr/bin/env python3
"""Build a complete Linux x86-64 toolchain archive with provenance/checksums."""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], cwd=ROOT).decode().strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, help='use an already verified source-built compiler')
    args = parser.parse_args()
    if args.compiler is None:
        subprocess.run(['sh', 'toolchain/rust/build.sh'], cwd=ROOT, check=True)
        compiler = ROOT/'toolchain/mayc/build/bin/mayc_new'
    else:
        compiler = args.compiler.resolve()
        if compiler.name == 'mayc_new' and compiler.parent == ROOT/'toolchain/mayc':
            compiler = ROOT/'toolchain/mayc/build/bin/mayc_new'
    version = run(compiler, '--version').removeprefix('mayc ')
    commit = run('git', 'rev-parse', 'HEAD')
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
        for tool in ('maypkg', 'maylsp'):
            subprocess.run([str(compiler), str(ROOT/f'toolchain/{tool}/main.may'), '-o', str(bin_dir/tool)], cwd=ROOT, check=True, timeout=180)
        (bundle/'VERSION').write_text(version+'\n')
        (bundle/'README.txt').write_text('Add this bundle\'s bin directory to PATH. Keep the entire bundle together.\nCompiler host: Linux x86-64. Full runtime: Linux x86-64 only.\nUse mayc --help, maypkg help, and maylsp with an LSP-capable editor.\nUpgrade by extracting a new bundle and changing PATH.\n')
        (bundle/'provenance.json').write_text(json.dumps({
            'version':version, 'commit':commit, 'dirty':bool(run('git','status','--porcelain')),
            'host':'x86_64-linux', 'bootstrap':'Rust -> C -> self-hosted native',
            'source_date_epoch':epoch,
            'compiler_sha256':hashlib.sha256(compiler.read_bytes()).hexdigest(),
        }, indent=2)+'\n')
        files = sorted(path for path in bundle.rglob('*') if path.is_file())
        (bundle/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle)}\n' for path in files))
        temporary = output.with_suffix(output.suffix+'.tmp')
        with temporary.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as archive:
            for path in [bundle, *sorted(bundle.rglob('*'))]:
                info = archive.gettarinfo(str(path), arcname=str(path.relative_to(bundle.parent)))
                info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=epoch
                info.mode = 0o755 if path.is_dir() or path.parent == bin_dir and path.name in ('mayc','maypkg','maylsp') else 0o644
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
