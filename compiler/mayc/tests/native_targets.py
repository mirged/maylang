#!/usr/bin/env python3
"""Cross-emit fixtures on Linux, then verify them with the real target loader."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

from backends import compile_source, compiler_binary
from core_runtime import ARENA_EXPECTED, EXPECTED, LIST_FAILURES
from portable_values import CALL_EXPECTED, EXPECTED as COLLECTION_EXPECTED

HERE = Path(__file__).resolve().parent
TARGETS = ('x86_64-linux', 'arm64-macos', 'x86_64-windows')


def emit(compiler, directory):
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = []
    for target in TARGETS:
        work = directory / target
        work.mkdir(exist_ok=True)
        suffix = '.exe' if target.endswith('windows') else ''

        def fixture(name, source, stdout, status, *options):
            binary = work / (name + suffix)
            image = compile_source(compiler, source, binary, '--target', target, *options)
            fixtures.append(dict(target=target, name=binary.name, stdout=stdout,
                                 status=status, sha256=hashlib.sha256(image).hexdigest()))

        fixture('core', HERE / 'backend/core.may', EXPECTED.decode(), 42, '--runtime', 'core')
        fixture('collections', HERE / 'backend/portable_collections.may', COLLECTION_EXPECTED.decode(), 0, '--runtime', 'core')
        fixture('calls', HERE / 'backend/portable_calls.may', CALL_EXPECTED.decode(), 0, '--runtime', 'core')
        fixture('arena', HERE / 'backend/arena.may', ARENA_EXPECTED.decode(), 0, '--runtime', 'core')
        for name, body, message in [
            ('overflow', 'let n: Any = int("1152921504606846975"); print(n + 1);', 'integer overflow\n'),
            ('divide', 'let n: Any = 3; print(n / 0);', 'division by zero\n'),
        ] + [(name, body, message.decode()) for name, body, message in LIST_FAILURES]:
            source = work / (name + '.may')
            source.write_text(body)
            fixture(name, source, message, 70, '--runtime', 'core')
        # Raw entry return exercises the PE loader and callee-save convention.
        if target.endswith('windows'):
            source = work / 'return.may'
            source.write_text('fun add(a: Any, b: Any) -> Any { return a + b; }\n'
                              'mut n: Any = 0; while n < 100 { n = add(n, 1); }\n')
            fixture('return', source, '', 0, '--raw')

    # Use reduced capacity so exhaustion checks do not commit 256 MiB per run.
    small = directory / 'small-compiler'
    small.mkdir(exist_ok=True)
    shutil.copy2(compiler_binary(compiler), small / 'mayc')
    shutil.copytree(HERE.parent / 'runtime', small / 'runtime', dirs_exist_ok=True)
    core = small / 'runtime/core.may'
    core.write_text(core.read_text().replace('CORE_RETAINED + size > 268435456',
                                             'CORE_RETAINED + size > 2097152'))
    for target in TARGETS:
        work = directory / target
        source = work / 'limit.may'
        source.write_text('for i in 0..10 { alloc(700000); }')
        binary = work / ('limit.exe' if target.endswith('windows') else 'limit')
        image = compile_source(small / 'mayc', source, binary, '--runtime', 'core', '--target', target)
        fixtures.append(dict(target=target, name=binary.name, stdout='core heap limit exceeded\n',
                             status=70, sha256=hashlib.sha256(image).hexdigest()))
    (directory / 'manifest.json').write_text(json.dumps(fixtures, indent=2) + '\n')
    print(f'Emitted {len(fixtures)} native-loader fixtures', flush=True)


def execute(directory, target):
    expected_host = {'x86_64-linux': ('Linux', ('x86_64', 'amd64')),
                     'arm64-macos': ('Darwin', ('arm64', 'aarch64')),
                     'x86_64-windows': ('Windows', ('amd64', 'x86_64'))}
    system, machines = expected_host[target]
    assert platform.system() == system and platform.machine().lower() in machines, platform.platform()
    report = {'target': target, 'host': platform.platform(), 'machine': platform.machine(), 'cases': []}
    print(json.dumps(report), flush=True)
    selected = [f for f in json.loads((directory / 'manifest.json').read_text()) if f['target'] == target]
    assert selected, f'No fixtures for {target}'
    for fixture in selected:
        binary = (directory / target / fixture['name']).resolve()
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == fixture['sha256'], binary
        binary.chmod(0o755)
        if system == 'Darwin':
            for command in (['codesign', '--force', '--sign', '-', str(binary)],
                            ['codesign', '--verify', '--verbose=4', str(binary)],
                            ['otool', '-l', str(binary)]):
                subprocess.run(command, check=True, timeout=30)
        try:
            result = subprocess.run([str(binary)], capture_output=True, timeout=30)
            case = {'name': fixture['name'], 'status': result.returncode,
                    'stdout': result.stdout.decode('utf-8', errors='replace'),
                    'stderr': result.stderr.decode('utf-8', errors='replace')}
        except OSError as error:
            case = {'name': fixture['name'], 'loader_error': str(error)}
            report['cases'].append(case)
            (directory / f'{target}-report.json').write_text(json.dumps(report, indent=2) + '\n')
            raise
        report['cases'].append(case)
        (directory / f'{target}-report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(case), flush=True)
        if system == 'Darwin' and result.returncode != fixture['status']:
            subprocess.run(['codesign', '--display', '--verbose=4', str(binary)], timeout=30)
            subprocess.run(['sudo', 'log', 'show', '--last', '2m', '--style', 'compact',
                            '--predicate', 'process == "kernel" AND (eventMessage CONTAINS "exec" OR eventMessage CONTAINS "signature" OR eventMessage CONTAINS "macho")'],
                           timeout=30)
            subprocess.run(['lldb', '--batch', '-o', 'run', '-o', 'process status', str(binary)], timeout=30)
            for path in (Path.home() / 'Library/Logs/DiagnosticReports').glob(f'{binary.name}*.ips'):
                print(path.read_text(errors='replace')[:20000], flush=True)
        assert result.returncode == fixture['status'], case
        assert result.stdout == fixture['stdout'].encode() and not result.stderr, case
    print(f'PASS {target}: real loader, console, heap, calls and exits', flush=True)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--emit', action='store_true')
    mode.add_argument('--run', choices=TARGETS)
    parser.add_argument('--compiler', type=Path, default=HERE.parent / 'mayc_new')
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if args.emit:
        emit(args.compiler.resolve(), args.directory)
    else:
        execute(args.directory, args.run)


if __name__ == '__main__':
    main()
