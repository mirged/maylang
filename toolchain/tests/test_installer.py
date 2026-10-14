#!/usr/bin/env python3
"""Real copied installs, source deletion, TUI, C bootstrap and safe uninstall."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import termios
import fcntl
import struct

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('installer_builder', ROOT / 'toolchain/distribution/build_installer.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def invoke(command, work, environment, *, ok=True, data=None):
    result = subprocess.run(list(map(str, command)), cwd=work, env=environment,
                            input=data, capture_output=True, timeout=180, start_new_session=True)
    assert (result.returncode == 0) == ok, (command, result.returncode, result.stdout, result.stderr)
    return result


def interactive(installer, source, prefix, work, environment, *, plain=False, cancel=False, checklist=False):
    child, descriptor = pty.fork()
    if child == 0:
        os.chdir(work)
        options = ['--plain'] if plain else []
        os.execve(installer, [str(installer), '--bundle', str(source), '--prefix', str(prefix), '--no-modify-path', *options], environment)
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 88, 0, 0))
    before = termios.tcgetattr(descriptor)
    if cancel:
        actions = [(b'esc cancel', b'\x03')]
    elif plain:
        actions = [(b'Choose', b'1\n')]
    else:
        actions = [(b'esc cancel', b'\x1b[B\r'), (b'esc cancel', b'2'),
                   (b'esc cancel', b'3' if checklist else b'\x1b[B\r')]
        if checklist:
            actions += [(b'space toggle', b' \x1b[B\x1b[B \x1b[B \r')]
        actions += [(b'esc cancel', b'4'), (b'esc cancel', b'\r')]
    transcript = bytearray()
    pending = bytearray()
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            if select.select([descriptor], [], [], .1)[0]:
                try:
                    chunk = os.read(descriptor, 65536)
                except OSError:
                    chunk = b''
                transcript.extend(chunk)
                pending.extend(chunk)
                if actions and actions[0][0] in pending:
                    _, response = actions.pop(0)
                    os.write(descriptor, response)
                    pending.clear()
            waited, status = os.waitpid(child, os.WNOHANG)
            if waited:
                assert os.waitstatus_to_exitcode(status) == 0, transcript.decode(errors='replace')
                assert not actions, (actions, transcript.decode(errors='replace'))
                assert b'Cancelled' in transcript if cancel else b"You're ready to May" in transcript, transcript
                after = termios.tcgetattr(descriptor)
                assert (after[3] & (termios.ECHO | termios.ICANON | termios.ISIG)) == (before[3] & (termios.ECHO | termios.ICANON | termios.ISIG))
                if plain:
                    assert b'\x1b[' not in transcript, transcript
                return transcript
        raise AssertionError('interactive installer timed out: ' + transcript.decode(errors='replace'))
    except BaseException:
        try:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
        except ProcessLookupError:
            pass
        raise
    finally:
        os.close(descriptor)


def installed_tools(prefix, work, environment):
    environment = {**environment, 'PATH': str(prefix / 'bin') + ':' + environment['PATH']}
    source = work / 'hello.may'
    source.write_text('import "result" as result;\nlet r: Result<Int, Str> = result.ok(42);\nprint(result.unwrap(r));\n')
    invoke(['mayc', source, '-o', work / 'hello'], work, environment)
    assert invoke([work / 'hello'], work, environment).stdout == b'42\n'
    invoke(['may', 'new', 'independent'], work, environment)
    assert b'Hello from independent!' in invoke(['may', 'run'], work / 'independent', environment).stdout
    invoke(['mayfmt', '--check', 'src/main.may'], work / 'independent', environment)
    invoke(['maypkg', 'help'], work, environment)
    message = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}).encode()
    wire = f'Content-Length: {len(message)}\r\n\r\n'.encode() + message
    assert b'"capabilities"' in invoke(['maylsp'], work, environment, data=wire).stdout
    shutil.rmtree(work / 'independent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--bundle', type=Path)
    group.add_argument('--archive', type=Path)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='maylang-installer-tests-') as temporary:
        work = Path(temporary)
        if args.archive:
            extracted = work / 'extracted'
            extracted.mkdir()
            with tarfile.open(args.archive) as archive:
                archive.extractall(extracted, filter='data')
            bundle, = extracted.iterdir()
        else:
            bundle = args.bundle.resolve()
        source = work / 'checkout' / 'build' / 'dev'
        shutil.copytree(bundle, source)
        installer = work / 'installer'
        shutil.copy2(source / 'bin/may-installer', installer)
        home = work / 'home'
        home.mkdir()
        profile = home / '.bashrc'
        profile.write_text('# user configuration\nexport USER_SETTING=kept\n')
        environment = {key: value for key, value in os.environ.items() if key not in ('MAYC', 'MAYLANG_STDLIB')}
        environment.update(HOME=str(home), SHELL='/bin/bash', TERM='xterm-256color')
        prefix = work / "prefix with spaces ' $ `quotes`"
        command = [installer, '--bundle', source, '--yes', '--prefix', prefix, '--profile', profile]
        invoke(command, work, environment)
        invoke(command, work, environment)
        assert profile.read_text().count('# >>> Maylang ') == 1
        assert 'USER_SETTING=kept' in profile.read_text()
        first_selection = os.readlink(prefix / 'current')
        for path in prefix.rglob('*'):
            if path.is_symlink():
                assert path.resolve().is_relative_to(prefix), path
        # A damaged candidate must not replace the verified current generation.
        original = (source / 'bin/mayc').read_bytes()
        (source / 'bin/mayc').write_text('#!/bin/sh\nexit 9\n')
        invoke(command, work, environment, ok=False)
        assert os.readlink(prefix / 'current') == first_selection
        (source / 'bin/mayc').write_bytes(original)
        assert not list(prefix.glob('.install-*'))
        original_native = (source / 'bin/native.may').read_bytes()
        outside = work / 'external-native.may'
        outside.write_bytes(original_native)
        (source / 'bin/native.may').unlink()
        (source / 'bin/native.may').symlink_to(outside)
        invoke(command, work, environment, ok=False)
        assert os.readlink(prefix / 'current') == first_selection
        (source / 'bin/native.may').unlink()
        (source / 'bin/native.may').write_bytes(original_native)
        old_profile = profile.read_text()
        profile.write_text(old_profile + '# >>> Maylang ' + str(prefix) + ' >>>\n')
        invoke(command, work, environment, ok=False)
        assert os.readlink(prefix / 'current') == first_selection
        profile.write_text(old_profile)
        # A genuine interactive terminal exercises prompts and component choice.
        tui_prefix = work / 'interactive-prefix'
        interactive(installer, source, tui_prefix, work, environment)
        assert (tui_prefix / 'bin/mayc').exists() and not (tui_prefix / 'bin/may').exists()
        assert profile.read_text().count('# >>> Maylang ') == 1
        cancelled = work / 'cancelled-prefix'
        interactive(installer, source, cancelled, work, environment, cancel=True)
        assert not cancelled.exists()
        plain_prefix = work / 'plain-prefix'
        interactive(installer, source, plain_prefix, work, environment, plain=True)
        custom_prefix = work / 'custom-prefix'
        interactive(installer, source, custom_prefix, work, environment, checklist=True)
        assert (custom_prefix / 'bin/mayfmt').exists()
        assert not (custom_prefix / 'bin/may').exists() and not (custom_prefix / 'bin/maypkg').exists()
        invoke([installer, '--bundle', source], work, environment, ok=False)
        invoke([installer, '--bundle', source, '--yes', '--prefix', home], work, environment, ok=False)
        # Build the single C file before deleting all source/development files.
        artifacts = args.artifacts.resolve() if args.artifacts else work / 'artifacts'
        if not args.artifacts:
            builder.generate(source, artifacts)
        c_runner = work / 'c-installer'
        invoke(['cc', '-std=c11', '-O2', '-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=2', '-Wall', '-Wextra', '-Werror', artifacts / 'maylang-bootstrap.c', '-o', c_runner], work, environment)
        shell_script = (artifacts / 'maylang-install.sh').read_bytes()
        shutil.rmtree(work / 'checkout')
        installed_tools(prefix, work, environment)
        assert invoke(['sh', '-c', '. "$1"; before=$PATH; . "$1"; test "$before" = "$PATH"; mayc --version', 'sh', prefix / 'env.sh'], work, environment).returncode == 0
        # The compiled C bootstrap and Maylang verification require no programs on PATH.
        c_prefix = work / 'c-prefix'
        invoke([c_runner, '--yes', '--no-modify-path', '--prefix=' + str(c_prefix)], work, {**environment, 'PATH': ''})
        assert (c_prefix / 'bin/mayc').exists()
        shell_prefix = work / 'shell-prefix'
        invoke(['sh', '-s', '--', '--yes', '--no-modify-path', '--prefix=' + str(shell_prefix)], work, environment, data=shell_script)
        assert (shell_prefix / 'bin/mayc').exists()
        # Uninstall owns its files and exact profile block, never unrelated data.
        (prefix / 'notes.txt').write_text('keep me')
        profile.write_text(profile.read_text() + '# another user setting\n')
        invoke([prefix / 'bin/may-uninstall'], work, environment)
        invoke([installer, '--uninstall', '--yes', '--prefix', prefix], work, environment)
        assert (prefix / 'notes.txt').read_text() == 'keep me'
        assert not (prefix / 'bin').exists() and not (prefix / 'releases').exists()
        assert profile.read_text() == '# user configuration\nexport USER_SETTING=kept\n\n# another user setting\n'
        for root in (tui_prefix, plain_prefix, custom_prefix, c_prefix, shell_prefix):
            invoke([root / 'bin/may-uninstall'], work, environment)
            assert not root.exists(), root
        print('PASS independent copies, repository deletion, all five tools and staged verification failure')
        print('PASS arrow navigation, component checkboxes, plain menus, cancellation/terminal restoration, profiles and safe uninstall')
        print('PASS standalone host-cc bootstrap with empty PATH and piped self-contained shell installer')


if __name__ == '__main__':
    main()
