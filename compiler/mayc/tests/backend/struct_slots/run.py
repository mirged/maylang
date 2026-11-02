#!/usr/bin/env python3
"""Before/after record-layout measurements for #134 (see ../struct-slots.md).

Usage: run.py OLD_MAYC NEW_MAYC OUT.json [--rounds N] [--self-compile] [--cpu C]

The workloads are the struct-field ones (`../struct_fields/`) plus
`record_gc.may`, which churns grown records over a live tree. Every workload is
built by both compilers; the runtime is read at compile time, so OLD_MAYC must
sit beside its own runtime sidecars. Rounds are interleaved (each runs every
binary once, alternating the order) so load drift on a shared machine affects
before and after alike. Each sample records wall time, the child's user+system
CPU time and its peak resident set, and outputs must match. --self-compile also
times each compiler compiling compiler/mayc/main.may. --cpu pins every measured
child to one CPU with taskset; on a shared machine the short workloads need that
to keep scheduling noise out of the medians.
"""
import argparse, hashlib, json, os, platform, statistics, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
# Existing struct-field workloads, reused so before and after see the same code.
STRUCT_FIELDS = HERE.parent / "struct_fields"
WORKLOADS = [HERE / "record_gc.may"] + [STRUCT_FIELDS / name for name in
             ("nbody.may", "trees.may", "construct.may", "read_field2.may", "read_local.may")]


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
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--self-compile", action="store_true")
    parser.add_argument("--cpu", help="pin each measured child to this CPU with taskset")
    parser.add_argument("--workload", action="append", default=[],
                        help="measure only these workload stems (repeatable)")
    args = parser.parse_args()
    workloads = WORKLOADS
    if args.workload:
        workloads = [source for source in WORKLOADS if source.stem in args.workload]
        assert workloads, f"no workload matches {args.workload}"
    compilers = {"before": args.old, "after": args.new}
    with tempfile.TemporaryDirectory() as work:
        commands = {}
        for source in workloads:
            for side, compiler in compilers.items():
                binary = Path(work) / f"{source.stem}.{side}"
                subprocess.run([compiler, str(source), "-o", str(binary)], check=True)
                commands[(source.stem, side)] = [str(binary)]
        if args.self_compile:
            for side, compiler in compilers.items():
                commands[("self_compile", side)] = [compiler, str(ROOT / "compiler/mayc/main.may"),
                                                    "-o", str(Path(work) / f"selfhost.{side}")]
        if args.cpu:
            for key, command in commands.items():
                commands[key] = ["taskset", "-c", args.cpu, *command]
        keys = list(commands)
        outputs = {}
        for key in keys:
            # Warm-up: first-touch pages and the file cache affect RSS and time.
            outputs[key] = sample(commands[key])[0]
        for name in {name for name, _ in keys}:
            if outputs[(name, "before")] != outputs[(name, "after")]:
                sys.exit(f"output differs: {name}")
        samples = {key: [] for key in keys}
        for round_index in range(args.rounds):
            for key in keys if round_index % 2 == 0 else keys[::-1]:
                _, wall, cpu, rss = sample(commands[key])
                samples[key].append({"wall_s": wall, "cpu_s": cpu, "max_rss_kb": rss})
    results = []
    for (name, side), runs in samples.items():
        results.append({
            "workload": name, "side": side, "samples": runs,
            "median_wall_ms": round(statistics.median(r["wall_s"] for r in runs) * 1000, 2),
            "median_cpu_ms": round(statistics.median(r["cpu_s"] for r in runs) * 1000, 2),
            "min_cpu_ms": round(min(r["cpu_s"] for r in runs) * 1000, 2),
            "median_max_rss_kb": int(statistics.median(r["max_rss_kb"] for r in runs)),
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
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    for r in results:
        print(f"{r['workload']:>13} {r['side']:>6}  wall {r['median_wall_ms']:>9} ms  cpu {r['median_cpu_ms']:>9} ms"
              f"  rss {r['median_max_rss_kb']:>8} KiB")


if __name__ == "__main__":
    main()
