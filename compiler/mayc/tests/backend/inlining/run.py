#!/usr/bin/env python3
"""Default vs --inline measurements for the opt-in inliner, #131.

Usage: run.py MAYC OUT.json [--rounds N] [--throughput] [--cpu N]

One compiler is built with the inliner behind the `--inline` flag (off by
default), so the two sides are the same binary: "default" compiles without the
flag and "inline" with it. That isolates the pass. The workloads beside this
script are the shapes the earlier inlining attempts measured: a struct field
accessor, a one-expression helper and a constructor wrapper, each called in a
hot loop. The eight cross-language benchmarks are the suite. --throughput adds
the compiler compiling compiler/mayc/main.may and examples/features.may.

Runs are interleaved (each round runs every command once per side, alternating
order) so load drift on a shared machine affects both sides alike; the metric is
the child's user+system CPU time and --cpu pins every measured child with
taskset. Behaviour must match between the two sides before timing.
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
SIDES = {"default": [], "inline": ["--inline"]}


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
    parser.add_argument("compiler")
    parser.add_argument("out")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--throughput", action="store_true")
    parser.add_argument("--cpu", type=int, default=None, help="pin measured children to this CPU")
    args = parser.parse_args()
    compiler = str(Path(args.compiler).resolve())
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        commands = {}
        runs = [(source.stem, source) for source in sorted(HERE.glob("*.may"))]
        runs += [(source.stem, source) for source in sorted(XLANGE.glob("*.may"))]
        for name, source in runs:
            for side, flags in SIDES.items():
                binary = work / f"{name}.{side}"
                subprocess.run([compiler, *flags, str(source), "-o", str(binary)], check=True)
                commands[(name, side)] = [str(binary)]
        if args.throughput:
            for side, flags in SIDES.items():
                commands[("self_compile", side)] = [compiler, *flags, str(ROOT / "compiler/mayc/main.may"),
                                                    "-o", str(work / f"selfhost.{side}")]
                commands[("features_compile", side)] = [compiler, *flags, str(ROOT / "examples/features.may"),
                                                        "-o", str(work / f"features.{side}")]
        keys = list(commands)
        measured = {key: ["taskset", "-c", str(args.cpu)] + command for key, command in commands.items()} \
            if args.cpu is not None else commands
        outputs = {key: sample(measured[key])[0] for key in keys}  # warm-up
        for name in {name for name, _ in keys}:
            if name.endswith("_compile"):
                continue
            if outputs[(name, "default")] != outputs[(name, "inline")]:
                sys.exit(f"output differs: {name}")
        samples = {key: [] for key in keys}
        for round_index in range(args.rounds):
            order = keys if round_index % 2 == 0 else keys[::-1]
            for key in order:
                _, wall, cpu, rss = sample(measured[key])
                samples[key].append({"wall_s": wall, "cpu_s": cpu, "max_rss_kib": rss})
    results = []
    for (name, side), runs_ in samples.items():
        results.append({
            "workload": name, "side": side, "samples": runs_,
            "median_wall_ms": round(statistics.median(r["wall_s"] for r in runs_) * 1000, 2),
            "median_cpu_ms": round(statistics.median(r["cpu_s"] for r in runs_) * 1000, 2),
            "max_rss_mib": round(max(r["max_rss_kib"] for r in runs_) / 1024, 1),
            "output": outputs[(name, side)].decode().strip(),
        })
    report = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "compiler": compiler,
        "compiler_sha256": hashlib.sha256(Path(compiler).read_bytes()).hexdigest(),
        "uname": " ".join(platform.uname()),
        "loadavg": os.getloadavg(),
        "rounds": args.rounds,
        "cpu": args.cpu,
        "sides": SIDES,
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    by = {}
    for result in results:
        by.setdefault(result["workload"], {})[result["side"]] = result
    for workload in by:
        before = by[workload]["default"]
        after = by[workload]["inline"]
        print(f"{workload:>18} default {before['median_cpu_ms']:>9.1f} ms  "
              f"inline {after['median_cpu_ms']:>9.1f} ms  "
              f"rss {before['max_rss_mib']:>6.1f} -> {after['max_rss_mib']:.1f} MiB")


if __name__ == "__main__":
    main()
