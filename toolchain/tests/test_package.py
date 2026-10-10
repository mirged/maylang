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
        env=os.environ.copy(); env['PATH']=str(bundle/'bin')+os.pathsep+env.get('PATH','')
        for variable in ('MAYC','MAYLANG_STDLIB','MAYPKG_MANIFEST','MAYPKG_ENTRY'): env.pop(variable,None)
        project=work/'project';project.mkdir()
        (project/'main.may').write_text('import "result" as result;\nlet r: Result<Int, Str> = result.ok(42); print(result.unwrap(r));')
        def run(*command):
            result=subprocess.run(command,cwd=project,env=env,capture_output=True,timeout=180)
            assert result.returncode == 0,(command,result)
            return result.stdout
        assert run(str(bundle/'bin/mayc'),'--version').decode().strip() == 'mayc '+provenance['version']
        run(str(bundle/'bin/mayc'),'main.may','-o','hello')
        assert run(str(project/'hello')) == b'42\n'
        run(str(bundle/'bin/maypkg'),'build')
        assert b'up to date' in run(str(bundle/'bin/maypkg'),'build')
        assert run(str(project/'project')) == b'42\n'
        message=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}).encode()
        wire=f'Content-Length: {len(message)}\r\n\r\n'.encode()+message
        result=subprocess.run([str(bundle/'bin/maylsp')],input=wire,cwd=project,env=env,capture_output=True,timeout=20)
        assert result.returncode == 0 and b'"capabilities"' in result.stdout,result
        run(str(bundle/'bin/mayc'), str(ROOT/'example_projects/apps/textstats/main.may'), '-o', 'textstats')
        result=subprocess.run([str(project/'textstats')],input=b'red fish blue fish\nred fish\n',cwd=project,env=env,capture_output=True,timeout=20)
        assert result.returncode==0,result
        lines=result.stdout.decode().splitlines()
        assert 'words 6  unique 3  avg 3.66' in lines and 'longest fish' in lines,lines
        rows=[line.split() for line in lines if line.startswith(('fish ','red ','blue '))]
        assert rows==[['fish','3','###'],['red','2','##'],['blue','1','#']],rows
        print('PASS extracted checksums, version, standalone compilation, stdlib, maypkg and LSP initialization')
        print('PASS installed compiler builds and runs the typed textstats application')


if __name__ == '__main__':
    main()
