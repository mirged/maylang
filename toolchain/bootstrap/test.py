#!/usr/bin/env python3
"""Source-only bootstrap and stage convergence; no prebuilt mayc is invoked."""
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(*args):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, text=True,
                            capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result.stdout


print("Building Rust bootstrap", flush=True)
run("cargo", "build", "--offline", "--locked", "--release", "-p", "may_bootstrap")
target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target"))
if not target.is_absolute():
    target = ROOT / target
bootstrap = target / "release/may-bootstrap"
with tempfile.TemporaryDirectory(prefix="may-bootstrap-test-") as temp:
    build = Path(temp)
    for name in ["runtime.may", "native.may", "runtime"]:
        (build / name).symlink_to(ROOT / "toolchain/mayc" / name)
    (build / "prelude.may").symlink_to(ROOT / "stdlib/prelude.may")
    smoke = build / "smoke"
    run(bootstrap, HERE / "tests/smoke.may", "-o", smoke)
    assert run(smoke) == "41 42 12 42\nruntime\n12\n7\ntrue\n"
    c_source = build / "hello.c"
    run(bootstrap, "--emit-c", ROOT / "examples/hello.may", "-o", c_source)
    run(os.environ.get("CC", "cc"), "-std=gnu11", c_source, "-lm", "-o", smoke)
    expected_hello = "Hello, Maylang!\nHello, world!\n"
    assert run(smoke) == expected_hello
    compiler_source = ROOT / "toolchain/mayc/main.may"
    print("Building C stage 1", flush=True)
    stage1 = build / "mayc1"
    run(bootstrap, compiler_source, "-o", stage1)
    for stage in [1, 2, 3]:
        compiler = build / f"mayc{stage}"
        assert "mayc " in run(compiler, "--version")
        run(compiler, "--check", ROOT / "examples/strict.may")
        run(compiler, ROOT / "examples/strict.may", "-o", smoke)
        assert run(smoke) == "42 [2, 4, 6] 3 12 nonnegative\n"
        run(compiler, ROOT / "examples/hello.may", "-o", smoke)
        assert run(smoke) == expected_hello
        if stage < 3:
            print(f"Building native stage {stage + 1}", flush=True)
            run(compiler, compiler_source, "-o", build / f"mayc{stage + 1}")
    assert (build / "mayc2").read_bytes() == (build / "mayc3").read_bytes()
print("PASS: C bootstrap, closures, evaluation order, strict checking, hello, stage 2 = stage 3")
