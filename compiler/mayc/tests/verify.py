#!/usr/bin/env python3
"""Differential regressions, area harnesses, diagnostics, ELF, and current entrypoints.

Bootstrap convergence is checked separately by compiler/rust/test.py
(`make test-bootstrap`).
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
COMPILER = ROOT / "compiler/mayc"
ARTIFACTS = ROOT / "tests/compliance/build"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="verify-", dir=ARTIFACTS))
RESULTS = []


def run(argv, stdin=b"", timeout=180):
    return subprocess.run([str(value) for value in argv], input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=ROOT, timeout=timeout,
                          env=dict(os.environ, MAYLANG_STDLIB=str(ROOT / "stdlib")))


def record(name, ok, detail=""):
    RESULTS.append({"name": name, "passed": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if not ok else ""), flush=True)


def compile_source(compiler, source, binary, timeout=180):
    result = run([compiler, source, "-o", binary], timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))


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
    # Interactive UI programs need the native UI library and a window/snapshot
    # harness. Their runtime checks live in tests/ui/run.py.
    showcase = ROOT / "examples/ui_showcase.may"
    sources = [source for source in sorted((ROOT / "examples").glob("*.may")) if source != showcase]
    sources += [ROOT / "examples/modules/app.may"]
    sources += [
        ROOT / "examples/apps/maytasks/main.may",
        ROOT / "examples/apps/textstats/main.may",
        ROOT / "examples/games/starfall/main.may",
        ROOT / "examples/tools/rivet/main.may",
        ROOT / "examples/simulations/ecosystem/main.may",
    ]
    print(f"Testing {len(sources)} current entrypoints", flush=True)
    for source, label in [(ROOT / "examples/apps/mayboard/src/main.may", "mayboard"), (showcase, "showcase")]:
        ui = run([compiler, "--check", source])
        record(f"target {label} UI type contracts", ui.returncode == 0, ui.stderr.decode())
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


# Area harnesses: each takes --compiler and exits nonzero on failure.
HARNESSES = [
    (["cli.py"], "source-free target discovery and runtime defaults"),
    (["comments.py"], "nested comments and source-aware import expansion"),
    (["strict_types.py"], "strict type contracts"),
    (["modules.py"], "module identities and visibility"),
    (["backends.py"], "backend contexts and cross-target formats"),
    (["raw_codegen.py"], "raw x86-64 code generation and workload checksums"),
    (["regalloc.py"], "linear-scan allocation and GC roots"),
    (["core_runtime.py"], "portable core runtime across formats"),
    (["portable_values.py"], "portable collections, closures and calling conventions"),
    (["runtime_maps.py"], "runtime hash tables and allocation bins"),
    (["gc.py"], "GC allocation identity and repeated collections"),
    (["gc_stress.py", "--self-test"], "seeded GC graph oracle, heap invariants and suspended closures"),
    (["stdlib_contracts.py"], "typed standard-library contracts"),
    (["strings.py"], "Unicode string operations and long environments"),
    (["json_controls.py"], "JSON control escaping and independent parser roundtrips"),
    (["processes.py"], "process inheritance and exit contracts"),
    (["file_io.py"], "complete binary file I/O"),
    (["source_files.py"], "compiler source read failures and empty files"),
    (["reachability.py"], "reachable functions, runtime helpers and loader dependencies"),
    (["behavior.py"], "scalar pure behavior contracts"),
    (["effect_rows.py"], "effect ceilings and recursive propagation"),
    (["behavior_reports.py"], "inspectable behavior summaries"),
    (["behavior_scalars.py"], "floating-point behavior contracts and pure constants"),
    (["behavior_control_flow.py"], "private scalar state and while-loop behavior contracts"),
    (["behavior_ir.py"], "behavior metadata survives frontend-to-IR snapshots"),
    (["behavior_function_types.py"], "callable effect-row type operations and variance"),
    (["behavior_callbacks.py"], "source callable ceilings and callback laundering rejection"),
    (["list_guards.py"], "dynamic list type and index guards"),
    (["numeric_contracts.py"], "numeric bounds and array lengths"),
    (["float_literals.py"], "correctly rounded float literals"),
    (["float_math.py"], "transcendental functions and floating powers on every backend"),
    (["float_text.py"], "shortest round-trip display and correctly rounded parsing"),
    (["strength_reduction.py"], "signed power-of-two codegen and runtime fallbacks"),
    (["diagnostics.py"], "structured diagnostics and recovery"),
    (["debug_traces.py"], "debug traces and fiber isolation"),
    (["fibers.py"], "suspended fiber handlers and caught errors"),
    (["externs.py"], "typed scalar externs and C-ABI stack arguments"),
    (["nodeos.py"], "x86_64-nodeos NXF images and target diagnostics"),
    (["fuzz.py"], "bounded frontend fuzzing"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features-only", action="store_true", help="skip the example entry points")
    parser.add_argument("--compiler", type=Path, default=COMPILER / "mayc_new")
    options = parser.parse_args()
    compiler = options.compiler.resolve()
    try:
        features(compiler)
        architecture(compiler)
        for (script, *args), name in HARNESSES:
            result = run([sys.executable, COMPILER / "tests" / script, "--compiler", compiler, *args], timeout=180)
            record(name, result.returncode == 0, (result.stdout + result.stderr).decode())
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
