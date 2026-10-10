#!/usr/bin/env python3
"""Isolated projects exercise compiler selection, invalidation and quoting."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='maypkg-tests-') as directory:
        work = Path(directory)
        project = work/"project ' $literal `literal`"; project.mkdir()
        shim = work/"compiler ' shim"
        shim.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']:
    print('test compiler v1'); sys.exit(0)
with open(os.environ['COMPILER_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ.get('COMPILER_FAIL') == '1': sys.exit(7)
out=pathlib.Path(sys.argv[sys.argv.index('-o')+1])
out.write_text('#!/usr/bin/env python3\\nimport json,sys\\nprint(json.dumps(sys.argv[1:]))\\n')
out.chmod(0o755)
'''); shim.chmod(0o755)
        log = work/'compiler.log'
        env = os.environ.copy(); env['MAYC'] = str(shim); env['COMPILER_LOG'] = str(log)
        env['PWD'] = '/not/the/project'
        source = project/'main.may'; source.write_text('print("hello");')
        manifest = project/'mayproj.json'
        doc = {'name':'project', 'entry':'main.may', 'output':"build/program ' $literal", 'target':'host'}
        manifest.write_text(json.dumps(doc))

        def run(*command, ok=True, environment=None):
            result = subprocess.run([str(binary), *command], cwd=project, env=environment or env, capture_output=True, text=True, timeout=60)
            assert (result.returncode == 0) == ok, (command, result)
            return result

        def calls():
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

        run('build'); assert len(calls()) == 1
        print('PASS initial build', flush=True)
        assert 'up to date' in run('build').stdout and len(calls()) == 1
        run('lock'); assert 'up to date' in run('build').stdout
        source.write_text('print("changed");'); run('lock'); run('build'); assert len(calls()) == 2
        doc.update(target='arm64-linux', runtime='core', strict=False, flags=['--time'])
        manifest.write_text(json.dumps(doc)); run('build'); assert len(calls()) == 3
        assert calls()[-1][:5] == ['--target', 'arm64-linux', '--runtime', 'core', '--legacy'], calls()
        assert '--time' in calls()[-1]
        print('PASS source and target/runtime invalidation', flush=True)
        shim.write_text(shim.read_text()+'\n# different compiler, same version\n'); run('build'); assert len(calls()) == 4
        run('build', '--script'); assert len(calls()) == 4
        result = subprocess.run(['sh', str(project/'build/maypkg.build.sh')], env=env, capture_output=True, timeout=60)
        assert result.returncode == 0 and len(calls()) == 5, result
        other = work/'other compiler'; other.write_text(shim.read_text()); other.chmod(0o755)
        configured = env.copy(); configured.pop('MAYC'); doc['compiler'] = str(other); manifest.write_text(json.dumps(doc))
        run('build', environment=configured); assert len(calls()) == 6
        print('PASS compiler content and scripts', flush=True)
        run('sync', environment=configured)
        saved = json.loads(manifest.read_text())
        assert all(saved[key] == doc[key] for key in ('compiler','target','runtime','strict','flags')), saved
        result = run('run', '--', '--flag', "value ' $literal")
        assert '["--flag", "value \' $literal"]' in result.stdout, result
        source.write_text('print("failure");')
        old = (project/'build/maypkg.state.json').read_bytes()
        failure = env.copy(); failure['COMPILER_FAIL'] = '1'; run('build', ok=False, environment=failure)
        assert (project/'build/maypkg.state.json').read_bytes() == old
        run('build'); assert 'up to date' in run('build').stdout
        (project/doc['output']).unlink(); run('build')
        manifest.write_text('{invalid json')
        count=len(calls()); run('build',ok=False)
        assert manifest.read_text()=='{invalid json' and len(calls())==count
        doc['flags']=['--check'];manifest.write_text(json.dumps(doc))
        run('build',ok=False);assert len(calls())==count
        manifest.write_text(json.dumps({**doc,'flags':['--time']}))
        assert not (project/'literal').exists()
        print('PASS compiler selection, config/byte/source invalidation, lock independence, scripts, arguments and failure recovery')
        # The generated template must compile with strict defaults.
        real = env.copy(); real['MAYC'] = str(ROOT/'toolchain/mayc/mayc_new')
        created = work/'new-project'
        run('new', str(created), environment=real)
        result = subprocess.run([str(binary), 'build'], cwd=created, env=real, capture_output=True, timeout=120)
        assert result.returncode == 0, result
        print('PASS new-project strict build with the real compiler')


if __name__ == '__main__':
    main()
