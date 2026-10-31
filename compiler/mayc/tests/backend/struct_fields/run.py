#!/usr/bin/env python3
"""Before/after struct field measurements for #98 (see ../struct-fields.md).

Usage: run.py OLD_MAYC NEW_MAYC OUT.json [--rounds N] [--self-compile]

Every workload beside this script is built by both compilers. The runtime
is read at compile time, so OLD_MAYC must sit beside its own runtime
sidecars. Rounds are interleaved (each runs every binary once, alternating
the order) so load drift on a shared machine affects before and after alike.
Each sample records wall time and the child's user+system CPU time, and
outputs must match. --self-compile also times each compiler compiling
compiler/mayc/main.may.
"""
import argparse, hashlib, json, os, platform, statistics, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def sample(command):
    start = time.perf_counter()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE)
    out = proc.stdout.read()
    _, status, usage = os.wait4(proc.pid, 0)
    wall = time.perf_counter() - start
    if status != 0:
        sys.exit(f"{command[0]} exited with status {status}")
    return out, wall, usage.ru_utime + usage.ru_stime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("out")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--self-compile", action="store_true")
    args = parser.parse_args()
    compilers = {"before": args.old, "after": args.new}
    with tempfile.TemporaryDirectory() as work:
        commands = {}
        for source in sorted(HERE.glob("*.may")):
            for side, compiler in compilers.items():
                binary = Path(work) / f"{source.stem}.{side}"
                subprocess.run([compiler, str(source), "-o", str(binary)], check=True)
                commands[(source.stem, side)] = [str(binary)]
        if args.self_compile:
            for side, compiler in compilers.items():
                commands[("self_compile", side)] = [compiler, str(ROOT / "compiler/mayc/main.may"),
                                                    "-o", str(Path(work) / f"selfhost.{side}")]
        keys = list(commands)
        outputs = {key: sample(commands[key])[0] for key in keys}  # warm-up
        for name in {name for name, _ in keys}:
            if outputs[(name, "before")] != outputs[(name, "after")]:
                sys.exit(f"output differs: {name}")
        samples = {key: [] for key in keys}
        for round_index in range(args.rounds):
            for key in keys if round_index % 2 == 0 else keys[::-1]:
                _, wall, cpu = sample(commands[key])
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
        print(f"{r['workload']:>13} {r['side']:>6}  wall {r['median_wall_ms']:>9} ms  cpu {r['median_cpu_ms']:>9} ms")


if __name__ == "__main__":
    main()
