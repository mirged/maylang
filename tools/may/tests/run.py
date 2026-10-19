#!/usr/bin/env python3
"""Real workspace builds: cache, locks, native recipes, failures and argument paths."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
ENV = os.environ.copy()
ENV.update(MAYC=str(ROOT / 'compiler/mayc/mayc_new'), MAYLANG_STDLIB=str(ROOT / 'stdlib'))


def invoke(binary, root, *args, ok=True, env=None):
    result = subprocess.run([str(binary), *args], cwd=root, env=env or ENV, capture_output=True, timeout=120)
    assert (result.returncode == 0) == ok, (args, result.returncode, result.stdout, result.stderr)
    return result


def manifest(root, value):
    (root / 'may.json').write_text(json.dumps(value))


with tempfile.TemporaryDirectory(prefix='may-workspace-tests-') as directory:
    work = Path(directory)
    binary = work / 'may'
    subprocess.run([ENV['MAYC'], str(ROOT / 'tools/may/main.may'), '-o', str(binary)],
                   cwd=ROOT, env=ENV, check=True, timeout=120)
    project = work / "λ project; ' quoted \\ path"
    invoke(binary, work, 'new', str(project))
    original = (project / 'may.json').read_bytes()
    assert b'Hello from' in invoke(binary, project, 'run').stdout
    cached = invoke(binary, project / 'src', 'run')
    assert b'cached app' in cached.stderr and (project / 'may.json').read_bytes() == original
    # Keep size and timestamps unchanged: cache freshness must still use bytes.
    source = project / 'src/main.may'
    previous = source.stat()
    source.write_bytes(source.read_bytes().replace(b'Hello', b'Howdy'))
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    changed = invoke(binary, project, 'run')
    assert b'build app' in changed.stderr and b'Howdy from' in changed.stdout, changed
    assert b'cached app' in invoke(binary, project, 'run').stderr
    invoke(binary, project, 'test')
    invoke(binary, project, 'check', '--all')
    invoke(binary, project, 'doctor')
    (project / 'src/main.may').write_text('let argv: List<Str> = args(); print(argv[1]);\n')
    argument = 'literal ; $(touch SHOULD_NOT_EXIST) `text` " λ'
    assert invoke(binary, project, 'run', '--', argument).stdout.decode().strip() == argument
    assert not (project / 'SHOULD_NOT_EXIST').exists()
    invoke(binary, project, 'build', '--profile', 'release')
    artifacts = [p for p in (project / '.may/store').iterdir() if '.corrupt-' not in p.name]
    before = len(artifacts)
    (project / 'src/main.may').write_text('let value: Int = "wrong";\n')
    assert b'build failed' in invoke(binary, project, 'run', ok=False).stderr
    assert len(list((project / '.may/store').iterdir())) == before
    (project / 'src/main.may').write_text('print(42);\n')
    invoke(binary, project, 'build')
    artifact = next(p / 'app' for p in (project / '.may/store').iterdir()
                    if (p / 'app').exists() and subprocess.run([str(p / 'app')], capture_output=True).stdout == b'42\n')
    artifact.write_bytes(artifact.read_bytes() + b'damage')
    assert b'build app' in invoke(binary, project, 'build').stderr
    assert b'cached app' in invoke(binary, project, 'build').stderr
    artifact.chmod(0o644)
    assert b'build app' in invoke(binary, project, 'build').stderr
    assert b'cached app' in invoke(binary, project, 'build').stderr
    (project / 'src/main.may').write_text('print( 42 );\n')
    invoke(binary, project, 'fmt', '--check', ok=False)
    invoke(binary, project, 'fmt')
    invoke(binary, project, 'fmt', '--check')
    (project / 'tests/fail.test.may').write_text('fail("expected test failure");\n')
    assert b'1 failed' in invoke(binary, project, 'test', ok=False).stdout
    (project / 'tests/fail.test.may').unlink()
    print('PASS workspace creation, literal argv, profiles, real tests/checks, cache hits and damaged/failed artifact recovery', flush=True)

    toolchain_project = work / 'toolchain freshness'
    invoke(binary, work, 'new', str(toolchain_project))
    compiler_directory = work / 'selected compiler'
    compiler_directory.mkdir()
    selected_compiler = compiler_directory / 'mayc'
    selected_compiler.write_text(f'#!{sys.executable}\n'
                                 'import subprocess, sys\n'
                                 '# revision A\n'
                                 f'sys.exit(subprocess.call([{ENV["MAYC"]!r}, *sys.argv[1:]]))\n')
    selected_compiler.chmod(0o755)
    sidecars = [compiler_directory / 'native.may', compiler_directory / 'runtime.may',
                compiler_directory / 'runtime/core.may']
    sidecars[-1].parent.mkdir()
    for path in sidecars:
        path.write_text('// revision A\n')
    config = json.loads((toolchain_project / 'may.json').read_text())
    config['compiler'] = str(selected_compiler)
    manifest(toolchain_project, config)
    module = toolchain_project / 'src/value.may'
    module.write_text('pub fun answer() -> Int { return 7; }\n')
    (toolchain_project / 'src/main.may').write_text('import "value.may" as value; print(value.answer());\n')
    assert invoke(binary, toolchain_project, 'run').stdout == b'7\n'
    assert b'cached app' in invoke(binary, toolchain_project, 'build').stderr
    for path in [selected_compiler, *sidecars, module]:
        previous = path.stat()
        path.write_bytes(path.read_bytes().replace(b'revision A', b'revision B').replace(b'return 7', b'return 8'))
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert b'build app' in invoke(binary, toolchain_project, 'build').stderr, path
        assert b'cached app' in invoke(binary, toolchain_project, 'build').stderr, path
    assert invoke(binary, toolchain_project, 'run').stdout == b'8\n'
    print('PASS compiler, runtime sidecars and imported-source byte changes invalidate unchanged metadata', flush=True)

    dependency = work / 'dependency'
    dependency.mkdir()
    (dependency / 'value.may').write_text('pub fun answer() -> Int { return 7; }\n')
    config = json.loads((project / 'may.json').read_text())
    config['dependencies'] = {'values': {'path': str(dependency), 'modules': '.'}}
    manifest(project, config)
    (project / 'src/main.may').write_text('import "value" as value;\nprint(value.answer());\n')
    assert b'missing may.lock' in invoke(binary, project, 'build', ok=False).stderr
    invoke(binary, project, 'lock')
    assert invoke(binary, project, 'run').stdout == b'7\n'
    (dependency / 'value.may').write_text('pub fun answer() -> Int { return 8; }\n')
    assert b'dependencies changed' in invoke(binary, project, 'build', ok=False).stderr
    invoke(binary, project, 'lock')
    assert invoke(binary, project, 'run').stdout == b'8\n'
    config['dependencies']['values']['path'] = '../dependency'
    manifest(project, config)
    invoke(binary, project, 'lock')
    relocated = work / 'relocated'
    relocated.mkdir()
    shutil.copytree(project, relocated / project.name, ignore=shutil.ignore_patterns('.may'))
    shutil.copytree(dependency, relocated / 'dependency')
    assert invoke(binary, relocated / project.name, 'run').stdout == b'8\n'
    print('PASS explicit local module roots, dependency pins and reviewed lock refresh', flush=True)

    native = work / 'native'
    invoke(binary, work, 'new', str(native))
    (native / 'input.txt').write_text('first')
    (native / 'recipe.py').write_text('import pathlib,sys,time\npathlib.Path("started").write_text("yes")\ntime.sleep(0.3)\npathlib.Path(sys.argv[1]).write_text(pathlib.Path("input.txt").read_text())\n')
    config = {'schema': 1, 'name': 'native', 'default': 'generated', 'targets': {
        'generated': {'kind': 'native', 'inputs': ['recipe.py', 'input.txt'],
                      'outputs': ['result.txt'], 'command': ['python3', 'recipe.py', '{out}/result.txt']}}}
    manifest(native, config)
    invoke(binary, native, 'build')
    assert b'cached generated' in invoke(binary, native, 'build').stderr
    (native / 'input.txt').write_text('second')
    assert b'build generated' in invoke(binary, native, 'build').stderr
    invoke(binary, native, 'clean')
    processes = [subprocess.Popen([str(binary), 'build'], cwd=native, env=ENV,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    logs = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, (out, err)
        logs.append(err)
    assert sum(b'build generated' in log for log in logs) == 1 and sum(b'cached generated' in log for log in logs) == 1, logs
    config['targets']['generated']['depends'] = ['generated']
    manifest(native, config)
    (native / 'started').unlink()
    assert b'target cycle' in invoke(binary, native, 'build', ok=False).stderr
    assert not (native / 'started').exists()
    config['targets']['generated']['depends'] = []
    config['targets']['generated']['outputs'] = ['artifact.json']
    manifest(native, config)
    assert b'unreserved' in invoke(binary, native, 'build', ok=False).stderr
    print('PASS native recipes, declared-input invalidation, concurrent publication and pre-execution DAG validation', flush=True)

    search = work / 'path search'
    invoke(binary, work, 'new', str(search))
    bins = {name: search / name for name in ('plain', 'directory', 'runnable', 'linked')}
    for folder in bins.values():
        folder.mkdir()
    (bins['plain'] / 'audit-command').write_text('#!/bin/sh\necho wrong\n')
    (bins['directory'] / 'audit-command').mkdir()
    real = bins['runnable'] / 'audit-command-real'
    real.write_text('#!/bin/sh\necho "$1" > "$2"\n')
    real.chmod(0o755)
    (bins['linked'] / 'audit-command').symlink_to(real)
    def recipe(command):
        manifest(search, {'schema': 1, 'name': 'search', 'default': 'generated', 'targets': {
            'generated': {'kind': 'native', 'inputs': [], 'outputs': ['result.txt'],
                          'command': [command, 'found', '{out}/result.txt']}}})
    def path_env(*folders):
        return {**ENV, 'PATH': ':'.join([*map(str, folders), os.environ.get('PATH', '')])}
    recipe('audit-command')
    # A non-executable file, a directory and an empty component precede the symlinked command.
    invoke(binary, search, 'build', env=path_env(bins['plain'], bins['directory'], '', bins['linked']))
    outputs = list((search / '.may/store').rglob('result.txt'))
    assert [p.read_text() for p in outputs] == ['found\n'], outputs
    denied = invoke(binary, search, 'build', ok=False, env=path_env(bins['plain'], bins['directory']))
    assert b'permission denied (not executable)' in denied.stderr and b'plain/audit-command' in denied.stderr, denied
    missing = invoke(binary, search, 'build', ok=False, env=path_env(bins['directory']))
    assert b'executable not found on PATH: audit-command' in missing.stderr, missing
    for command, message in ((f'{bins["plain"]}/audit-command', b'permission denied (not executable)'),
                             (f'{bins["directory"]}/audit-command', b'not a regular file'),
                             ('./absent/audit-command', b'executable not found: ')):
        recipe(command)
        result = invoke(binary, search, 'build', ok=False)
        assert message in result.stderr, (command, result)
    recipe(str(bins['linked'] / 'audit-command'))
    invoke(binary, search, 'clean')
    invoke(binary, search, 'build')
    print('PASS PATH search skips non-executable files and directories; explicit-path and exhaustion diagnostics', flush=True)

    probe_source = work / 'stop_probe.may'
    probe_source.write_text(f'import "{ROOT}/tools/may/src/process.may" as proc;\n'
                            'let argv: List<Str> = args();\n'
                            'let child: Int = proc.spawn(["sh", "-c", argv[1]], ".", []);\n'
                            'sleep(300); proc.stop(child); proc.stop(child);\n'
                            'print(syscall(62, 0 - child, 0) != 0);\n')
    probe = work / 'stop_probe'
    subprocess.run([ENV['MAYC'], str(probe_source), '-o', str(probe)], cwd=work, env=ENV, check=True, timeout=120)
    stubborn = "trap '' TERM; (trap '' TERM; exec sleep 1000) & while :; do sleep 1; done"
    for script, slowest in ((stubborn, 6.0), ('exit 0', 1.5), ('sleep 1000', 1.5),
                            ('sleep 1000 & sleep 1000 & wait', 1.5)):
        started = time.monotonic()
        result = subprocess.run([str(probe), script], cwd=work, env=ENV, capture_output=True, timeout=20)
        elapsed = time.monotonic() - started
        assert result.returncode == 0 and result.stdout == b'true\n', (script, result)
        assert elapsed < slowest, (script, elapsed)
        if script == stubborn:
            assert elapsed >= 2.0, ('SIGKILL before the grace period', elapsed)
    print('PASS bounded stop escalates to SIGKILL, empties the process group and tolerates repeated calls', flush=True)

    watched = work / 'watched'
    invoke(binary, work, 'new', str(watched))
    source = watched / 'src/main.may'
    def application(label):
        return f'write_file("running.pid", str(syscall(39))); print("{label}"); while (true) {{ sleep(50); }}\n'
    source.write_text(application('first'))
    watch_log = watched / 'watch.log'
    log_handle = watch_log.open('wb')
    watcher = subprocess.Popen([str(binary), 'dev'], cwd=watched, env=ENV,
                               stdout=subprocess.PIPE, stderr=log_handle)
    pid_file = watched / 'running.pid'
    def await_pid(previous=None):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if pid_file.exists():
                pid = int(pid_file.read_text())
                if pid != previous:
                    return pid
            assert watcher.poll() is None, watcher.communicate()
            time.sleep(0.05)
        raise AssertionError('development application did not start/reload')
    try:
        first = await_pid()
        source.write_text('let wrong: Int = "bad";\n')
        deadline = time.monotonic() + 20
        while b'build failed' not in watch_log.read_bytes() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert b'build failed' in watch_log.read_bytes(), watch_log.read_bytes()
        assert Path(f'/proc/{first}').exists(), 'failed edit stopped the working application'
        source.write_text(application('second'))
        second = await_pid(first)
        assert not Path(f'/proc/{first}').exists(), 'replaced application was not reaped'
    finally:
        watcher.terminate()
        out, _ = watcher.communicate(timeout=10)
        log_handle.close()
        err = watch_log.read_bytes()
    deadline = time.monotonic() + 5
    while True:
        try:
            state = Path(f'/proc/{second}/stat').read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == 'Z':
            break
        assert time.monotonic() < deadline, 'watcher exit orphaned a running application'
        time.sleep(0.05)
    assert b'first\n' in out and b'second\n' in out and b'build failed' in err, (out, err)
    print('PASS development reload, failed-edit preservation, replacement reaping and parent-death cleanup', flush=True)
