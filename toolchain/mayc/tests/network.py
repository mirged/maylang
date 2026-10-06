#!/usr/bin/env python3
"""Offline conformance and real loopback TCP/UDP for the Maylang net module."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import errno
from pathlib import Path
import selectors
import shutil
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_suffix('')


def run(command, timeout=60):
    result = subprocess.run([str(x) for x in command], cwd=ROOT,
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


def stream_server(listener):
    conn, _ = listener.accept()
    with conn:
        conn.settimeout(10)
        for byte in 'λ\0☃'.encode():
            conn.sendall(bytes([byte]))
            time.sleep(0.005)
        payload = bytearray()
        while True:
            part = conn.recv(4096)
            if not part:
                break
            payload.extend(part)
        assert payload == b'abcd' * 262144, (len(payload), payload[:20])
        conn.sendall(b'OK')


def echo_example(server, client):
    with subprocess.Popen([str(server), '0'], cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(10), 'echo server did not announce its port'
            announcement = process.stdout.readline().strip()
            assert announcement.startswith('Listening on '), announcement
            port = int(announcement.rsplit(' ', 1)[1])
            assert run([client, port, 'Hello λ☃'], timeout=15) == 'Hello λ☃\n'
            output, error = process.communicate(timeout=15)
            assert process.returncode == 0, (output, error)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true', help='also test the direct LLVM backend')
    parser.add_argument('--require-sockets', action='store_true', help='fail if the sandbox blocks sockets')
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    available = True
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
    except OSError as error:
        if args.require_sockets or error.errno not in (errno.EPERM, errno.EACCES):
            raise
        available = False
        print(f'SKIP live loopback tests: socket creation blocked ({error})', flush=True)
    backends = [('native', [])]
    if args.llvm:
        assert shutil.which('clang'), '--llvm requires Clang'
        backends.append(('llvm', ['--target', 'clang-llvm']))
    with tempfile.TemporaryDirectory(prefix='mayc-network-') as directory:
        work = Path(directory)
        for name, flags in backends:
            for fixture in ('unit', 'loopback', 'stream'):
                binary = work / f'{fixture}-{name}'
                run([compiler, '--strict', *flags, FIXTURES / f'{fixture}.may', '-o', binary], timeout=180)
                print(f'PASS {name}: compiled {fixture}', flush=True)
                if fixture != 'unit' and not available:
                    continue
                if fixture == 'stream':
                    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
                        listener.settimeout(15)
                        listener.bind(('127.0.0.1', 0))
                        listener.listen(1)
                        server = pool.submit(stream_server, listener)
                        output = run([binary, listener.getsockname()[1]], timeout=20)
                        server.result(timeout=15)
                else:
                    output = run([binary], timeout=20)
                assert output.startswith('PASS network'), output
                print(f'PASS {name}: {output.strip()}', flush=True)
            examples = []
            for example in ('echo_server', 'echo_client'):
                binary = work / f'{example}-{name}'
                run([compiler, '--strict', *flags, ROOT / 'examples/network' / f'{example}.may',
                     '-o', binary], timeout=180)
                examples.append(binary)
            print(f'PASS {name}: compiled echo examples', flush=True)
            if available:
                echo_example(*examples)
                print(f'PASS {name}: TCP echo examples', flush=True)
        # Helpers stay private; public Socket/Address types and aliases compile.
        private = work / 'private.may'
        private.write_text('import "net" as net;\nprint(net.net_buffer(8));\n')
        result = subprocess.run([str(compiler), '--check', str(private)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and 'net_buffer' in result.stderr, result
        print('PASS network module visibility', flush=True)


if __name__ == '__main__':
    main()
