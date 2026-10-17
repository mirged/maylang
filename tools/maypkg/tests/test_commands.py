#!/usr/bin/env python3
"""Isolated command, discovery, watcher lifecycle and cleanup acceptance tests."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    options = parser.parse_args()
    binary = options.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='maypkg-commands-') as directory:
        work = Path(directory)
        project = work / "project ' with spaces"; project.mkdir()
        compiler = work / "compiler ' with spaces"
        compiler.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ['--version']: print('fixture compiler 1'); sys.exit(0)
source=pathlib.Path(sys.argv[-3])
with open(os.environ['COMPILE_LOG'],'a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')
if 'FAIL' in source.read_text(): sys.exit(7)
output=pathlib.Path(sys.argv[-1])
output.write_text('#!/usr/bin/env python3\\nimport os,sys\\nwith open(os.environ["RUN_LOG"],"a") as log: log.write("ran\\\\n")\\nprint("application",*sys.argv[1:])\\n')
output.chmod(0o755)
'''); compiler.chmod(0o755)
        env = os.environ.copy()
        for key in ('MAYPKG_ENTRY','MAYPKG_MANIFEST'): env.pop(key, None)
        env.update(MAYC=str(compiler), COMPILE_LOG=str(work/'compile.log'), RUN_LOG=str(work/'run.log'))
        env['PWD'] = '/stale/pwd'

        def run(*arguments, cwd=project, ok=True):
            result = subprocess.run([str(binary), *arguments], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == ok, (arguments, result)
            return result

        def calls(name):
            path = work/name
            return path.read_text().splitlines() if path.exists() else []

        run('init', 'demo', 'src/main.may')
        manifest = project/'mayproj.json'
        doc = json.loads(manifest.read_text()); doc['output'] = 'build/demo'
        manifest.write_text(json.dumps(doc))
        source = project/'src/main.may'
        source.write_text('import "../lib/helper";\nprint(value());\n')
        (project/'lib').mkdir(); helper = project/'lib/helper.may'
        helper.write_text('pub fun value() -> Int { return 1; }\n')
        orphan = project/'scratch.may'; orphan.write_text('print("scratch");\n')
        child = project/'nested/child'; child.mkdir(parents=True)
        run('init', ok=False)
        assert json.loads(manifest.read_text()) == doc
        assert str(project) in run('info', cwd=child).stdout
        tree = run('tree', cwd=child).stdout
        assert 'main.may' in tree and 'helper.may' in tree and 'scratch.may' not in tree, tree
        assert '[orphan] scratch.may' in run('check').stdout
        assert 'scratch.may' in run('status').stdout
        run('sync', cwd=child)
        synced = json.loads(manifest.read_text())
        assert set(synced['modules']) == {'src/main.may','lib/helper.may'}, synced
        run('lock'); run('verify', cwd=child)
        helper.write_text('pub fun value() -> Int { return 2; }\n')
        assert '[changed] lib/helper.may' in run('verify', ok=False).stdout
        run('lock'); run('verify')
        run('build', cwd=child)
        assert 'application --flag value' in run('run', '--', '--flag', 'value', cwd=child).stdout
        source.write_text('import "../missing";\n')
        count = len(calls('compile.log'))
        assert '[import]' in run('check', ok=False).stdout
        run('build', ok=False); assert len(calls('compile.log')) == count
        source.write_text('import "../lib/helper";\n')
        helper.write_text('import "../src/main";\n')
        assert '[cycle]' in run('check', ok=False).stdout
        run('build', ok=False); assert len(calls('compile.log')) == count
        helper.write_text('pub fun value() -> Int { return 3; }\n')
        source.write_text('import "../lib/helper";\nprint(value());\n')
        run('build')
        print('PASS init/sync/tree/lock/verify/build/run, ancestor discovery, imports, orphans, cycles and quoted paths', flush=True)

        def wait_until(condition, process, label):
            deadline = time.monotonic()+12
            while time.monotonic() < deadline:
                if condition(): return
                assert process.poll() is None, (label, process.returncode, (work/'watch.log').read_text())
                time.sleep(0.05)
            raise AssertionError((label, (work/'watch.log').read_text()))

        def watch(command):
            with (work/'watch.log').open('w') as output:
                before = len(calls('run.log'))
                process = subprocess.Popen(command, cwd=child, env=env, stdout=output,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    wait_until(lambda: len(calls('run.log')) > before, process, 'initial run')
                    for label, edit in [
                        ('source', lambda: source.write_text(source.read_text()+'\n// edited\n')),
                        ('dependency', lambda: helper.write_text(helper.read_text()+'\n// edited\n')),
                        ('compiler', lambda: compiler.write_text(compiler.read_text()+'\n# edited\n')),
                    ]:
                        before = len(calls('run.log')); edit()
                        wait_until(lambda: len(calls('run.log')) > before, process, label)
                    before = len(calls('run.log'))
                    current = json.loads(manifest.read_text()); current['flags'] = ['--time']
                    manifest.write_text(json.dumps(current))
                    wait_until(lambda: len(calls('run.log')) > before, process, 'configuration')
                    compiled = len(calls('compile.log')); before = len(calls('run.log'))
                    source.write_text('FAIL\n')
                    wait_until(lambda: len(calls('compile.log')) > compiled, process, 'failed compilation')
                    time.sleep(0.6)
                    assert len(calls('run.log')) == before, 'watcher ran an old binary after compilation failed'
                    source.write_text('import "../lib/helper";\nprint(value());\n')
                    wait_until(lambda: len(calls('run.log')) > before, process, 'recovery')
                finally:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=3)
                        raise AssertionError('watcher did not terminate within three seconds')
                try: os.killpg(process.pid, 0)
                except ProcessLookupError: pass
                else: raise AssertionError('watcher left a child process running')

        watch([str(binary),'dev'])
        run('dev','--script')
        # Reset settings so the generated watcher must see the next config edit.
        current=json.loads(manifest.read_text()); current['flags']=[]; manifest.write_text(json.dumps(current))
        watch(['sh',str(project/'build/maypkg.dev.sh')])
        print('PASS native/generated watchers rebuild changed inputs, recover from failure and stop their process groups', flush=True)

        run('build'); run('build','--script'); run('run','--script')
        keep = project/'build/user-owned.txt'; keep.write_text('keep this')
        snapshot = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob('*') if path.is_file()}
        assert 'would remove' in run('clean','--dry-run',cwd=child).stdout
        assert snapshot == {str(path.relative_to(project)): path.read_bytes() for path in project.rglob('*') if path.is_file()}
        run('clean',cwd=child)
        expected = {'build/maypkg.build.sh','build/maypkg.run.sh','build/maypkg.dev.sh',
                    'build/maypkg.plan.txt','build/maypkg.state.json','build/maypkg.compiler-version',
                    'build/maypkg.input-digest','mayproj.lock','build/demo'}
        remaining = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob('*') if path.is_file()}
        assert remaining == {path: data for path,data in snapshot.items() if path not in expected}, remaining.keys()
        assert keep.read_text() == 'keep this'
        run('clean'); run('build')
        for protected in ['src/main.may','mayproj.json','mayproj.lock','build/maypkg.state.json','../outside.txt']:
            external = work/'outside.txt'; external.write_text('external user file')
            current=json.loads(manifest.read_text()); current['output']=protected; manifest.write_text(json.dumps(current))
            before={str(path):path.read_bytes() for path in [source,manifest,helper,external]}
            run('clean',ok=False)
            assert all(Path(path).read_bytes() == content for path,content in before.items()), protected
        print('PASS clean/dry-run preserve source, configuration, user artifacts and files outside the project', flush=True)

        fresh = work/'new project'; run('new',str(fresh),'fresh')
        existing=(fresh/'main.may').read_bytes()
        run('new',str(fresh),'replacement',ok=False)
        assert (fresh/'main.may').read_bytes() == existing
        print('PASS new refuses to overwrite an existing project', flush=True)


if __name__ == '__main__':
    main()
