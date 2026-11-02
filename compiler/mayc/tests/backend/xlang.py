#!/usr/bin/env python3
"""Cross-language benchmark suite for the performance roadmap (#101).

Builds the eight roadmap workloads in Maylang plus every other implementation
whose toolchain is installed, checks that every language prints the same
output, and reports median whole-process wall time and peak RSS per benchmark.

The suite is deliberately not a correctness gate: it lives beside the compiler
tests and is run by hand (or by the optional CI job) when a phase lands. A
benchmark that changes behaviour must fail here rather than silently time a
different program.

Usage:
    python3 xlang.py                       # build, verify, time, print tables
    python3 xlang.py --runs 10             # more samples
    python3 xlang.py --bench collatz trees # a subset
    python3 xlang.py --compiler /path/mayc_new --report out.md --json out.json

Every language is optional; a missing toolchain is skipped and reported.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE / "xlang"
LANGS = ["maylang", "c", "rust", "java", "node", "python"]
# Whole-process medians are dominated by the workload, not by the build, so the
# default of five samples after one warm-up keeps a full run near ten minutes.
DEFAULTS = {"runs": 5, "warmup": 1}

BENCHMARKS = ["fib", "collatz", "sieve", "hashmap", "strings", "mandelbrot", "nbody", "trees"]

TOOLS = {"c": "gcc", "rust": "rustc", "java": "javac", "node": "node", "python": "python3"}


def run(cmd, **kwargs):
    """Run a command, echoing it on failure, and return the completed process."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        sys.stderr.write("$ " + " ".join(str(c) for c in cmd) + "\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("command failed: " + " ".join(str(c) for c in cmd))
    return result


def available(compiler):
    """The languages whose toolchain is present, plus any skip reasons."""
    present = {"maylang": True}
    missing = {}
    for lang, tool in TOOLS.items():
        if shutil.which(tool) is None:
            missing[lang] = tool + " not found"
        else:
            present[lang] = True
    if not Path(compiler).exists():
        raise SystemExit(f"compiler not found: {compiler}")
    return present, missing


def build(compiler, build_dir, benches, present, missing):
    """Build every implementation; return {bench: {lang: command list}}."""
    build_dir.mkdir(parents=True, exist_ok=True)
    java_dir = build_dir / "java"
    commands = {}
    for bench in benches:
        commands[bench] = {}
        may_src = SUITE / "may" / f"{bench}.may"
        out = build_dir / f"may_{bench}"
        run([compiler, str(may_src), "-o", str(out)])
        commands[bench]["maylang"] = [str(out)]
        if "c" in present:
            out = build_dir / f"c_{bench}"
            run(["gcc", "-O2", "-o", str(out), str(SUITE / "c" / f"{bench}.c"), "-lm"])
            commands[bench]["c"] = [str(out)]
        if "rust" in present:
            out = build_dir / f"rs_{bench}"
            run(["rustc", "-C", "opt-level=3", "-o", str(out), str(SUITE / "rs" / f"{bench}.rs")])
            commands[bench]["rust"] = [str(out)]
        if "node" in present:
            commands[bench]["node"] = ["node", str(SUITE / "js" / f"{bench}.js")]
        if "python" in present:
            commands[bench]["python"] = [sys.executable, str(SUITE / "py" / f"{bench}.py")]
    if "java" in present:
        java_dir.mkdir(exist_ok=True)
        sources = [str(SUITE / "java" / f"{bench.capitalize()}.java") for bench in benches]
        run(["javac", "-d", str(java_dir)] + sources)
        for bench in benches:
            commands[bench]["java"] = ["java", "-cp", str(java_dir), bench.capitalize()]
    return commands


def output_of(command):
    """The program's stdout, for the cross-language equality check."""
    return subprocess.run(command, capture_output=True, text=True).stdout.strip()


def verify(commands, benches):
    """Every language must print the same output. Returns the failures."""
    failures = []
    outputs = {}
    for bench in benches:
        seen = {}
        for lang, command in commands[bench].items():
            text = output_of(command)
            seen[lang] = text
        outputs[bench] = seen
        reference = seen.get("maylang")
        for lang, text in seen.items():
            if text != reference:
                failures.append(f"{bench}: {lang} printed {text!r}, maylang {reference!r}")
    return outputs, failures


def time_hyperfine(commands, bench, runs, warmup):
    """Median wall time per language from one hyperfine run (seconds)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        export = handle.name
    try:
        invocation = ["hyperfine", "-N", "--warmup", str(warmup), "--runs", str(runs),
                      "--export-json", export]
        for lang, command in commands[bench].items():
            invocation += ["-n", lang, " ".join(command)]
        result = subprocess.run(invocation, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        with open(export) as handle:
            data = json.load(handle)
        return {entry["command"]: entry["median"] for entry in data["results"]}
    finally:
        os.unlink(export)


def time_internal(commands, bench, runs, warmup):
    """Median wall time per language without hyperfine, interleaving samples."""
    samples = {lang: [] for lang in commands[bench]}
    for _ in range(warmup):
        for command in commands[bench].values():
            subprocess.run(command, capture_output=True)
    for _ in range(runs):
        for lang, command in commands[bench].items():
            start = time.perf_counter()
            subprocess.run(command, capture_output=True)
            samples[lang].append(time.perf_counter() - start)
    return {lang: statistics.median(values) for lang, values in samples.items()}


def peak_rss(commands, bench):
    """Peak RSS in MiB per language, from the child's own rusage."""
    rss = {}
    for lang, command in commands[bench].items():
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL)
        _, status, usage = os.wait4(process.pid, 0)
        if status != 0:
            raise SystemExit(f"{bench}: {lang} exited with status {status}")
        rss[lang] = usage.ru_maxrss / 1024.0
    return rss


def tables(times, rss, benches, langs):
    """The two Markdown tables the reports and docs quote."""
    head = "| benchmark | " + " | ".join(langs) + " | may/C | may/python |"
    rule = "|" + "---|" * (len(langs) + 3)
    rows = [head, rule]
    for bench in benches:
        row = [bench]
        for lang in langs:
            row.append(f"{times[bench][lang] * 1000:.0f}" if lang in times[bench] else "-")
        c = times[bench].get("c")
        python = times[bench].get("python")
        row.append(f"{times[bench]['maylang'] / c:.1f}x" if c else "-")
        row.append(f"{times[bench]['maylang'] / python:.2f}x" if python else "-")
        rows.append("| " + " | ".join(row) + " |")
    memory = ["| benchmark | " + " | ".join(langs) + " |", "|" + "---|" * (len(langs) + 1)]
    for bench in benches:
        row = [bench]
        for lang in langs:
            row.append(f"{rss[bench][lang]:.0f}" if lang in rss[bench] else "-")
        memory.append("| " + " | ".join(row) + " |")
    return "\n".join(rows), "\n".join(memory)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cross-language benchmark suite (#101)")
    parser.add_argument("--compiler", default=str(HERE.parent.parent / "mayc_new"),
                        help="mayc binary (default: compiler/mayc/mayc_new)")
    parser.add_argument("--bench", nargs="+", default=BENCHMARKS, choices=BENCHMARKS)
    parser.add_argument("--runs", type=int, default=DEFAULTS["runs"])
    parser.add_argument("--warmup", type=int, default=DEFAULTS["warmup"])
    parser.add_argument("--build-dir", default=None, help="where binaries are written")
    parser.add_argument("--json", default=None, help="write the raw results here")
    parser.add_argument("--report", default=None, help="write the Markdown tables here")
    parser.add_argument("--no-rss", action="store_true", help="skip the peak-RSS pass")
    args = parser.parse_args(argv)

    compiler = str(Path(args.compiler).resolve())
    present, missing = available(compiler)
    for lang in sorted(missing):
        print(f"skip {lang}: {missing[lang]}", file=sys.stderr)
    langs = [lang for lang in LANGS if lang in present]

    build_dir = Path(args.build_dir) if args.build_dir else HERE / "build"
    commands = build(compiler, build_dir, args.bench, present, missing)
    outputs, failures = verify(commands, args.bench)
    if failures:
        for failure in failures:
            print("output mismatch: " + failure, file=sys.stderr)
        return 1

    timer = time_hyperfine if shutil.which("hyperfine") else time_internal
    if timer is time_internal:
        print("note: hyperfine not found, timing in-process", file=sys.stderr)
    times = {}
    rss = {}
    for bench in args.bench:
        times[bench] = timer(commands, bench, args.runs, args.warmup)
        rss[bench] = {} if args.no_rss else peak_rss(commands, bench)
        print(f"done {bench}", file=sys.stderr)

    wall, memory = tables(times, rss, args.bench, langs)
    report = ["Medians are whole-process wall time in ms; '-' is a missing toolchain.", "",
              wall]
    if not args.no_rss:
        report += ["", "Peak RSS in MiB:", "", memory]
    report += ["", "maylang " + maylang_identity(compiler) + "; " + sample_identity(args.runs, args.warmup)]
    text = "\n".join(report) + "\n"
    print(text if args.report is None else f"wrote {args.report}")
    if args.report:
        Path(args.report).write_text(text)
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"compiler": maylang_identity(compiler), "runs": args.runs, "warmup": args.warmup,
             "times_ms": {b: {l: t * 1000 for l, t in times[b].items()} for b in times},
             "rss_mib": rss, "outputs": outputs,
             "skipped": missing}, indent=1) + "\n")
    return 0


def maylang_identity(compiler):
    try:
        return run([compiler, "--version"]).stdout.strip().replace("\n", " ")
    except SystemExit:
        return "mayc"


def sample_identity(runs, warmup):
    return f"{runs} runs after {warmup} warm-up"


if __name__ == "__main__":
    sys.exit(main())
