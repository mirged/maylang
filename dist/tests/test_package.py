#!/usr/bin/env python3
"""Verify an extracted installation in an unrelated directory."""
import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='maylang-installed-') as directory:
        work = Path(directory)
        with tarfile.open(args.archive) as archive: archive.extractall(work, filter='data')
        bundle, = work.iterdir()
        for line in (bundle/'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ',1)
            assert hashlib.sha256((bundle/name).read_bytes()).hexdigest() == digest, name
        provenance=json.loads((bundle/'provenance.json').read_text())
        assert provenance['version'] == (bundle/'VERSION').read_text().strip()
        metadata = json.loads((bundle / 'RELEASE.json').read_text())
        assert metadata == provenance['release'] and metadata['version'] == provenance['version']
        assert metadata['codename'] in (bundle / 'CHANGELOG.md').read_text()
        env=os.environ.copy(); env['PATH']=str(bundle/'bin')+os.pathsep+env.get('PATH','')
        for variable in ('MAYC','MAYLANG_STDLIB','MAYPKG_MANIFEST','MAYPKG_ENTRY'): env.pop(variable,None)
        project=work/'project';project.mkdir()
        (project/'main.may').write_text('import "result" as result;\nlet r: Result<Int, Str> = result.ok(42); print(result.unwrap(r));')
        def run(*command):
            result=subprocess.run(command,cwd=project,env=env,capture_output=True,timeout=180)
            assert result.returncode == 0,(command,result)
            return result.stdout
        assert run('mayc','--version').decode().strip() == 'mayc '+provenance['version']
        targets = run(str(bundle / 'bin/mayc'), '--list-targets').decode()
        assert 'arm64-macos\tmacho\tcore' in targets and 'clang-llvm\tllvm\tfull' in targets
        run('mayc','main.may','-o','hello')
        assert run(str(project/'hello')) == b'42\n'
        run(str(bundle/'bin/maypkg'),'build')
        assert b'up to date' in run(str(bundle/'bin/maypkg'),'build')
        assert run(str(project/'project')) == b'42\n'
        run(str(bundle / 'bin/may'), 'new', 'workspace')
        result = subprocess.run([str(bundle / 'bin/may'), 'run'], cwd=project / 'workspace',
                                env=env, capture_output=True, timeout=120)
        assert result.returncode == 0 and result.stdout == b'Hello from workspace!\n', result
        result = subprocess.run([str(bundle / 'bin/may'), 'test'], cwd=project / 'workspace',
                                env=env, capture_output=True, timeout=120)
        assert result.returncode == 0 and b'PASS smoke.test.may' in result.stdout, result
        run(str(bundle / 'bin/mayfmt'), '--check', str(project / 'workspace/src/main.may'))
        message=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}).encode()
        wire=f'Content-Length: {len(message)}\r\n\r\n'.encode()+message
        result=subprocess.run([str(bundle/'bin/maylsp')],input=wire,cwd=project,env=env,capture_output=True,timeout=20)
        assert result.returncode == 0 and b'"capabilities"' in result.stdout,result
        run(str(bundle/'bin/mayc'), str(ROOT/'examples/apps/textstats/main.may'), '-o', 'textstats')
        result=subprocess.run([str(project/'textstats')],input=b'red fish blue fish\nred fish\n',cwd=project,env=env,capture_output=True,timeout=20)
        assert result.returncode==0,result
        lines=result.stdout.decode().splitlines()
        assert 'words 6  unique 3  avg 3.66' in lines and 'longest fish' in lines,lines
        rows=[line.split() for line in lines if line.startswith(('fish ','red ','blue '))]
        assert rows==[['fish','3','###'],['red','2','##'],['blue','1','#']],rows
        assert (bundle / 'stdlib/ui/native/draw.c').is_file()
        run(str(bundle / 'bin/may'), 'new', 'desktop', '--ui')
        result = subprocess.run([str(bundle / 'bin/may'), 'build'], cwd=project / 'desktop',
                                env=env, capture_output=True, timeout=180)
        assert result.returncode == 0, result
        native_outputs = list((project / 'desktop/.may/store').glob('*/libmayui.so'))
        assert len(native_outputs) == 1
        source = project / 'snapshot.may'
        source.write_text('import "ui" as ui; let w: ui.Window = ui.open("Installed UI", 400, 300, true); ui.present(w, ui.label("Installed native UI")); ui.snapshot(w, "installed.png"); ui.close(w);')
        run(str(bundle / 'bin/mayc'), str(source), '-o', 'snapshot')
        ui_env = dict(env, LD_LIBRARY_PATH=str(native_outputs[0].parent))
        result = subprocess.run([str(project / 'snapshot')], cwd=project, env=ui_env,
                                capture_output=True, timeout=20)
        assert result.returncode == 0 and (project / 'installed.png').read_bytes().startswith(b'\x89PNG'), result
        board = bundle / 'examples/apps/mayboard'
        result = subprocess.run([str(bundle / 'bin/may'), 'run', '--', '--demo', '--snapshot', str(work / 'mayboard.png')],
                                cwd=board, env=env, capture_output=True, timeout=180)
        assert result.returncode == 0 and (work / 'mayboard.png').read_bytes().startswith(b'\x89PNG'), result
        result = subprocess.run([str(bundle / 'bin/may'), 'test'], cwd=board, env=env,
                                capture_output=True, timeout=120)
        assert result.returncode == 0 and b'PASS model.test.may' in result.stdout, result
        nes = bundle / 'examples/apps/maynes'
        nes_env = dict(env, XDG_DATA_HOME=str(work / 'data'))
        report_path = work / 'nes.json'
        result = subprocess.run([str(bundle / 'bin/may'), 'run', '--', '--headless', '--frames', '90',
                                 '--snapshot', str(work / 'nes.png'), '--report', str(report_path)],
                                cwd=nes, env=nes_env, capture_output=True, timeout=180)
        assert result.returncode == 0 and (work / 'nes.png').read_bytes().startswith(b'\x89PNG'), result
        report = json.loads(report_path.read_text())
        assert report['frames'] == 90 and report['rom'] == 'Starfall' and report['audio_samples'] > 60000, report
        result = subprocess.run([str(bundle / 'bin/may'), 'test'], cwd=nes, env=nes_env,
                                capture_output=True, timeout=120)
        assert result.returncode == 0 and b'PASS emulator.test.may' in result.stdout, result
        print('PASS bundled May NES executes a real cartridge, synthesizes audio and renders its framebuffer')
        print('PASS bundled Mayboard renders a demo PNG and its model tests pass')
        print('PASS extracted checksums, version, standalone compilation, stdlib, workspace/formatter, legacy maypkg and LSP initialization')
        print('PASS installed UI scaffold builds and a headless application renders PNG')
        print('PASS installed compiler builds and runs the typed textstats application')


if __name__ == '__main__':
    main()
