#!/usr/bin/env python3
"""Before/after measurements for fat code alignment, #131.

Usage: run.py OLD_MAYC NEW_MAYC OUT.json [--rounds N] [--self-compile] [--cpu N]

The eight cross-language benchmarks are compiled by both compilers and timed as
whole processes. --self-compile adds two compiler-throughput workloads: each
compiler compiling compiler/mayc/main.may and examples/features.may. Runs are
interleaved (each round runs every side once, alternating the order) so load
drift on a shared machine affects before and after alike; child CPU time is the
metric and --cpu pins every measured child with taskset.

The runtime is read at compile time, so each compiler must sit beside its own
runtime sidecars. Rounds are interleaved (each runs every binary once,
alternating the order) so load drift on a shared machine affects before and
after alike. Each sample records wall time, the child's user+system CPU time
and its peak RSS, and outputs must match. --self-compile also times each
compiler compiling compiler/mayc/main.may, which is fat code itself.
--cpu pins every measured child to one CPU with taskset: this host has P-cores
(CPUs 0-7) and slower E-cores, and an unpinned process migrates between them,
which makes the same binary measure up to 55% apart.
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
XLANGE = HERE.parent / "xlang" / "may"
ROADMAP = {}


def sample(command):
    start = time.perf_counter()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE)
    out = proc.stdout.read()
    _, status, usage = os.wait4(proc.pid, 0)
    wall = time.perf_counter() - start
    if status != 0:
        sys.exit(f"{command[0]} exited with status {status}")
    return out, wall, usage.ru_utime + usage.ru_stime, usage.ru_maxrss


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("out")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--self-compile", action="store_true")
    parser.add_argument("--cpu", type=int, default=None, help="pin measured children to this CPU")
    args = parser.parse_args()
    compilers = {"before": args.old, "after": args.new}
    sources = [(source.stem, source) for source in sorted(XLANGE.glob("*.may"))]
    with tempfile.TemporaryDirectory() as work:
        commands = {}
        for name, source in sources:
            for side, compiler in compilers.items():
                binary = Path(work) / f"{name}.{side}"
                subprocess.run([compiler, str(source), "-o", str(binary)], check=True)
                commands[(name, side)] = [str(binary)]
        if args.self_compile:
            for side, compiler in compilers.items():
                commands[("self_compile", side)] = [compiler, str(ROOT / "compiler/mayc/main.may"),
                                                    "-o", str(Path(work) / f"selfhost.{side}")]
                commands[("features_compile", side)] = [compiler, str(ROOT / "examples/features.may"),
                                                        "-o", str(Path(work) / f"features.{side}")]
        keys = list(commands)
        if args.cpu is not None:
            commands = {key: ["taskset", "-c", str(args.cpu)] + command for key, command in commands.items()}
        outputs = {key: sample(commands[key])[0] for key in keys}  # warm-up
        for name in {name for name, _ in keys}:
            if name.endswith("_compile"):
                continue
            if outputs[(name, "before")] != outputs[(name, "after")]:
                sys.exit(f"output differs: {name}")
        samples = {key: [] for key in keys}
        for round_index in range(args.rounds):
            order = keys if round_index % 2 == 0 else keys[::-1]
            for key in order:
                _, wall, cpu, rss = sample(commands[key])
                samples[key].append({"wall_s": wall, "cpu_s": cpu, "max_rss_kib": rss})
    results = []
    for (name, side), runs in samples.items():
        results.append({
            "workload": name, "side": side, "samples": runs,
            "median_wall_ms": round(statistics.median(r["wall_s"] for r in runs) * 1000, 2),
            "median_cpu_ms": round(statistics.median(r["cpu_s"] for r in runs) * 1000, 2),
            "max_rss_mib": round(max(r["max_rss_kib"] for r in runs) / 1024, 1),
            "output": outputs[(name, side)].decode().strip(),
        })

    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    def binary(path):
        launcher = Path(path).resolve()
        built = launcher.parent / "build/bin/mayc_new"
        return built if built.exists() else launcher

    report = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": git("rev-parse", "HEAD"),
        "status": git("status", "--short", "--", "compiler", "stdlib"),
        "compiler_sha256": {side: hashlib.sha256(binary(path).read_bytes()).hexdigest() for side, path in compilers.items()},
        "runtime_sha256": {side: hashlib.sha256((Path(path).resolve().parent / "runtime/fat.may").read_bytes()).hexdigest()
                           for side, path in compilers.items()},
        "uname": " ".join(platform.uname()),
        "loadavg": os.getloadavg(),
        "rounds": args.rounds,
        "cpu": args.cpu,
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    for r in results:
        print(f"{r['workload']:>13} {r['side']:>6}  wall {r['median_wall_ms']:>9} ms  cpu {r['median_cpu_ms']:>9} ms  rss {r['max_rss_mib']:>7} MiB")


if __name__ == "__main__":
    main()
