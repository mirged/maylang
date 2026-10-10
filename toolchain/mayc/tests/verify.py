#!/usr/bin/env python3
"""Bootstrap, differential regressions, diagnostics, ELF, and current entrypoints.

The source-built compiler launcher first builds a seed. Following generations
must converge to identical binaries.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
COMPILER = ROOT / "toolchain/mayc"
BOOTSTRAP = COMPILER / "build/bootstrap"
BOOTSTRAP.mkdir(parents=True, exist_ok=True)
ARTIFACTS = ROOT / "tests/compliance/build"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="verify-", dir=ARTIFACTS))
RESULTS = []


def run(argv, stdin=b"", timeout=180):
    return subprocess.run([str(value) for value in argv], input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=ROOT, timeout=timeout)


def record(name, ok, detail=""):
    RESULTS.append({"name": name, "passed": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if not ok else ""), flush=True)


def compile_source(compiler, source, binary, timeout=180):
    result = run([compiler, source, "-o", binary], timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap():
    seed = BOOTSTRAP / "mayc_v2_seed"
    first = BOOTSTRAP / "mayc_v2_stage1"
    second = BOOTSTRAP / "mayc_v2_stage2"
    third = BOOTSTRAP / "mayc_v2_stage3"
    # The launcher builds a strict-capable compiler from Rust/C on first use.
    # The full self-hosted compiler can collect several times while building;
    # allow longer than the small regression programs, including under load.
    compile_source(COMPILER / "mayc_new", COMPILER / "main.may", seed, timeout=600)
    compile_source(seed, COMPILER / "main.may", first, timeout=600)
    compile_source(first, COMPILER / "main.may", second, timeout=600)
    compile_source(second, COMPILER / "main.may", third, timeout=600)
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in (seed, first, second, third)}
    stable = hashes[str(first.relative_to(ROOT))] == hashes[str(second.relative_to(ROOT))] == hashes[str(third.relative_to(ROOT))]
    record("bootstrap fixpoint", stable, json.dumps(hashes))
    return first


def features(compiler):
    legacy = json.loads((COMPILER / "tests/legacy_behavior.json").read_text())
    for source in sorted((COMPILER / "tests").glob("*.may")):
        if source.name in {"mod_a.may", "architecture.may", "abi.may"}:
            continue
        binary = WORK / "feature"
        compile_source(compiler, source, binary)
        result = run([binary])
        actual = (result.returncode, result.stdout, result.stderr)
        saved = legacy[source.name]
        expected = (saved["exit"], base64.b64decode(saved["stdout"]), base64.b64decode(saved["stderr"]))
        record("feature " + source.name, actual == expected, repr(actual)[:2000] if actual != expected else "")


def architecture(compiler):
    expected = {
        "architecture.may": b"3\n2 2\n1\n90\n11 12\n45\n5000050000\n17\n23\nfalse true 8 1\n-4 512 14\n2\n",
        "abi.may": b"8\n8\n[1, 2, 3, 4, 5, 6, 7, 8]\n[11, 12, 13, 14, 15, 16, 17, 18]\n",
    }
    for name, stdout in expected.items():
        binary = WORK / name.removesuffix(".may")
        compile_source(compiler, COMPILER / "tests" / name, binary)
        result = run([binary])
        record(name, result.returncode == 0 and result.stdout == stdout, repr((result.returncode, result.stdout, result.stderr)))
    errors = {
        "immutable.may": "cannot assign to let",
        "captured_immutable.may": "cannot assign to let",
        "out_of_scope.may": "unknown type or name",
        "loop_control.may": "outside a loop",
        "type_annotation.may": "expected Int, found Str",
        "type_argument.may": "expected Int, found Str",
        "type_return.may": "expected Int, found Str",
        "type_collection.may": "expected List<Int>",
        "unterminated.may": "unterminated string",
        "exponent.may": "expected exponent digits",
        "unexpected.may": "unexpected character",
    }
    for name, message in errors.items():
        binary = WORK / ("invalid-" + name)
        result = run([compiler, COMPILER / "tests/fail" / name, "-o", binary])
        error = result.stderr.decode(errors="replace")
        record("diagnostic " + name, result.returncode != 0 and message in error and "^" in error and name in error and not binary.exists(), error)


def targets(compiler):
    sources = sorted((ROOT / "examples").glob("*.may"))
    sources += [ROOT / "examples/modules/app.may"]
    sources += [
        ROOT / "example_projects/apps/maytasks/main.may",
        ROOT / "example_projects/apps/textstats/main.may",
        ROOT / "example_projects/games/starfall/main.may",
    ]
    print(f"Testing {len(sources)} current entrypoints", flush=True)
    shutil.copy2(COMPILER / "runtime.may", WORK / "runtime.may")
    shutil.copy2(COMPILER / "native.may", WORK / "native.may")
    for index, source in enumerate(sources):
        binary = WORK / f"target-{index}"
        compile_source(compiler, source, binary)
        args = []
        stdin = b"10\n" if source.name == "m_to_km.may" else b"red fish blue fish\nred fish\n"
        if source == COMPILER / "main.may":
            args = [ROOT / "examples/hello.may", "-o", WORK / "target-hello"]
        elif source.parent.name == "maylsp":
            stdin = b""
        elif source.parent.name in {"maytasks", "maypkg"}:
            args = ["help"]
        result = run([binary, *args], stdin=stdin)
        (WORK / f"target-{index}.stdout").write_bytes(result.stdout)
        (WORK / f"target-{index}.stderr").write_bytes(result.stderr)
        expected_exit = 42 if source == ROOT / "examples/selfhost_test.may" else 0
        ok = result.returncode == expected_exit
        if source == COMPILER / "main.may" and ok:
            child = run([WORK / "target-hello"])
            ok = child.returncode == 0 and child.stdout == b"Hello, Maylang!\nHello, world!\n"
        record("target " + str(source.relative_to(ROOT)), ok, repr((result.returncode, result.stderr))[:1000])
    elf = run(["readelf", "-SW", "-l", WORK / "target-0"])
    text = elf.stdout.decode()
    ok = elf.returncode == 0 and not elf.stderr and all(name in text for name in (".text", ".rodata", ".data", ".symtab", ".strtab")) and "RWE" not in text
    record("ELF sections and segment permissions", ok, elf.stderr.decode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--features-only", action="store_true")
    parser.add_argument("--compiler", type=Path, help="test an existing compiler without bootstrapping")
    options = parser.parse_args()
    try:
        compiler = options.compiler.resolve() if options.compiler else (BOOTSTRAP / "mayc_v2_stage1" if options.skip_bootstrap else bootstrap())
        features(compiler)
        architecture(compiler)
        strict = run(["python3", COMPILER / "tests/strict_types.py", "--compiler", compiler], timeout=180)
        record("strict type contracts", strict.returncode == 0, (strict.stdout + strict.stderr).decode())
        modules = run(["python3", COMPILER / "tests/modules.py", "--compiler", compiler], timeout=180)
        record("module identities and visibility", modules.returncode == 0, (modules.stdout + modules.stderr).decode())
        backends = run(["python3", COMPILER / "tests/backends.py", "--compiler", compiler], timeout=180)
        record("backend contexts and cross-target formats", backends.returncode == 0, (backends.stdout + backends.stderr).decode())
        allocator = run(["python3", COMPILER / "tests/regalloc.py", "--compiler", compiler], timeout=180)
        record("linear-scan allocation and GC roots", allocator.returncode == 0, (allocator.stdout + allocator.stderr).decode())
        core = run(["python3", COMPILER / "tests/core_runtime.py", "--compiler", compiler], timeout=180)
        record("portable core runtime across formats", core.returncode == 0, (core.stdout + core.stderr).decode())
        maps = run(["python3", COMPILER / "tests/runtime_maps.py", "--compiler", compiler], timeout=180)
        record("runtime hash tables and allocation bins", maps.returncode == 0, (maps.stdout + maps.stderr).decode())
        gc = run(["python3", COMPILER / "tests/gc.py", "--compiler", compiler], timeout=180)
        record("GC allocation identity and repeated collections", gc.returncode == 0, (gc.stdout + gc.stderr).decode())
        if not options.features_only:
            targets(compiler)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        record("verification interrupted", False, str(error))
    report = {"artifacts": str(WORK), "results": RESULTS,
              "passed": sum(item["passed"] for item in RESULTS), "failed": sum(not item["passed"] for item in RESULTS)}
    (ROOT / "tests/compliance/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['passed']} passed, {report['failed']} failed; logs: {WORK}")
    return bool(report["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
