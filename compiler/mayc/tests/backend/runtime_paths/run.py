#!/usr/bin/env python3
"""Before/after runtime-library measurements (see ../runtime-audit.md).

Usage: run.py OLD_MAYC NEW_MAYC OUT.json [--runs N] [--only a,b]

Every workload beside this script is built by both compilers, and both
builds must print the same output. The runtime is read at compile time, so
OLD_MAYC must sit beside its own `native.may`, `prelude.may` and `runtime/`
copies (see the report for how the snapshot is made).

Timing uses hyperfine: each workload's two binaries go into one hyperfine
call, which warms up once and then times `--runs` executions of each. The
call is repeated in the opposite order and all samples are pooled, so load
drift on a shared machine affects before and after alike; the table quotes
the pooled median. Peak RSS is the child's `ru_maxrss` from one extra run.
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
SIDES = ("before", "after")


def sample(command):
    """Run once: stdout, and the child's peak RSS in KiB."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE)
    out = proc.stdout.read()
    proc.stdout.close()
    _, status, usage = os.wait4(proc.pid, 0)
    proc.returncode = 0
    if status != 0:
        sys.exit(f"{command[0]} exited with status {status}")
    return out, usage.ru_maxrss


def hyperfine(commands, runs, name):
    """Pooled timings for {side: command} from two opposite-order calls."""
    with tempfile.TemporaryDirectory() as work:
        times = {side: [] for side in commands}
        for order in (list(commands), list(commands)[::-1]):
            export = Path(work) / "hf.json"
            argv = ["hyperfine", "--warmup", "1", "--runs", str(runs), "--export-json", str(export)]
            for side in order:
                argv += ["--command-name", f"{name}.{side}", commands[side]]
            result = subprocess.run(argv, capture_output=True, text=True)
            if result.returncode != 0:
                sys.exit("hyperfine failed:\n" + result.stdout + result.stderr)
            for entry in json.loads(export.read_text())["results"]:
                side = entry["command"].rsplit(".", 1)[-1]
                times[side].extend(entry["times"])
    return times


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("out")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    compilers = {"before": args.old, "after": args.new}
    sources = sorted(HERE.glob("*.may"))
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        sources = [source for source in sources if source.stem in wanted]

    with tempfile.TemporaryDirectory() as work:
        commands = {}
        for source in sources:
            for side, compiler in compilers.items():
                binary = Path(work) / f"{source.stem}.{side}"
                build = subprocess.run([compiler, str(source), "-o", str(binary)],
                                       capture_output=True, text=True)
                if build.returncode != 0:
                    sys.exit(f"build failed: {source.name} ({side})\n{build.stdout}{build.stderr}")
                commands[(source.stem, side)] = str(binary)
        outputs, rss = {}, {}
        for key, command in commands.items():
            outputs[key], rss[key] = sample([command])
        for source in sources:
            if outputs[(source.stem, "before")] != outputs[(source.stem, "after")]:
                sys.exit(f"output differs: {source.stem}")

        results = []
        for source in sources:
            pooled = hyperfine({side: commands[(source.stem, side)] for side in SIDES},
                               args.runs, source.stem)
            for side in SIDES:
                values = pooled[side]
                results.append({
                    "workload": source.stem,
                    "side": side,
                    "samples_ms": [round(value * 1000, 3) for value in values],
                    "median_ms": round(statistics.median(values) * 1000, 2),
                    "min_ms": round(min(values) * 1000, 2),
                    "rss_mib": round(rss[(source.stem, side)] / 1024, 1),
                    "output": outputs[(source.stem, side)].decode(errors="replace").strip(),
                })

    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    def runtime_hash(path):
        return hashlib.sha256((Path(path).resolve().parent / "runtime/fat.may").read_bytes()).hexdigest()

    report = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "revision": git("rev-parse", "HEAD"),
        "status": git("status", "--short", "--", "compiler", "stdlib"),
        "compilers": {side: str(Path(path).resolve()) for side, path in compilers.items()},
        "runtime_fat_sha256": {side: runtime_hash(path) for side, path in compilers.items()},
        "uname": " ".join(platform.uname()),
        "loadavg": os.getloadavg(),
        "runs": args.runs,
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    for row in results:
        print(f"{row['workload']:>14} {row['side']:>6}  median {row['median_ms']:>9.2f} ms"
              f"  min {row['min_ms']:>9.2f} ms  rss {row['rss_mib']:>7.1f} MiB")


if __name__ == "__main__":
    main()
