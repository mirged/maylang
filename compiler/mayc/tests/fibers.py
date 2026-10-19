#!/usr/bin/env python3
"""Observe scheduler ordering and fault isolation across suspended fibers."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]

CASES = {
    'handlers': ('''
fun worker(id: Int) -> Nil {
    let result: Str = may {
        print("start", id); yield();
        may { yield(); fail("inner"); } otherwise { print(id, err.message); };
        fail(str(id));
        "bad"
    } otherwise { str(err.message) };
    print("caught", id, result);
    return nil;
}
spawn(fun() -> Nil { worker(1); return nil; });
spawn(fun() -> Nil { worker(2); return nil; });
print(may { run(); fail("main"); "bad" } otherwise { str(err.message) });
''', 0, b'start 1\nstart 2\n1 inner\ncaught 1 1\n2 inner\ncaught 2 2\nmain\n'),
    'caught-error': ('''
fun worker(id: Str) -> Nil {
    may { fail(id); } otherwise { yield(); print(err.message); };
    return nil;
}
spawn(fun() -> Nil { worker("first"); return nil; });
spawn(fun() -> Nil { worker("second"); return nil; });
run(); run(); yield(); print("done");
''', 0, b'first\nsecond\ndone\n'),
    'uncaught': ('''
spawn(fun() -> Nil { yield(); fail("worker"); return nil; });
may { run(); } otherwise { print("wrong handler"); };
''', 70, b'fail: worker\n'),
    'captures': ('''
fun launch() -> Nil {
    mut n: Int = 0;
    spawn(fun() -> Nil { n += 1; yield(); n += 10; print(n); return nil; });
    spawn(fun() -> Nil { n += 2; yield(); n += 20; print(n); return nil; });
    return nil;
}
launch(); run();
''', 0, b'13\n33\n'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    parser.add_argument('--llvm', action='store_true')
    args = parser.parse_args()
    targets = ['x86_64-linux', 'clang-llvm'] if args.llvm else ['x86_64-linux']
    with tempfile.TemporaryDirectory(prefix='mayc-fibers-') as directory:
        work = Path(directory)
        for name, (text, status, output) in CASES.items():
            source = work / f'{name}.may'
            source.write_text(text)
            for target in targets:
                binary = work / f'{name}-{target}'
                result = subprocess.run([str(args.compiler.resolve()), '--target', target,
                                         str(source), '-o', str(binary)],
                                        capture_output=True, timeout=120)
                assert result.returncode == 0, result.stderr.decode()
                result = subprocess.run([str(binary)], capture_output=True, timeout=20)
                assert (result.returncode, result.stdout, result.stderr) == (status, output, b''), (name, target, result)
                print(f'PASS {target} fibers: {name}', flush=True)


if __name__ == '__main__':
    main()
