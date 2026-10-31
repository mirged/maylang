#!/usr/bin/env python3
"""Before/after map hashing measurements for #97 (see ../map-hashing.md).

Usage: run.py OLD_MAYC NEW_MAYC OUT.json [--rounds N]

The runtime is read at compile time, so OLD_MAYC must sit beside the old
runtime sidecars. Rounds are interleaved (each round runs every binary once,
in alternating order) so that load drift on a shared machine affects before
and after alike. Each sample records wall time and the child's user+system
CPU time; the report quotes medians.
"""
import argparse, hashlib, json, os, platform, statistics, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BOTH = ["int_keys_20k", "str_keys", "str_floor", "small_maps"]
# The old runtime scans these linearly and needs hours, so only time them after.
AFTER_ONLY = ["int_keys", "grid_keys"]


def sample(binary):
    start = time.perf_counter()
    proc = subprocess.Popen([binary], stdout=subprocess.PIPE)
    out = proc.stdout.read()
    _, status, usage = os.wait4(proc.pid, 0)
    wall = time.perf_counter() - start
    if status != 0:
        sys.exit(f"{binary} exited with status {status}")
    return out, wall, usage.ru_utime + usage.ru_stime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("out")
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as work:
        binaries = {}
        for name in BOTH + AFTER_ONLY:
            sides = [("after", args.new)] + ([("before", args.old)] if name in BOTH else [])
            for side, compiler in sides:
                path = Path(work) / f"{name}.{side}"
                subprocess.run([compiler, str(HERE / f"{name}.may"), "-o", str(path)], check=True)
                binaries[(name, side)] = path
        outputs, samples = {}, {key: [] for key in binaries}
        keys = list(binaries)
        for key in keys:  # warm-up and output check
            outputs[key] = sample(binaries[key])[0]
        for name in BOTH:
            if outputs[(name, "before")] != outputs[(name, "after")]:
                sys.exit(f"output differs: {name}")
        for round_index in range(args.rounds):
            order = keys if round_index % 2 == 0 else keys[::-1]
            for key in order:
                _, wall, cpu = sample(binaries[key])
                samples[key].append({"wall_s": wall, "cpu_s": cpu})
    results = []
    for (name, side), runs in samples.items():
        results.append({
            "workload": name, "side": side, "samples": runs,
            "median_wall_ms": round(statistics.median(r["wall_s"] for r in runs) * 1000, 2),
            "median_cpu_ms": round(statistics.median(r["cpu_s"] for r in runs) * 1000, 2),
            "output": outputs[(name, side)].decode().strip(),
        })
    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": git("rev-parse", "HEAD"),
        "status": git("status", "--short", "--", "compiler", "stdlib"),
        "compilers": {side: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                      for side, path in (("before", args.old), ("after", args.new))},
        "runtime_sha256": {side: hashlib.sha256((Path(path).resolve().parent / "runtime/fat.may").read_bytes()).hexdigest()
                           for side, path in (("before", args.old), ("after", args.new))},
        "uname": " ".join(platform.uname()),
        "loadavg": os.getloadavg(),
        "rounds": args.rounds,
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    for r in results:
        print(f"{r['workload']:>13} {r['side']:>6}  wall {r['median_wall_ms']:>9} ms  cpu {r['median_cpu_ms']:>9} ms")


if __name__ == "__main__":
    main()
