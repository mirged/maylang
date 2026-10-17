#!/usr/bin/env python3
"""Exercise the public curl-to-sh flow with real native assets over loopback HTTP."""
import argparse
import socket
import sys
import fcntl
import termios
import struct
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'install.sh'


class DownloadTests(unittest.TestCase):
    artifacts = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maylang-one-line-')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.home = self.work / 'home'
        self.home.mkdir()
        self.prefix = self.work / "toolchain with ' quotes"
        self.environment = {key: value for key, value in os.environ.items() if key not in ('MAYC', 'MAYLANG_STDLIB', 'MAYLANG_VERSION', 'NO_COLOR')}
        self.environment.update(HOME=str(self.home), SHELL='/bin/bash', TERM='xterm-256color')
        self.web = self.work / 'web'
        assets = self.web / 'latest/download'
        assets.mkdir(parents=True)
        shutil.copy2(SCRIPT, self.web / 'install.sh')
        for name in ('maylang-init-x86_64-linux', 'maylang-init-x86_64-linux.sha256'):
            shutil.copy2(self.artifacts / name, assets / name)
        (self.web / 'download').mkdir()
        (self.web / 'download/v0.12.1').symlink_to('../latest/download', target_is_directory=True)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        self.server = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1', '--directory', str(self.web)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                if self.server.poll() is not None or time.monotonic() > deadline:
                    self.fail('HTTP fixture could not start')
                time.sleep(.02)
        self.url = f'http://127.0.0.1:{port}'
        self.environment['MAYLANG_DIST_ROOT'] = self.url

    def stop_server(self):
        self.server.terminate()
        self.server.wait(timeout=5)

    def remove_asset(self):
        (self.web / 'latest/download/maylang-init-x86_64-linux').unlink()

    def run_script(self, *options):
        return subprocess.run(['sh', '-s', '--', *options], input=SCRIPT.read_bytes(), cwd=self.work,
                              env=self.environment, capture_output=True, timeout=90, start_new_session=True)

    def test_prebuilt_install_has_no_build_tools_and_runs_from_path(self):
        blockers = self.work / 'build-tool-blockers'
        blockers.mkdir()
        marker = self.work / 'build-tool-was-called'
        for name in ('make', 'cc', 'gcc', 'clang', 'rustc', 'cargo', 'python3'):
            stub = blockers / name
            stub.write_text('#!/bin/sh\ntouch "$HOME/../build-tool-was-called"\nexit 99\n')
            stub.chmod(0o755)
        self.environment['PATH'] = str(blockers) + ':' + self.environment['PATH']
        self.environment['MAYLANG_VERSION'] = 'v0.12.1'
        result = self.run_script('--yes', '--prefix=' + str(self.prefix), '--no-modify-path', '--plain')
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertFalse(marker.exists())
        self.assertFalse((self.home / '.bashrc').exists())
        source = self.work / 'hello.may'
        source.write_text('print(42);\n')
        env = {**self.environment, 'PATH': str(self.prefix / 'bin') + ':' + os.environ['PATH']}
        subprocess.run(['mayc', str(source), '-o', str(self.work / 'hello')], env=env, cwd=self.work, check=True, capture_output=True)
        self.assertEqual(subprocess.check_output([str(self.work / 'hello')]), b'42\n')
        self.assertIn(b'Download verified', result.stderr)
        self.assertNotIn(b'\x1b[', result.stdout)
        subprocess.run([str(self.prefix / 'bin/may-uninstall')], env=env, check=True, capture_output=True)

    def test_interactive_curl_pipe_keeps_terminal_input(self):
        child, descriptor = pty.fork()
        if child == 0:
            os.chdir(self.work)
            os.execve('/bin/sh', ['sh', '-c', 'curl -fsSL "$1/install.sh" | sh -s -- --prefix "$2" --no-modify-path',
                                 'sh', self.url, str(self.prefix)], self.environment)
        fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 88, 0, 0))
        transcript = bytearray()
        chosen = False
        deadline = time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                if select.select([descriptor], [], [], .1)[0]:
                    try:
                        transcript.extend(os.read(descriptor, 65536))
                    except OSError:
                        pass
                    if b'esc cancel' in transcript and not chosen:
                        os.write(descriptor, b'\r')
                        chosen = True
                waited, status = os.waitpid(child, os.WNOHANG)
                if waited:
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0, transcript.decode(errors='replace'))
                    self.assertTrue(chosen)
                    self.assertIn(b"You're ready to May", transcript)
                    self.assertTrue((self.prefix / 'bin/mayc').exists())
                    return
            self.fail('curl-to-sh interaction timed out: ' + transcript.decode(errors='replace'))
        finally:
            try:
                os.killpg(child, signal.SIGKILL)
                os.waitpid(child, 0)
            except ProcessLookupError:
                pass
            os.close(descriptor)

    def test_checksum_mismatch_never_runs_the_installer(self):
        (self.web / 'latest/download/maylang-init-x86_64-linux.sha256').write_text('0' * 64 + '  maylang-init-x86_64-linux\n')
        result = self.run_script('--yes', '--prefix', str(self.prefix))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'did not match its checksum', result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_interrupt_restores_the_terminal(self):
        child, descriptor = pty.fork()
        if child == 0:
            executable = str(self.artifacts / 'maylang-init-x86_64-linux')
            os.execve(executable, [executable, '--prefix', str(self.prefix), '--no-modify-path'], self.environment)
        fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 88, 0, 0))
        before = termios.tcgetattr(descriptor)
        transcript = bytearray()
        interrupted = False
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                if select.select([descriptor], [], [], .1)[0]:
                    try:
                        transcript.extend(os.read(descriptor, 65536))
                    except OSError:
                        pass
                    if b'esc cancel' in transcript and not interrupted:
                        self.assertFalse(termios.tcgetattr(descriptor)[3] & termios.ICANON)
                        os.kill(child, signal.SIGTERM)
                        interrupted = True
                waited, status = os.waitpid(child, os.WNOHANG)
                if waited:
                    self.assertTrue(interrupted)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 143)
                    self.assertEqual(termios.tcgetattr(descriptor)[3], before[3])
                    self.assertFalse(self.prefix.exists())
                    return
            self.fail('interrupted installer did not stop')
        finally:
            try:
                os.killpg(child, signal.SIGKILL)
                os.waitpid(child, 0)
            except ProcessLookupError:
                pass
            os.close(descriptor)

    def test_missing_asset_is_an_actionable_failure(self):
        self.remove_asset()
        result = self.run_script('--yes', '--prefix', str(self.prefix))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'could not download its installer', result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_help_needs_no_download_and_invalid_release_is_rejected(self):
        self.remove_asset()
        self.assertEqual(self.run_script('--help').returncode, 0)
        self.environment['MAYLANG_VERSION'] = '../other'
        result = self.run_script('--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Invalid MAYLANG_VERSION', result.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    DownloadTests.artifacts = args.artifacts.resolve()
    unittest.main(argv=[__file__, *remaining])
