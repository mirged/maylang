#!/usr/bin/env python3
"""Native process API: tagged PIDs, wait failures and signal exit statuses."""
import argparse
import os
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
        source.write_text(r'''
let pid: Int = exec(["/bin/sh", "-c", "exit 7"]);
print(pid > 0, wait(pid));
let signaled: Int = exec(["/bin/sh", "-c", "kill -TERM $$"]);
print(wait(signaled));
let rejected: Bool = may { wait(pid); false } otherwise { true };
print(rejected);
let inherited: Int = exec(["/bin/sh", "-c", "test \"$MAY_PROCESS_TEST\" = \"inherited value\" && test \"$PATH\" = \"$MAY_PROCESS_PATH\""]);
print(wait(inherited));
print(system("test \"$MAY_PROCESS_TEST\" = \"inherited value\""));
print(system("exit 9"));
print(system("kill -TERM $$"));
''')
        subprocess.run([str(args.compiler.resolve()), str(source), '-o', str(work/'processes')], cwd=ROOT, check=True, timeout=60)
        environment = dict(os.environ, MAY_PROCESS_TEST='inherited value',
                           MAY_PROCESS_PATH=os.environ.get('PATH', ''))
        result = subprocess.run([str(work/'processes'), 'extra', 'arguments'],
                                env=environment, capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == b'true 7\n143\ntrue\n0\n0\n9\n143\n', result
        print('PASS exec/system inheritance, PIDs, blocking wait, signal exits and reaped errors')


if __name__ == '__main__':
    main()
