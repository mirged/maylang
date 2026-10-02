#!/usr/bin/env python3
"""Native process API: tagged PIDs, wait failures and signal exit statuses."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--compiler', type=Path, default=ROOT/'toolchain/mayc/mayc_new')
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-processes-') as directory:
        work = Path(directory)
        source = work/'processes.may'
        source.write_text('''
let pid: Int = exec(["/bin/sh", "-c", "exit 7"]);
print(pid > 0, wait(pid));
let signaled: Int = exec(["/bin/sh", "-c", "kill -TERM $$"]);
print(wait(signaled));
let rejected: Bool = may { wait(pid); false } otherwise { true };
print(rejected);
''')
        subprocess.run([str(args.compiler.resolve()), str(source), '-o', str(work/'processes')], cwd=ROOT, check=True, timeout=60)
        result = subprocess.run([str(work/'processes')], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == b'true 7\n143\ntrue\n', result
        print('PASS process PIDs, blocking wait, signal exits and already-reaped errors')


if __name__ == '__main__':
    main()
