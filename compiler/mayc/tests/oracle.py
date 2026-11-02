#!/usr/bin/env python3
"""Oracle test for the fat backend's optional passes (issue #101).

`mayc --no-opt` turns off the passes that keep locals in registers, prove
static types, forward constants and turn unused top-level bindings into main
locals. This suite compiles every behaviour fixture both ways and requires the
same exit status, stdout and stderr, so a pass that changes what a program does
fails here rather than in the suite that happens to exercise it.

Fixtures are run without arguments and without stdin, as verify.py does.

Usage: python3 compiler/mayc/tests/oracle.py [--compiler PATH] [--program FILE...]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

COMPILER_DIR = Path(__file__).resolve().parent.parent
TESTS = COMPILER_DIR / "tests"
SKIP = {"mod_a.may", "architecture.may", "abi.may"}


def compile_and_run(compiler, source, binary, extra):
    command = [str(compiler), *extra, str(source), "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return ("compile failed: " + " ".join(command), built.stdout, built.stderr)
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=120)
    return ran.returncode, ran.stdout, ran.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compiler", type=Path, default=COMPILER_DIR / "mayc_new")
    parser.add_argument("--program", dest="programs", action="append", default=[])
    options = parser.parse_args()

    compiler = options.compiler.resolve()
    version = subprocess.run([str(compiler), "--version"], capture_output=True, text=True)
    print(f"oracle: {compiler} ({version.stdout.strip() or version.stderr.strip()})", flush=True)
    programs = [Path(p) for p in options.programs] or [
        source for source in sorted(TESTS.glob("*.may")) if source.name not in SKIP]

    failures = 0
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        for index, source in enumerate(programs):
            optimized = compile_and_run(compiler, source, work / f"opt-{index}", [])
            plain = compile_and_run(compiler, source, work / f"plain-{index}", ["--no-opt"])
            if optimized != plain:
                failures += 1
                print(f"FAIL {source.name}: optimized {optimized!r} != --no-opt {plain!r}")
            else:
                print(f"PASS {source.name}")
    print(f"{len(programs) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
