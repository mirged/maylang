# GC workloads

The workload suite of the [MOSAIC GC roadmap](../../../../docs/design/MOSAIC_GC.md)
(milestone M0): programs that exercise the collector differently, and a
runner, [`../gc_workloads.py`](../gc_workloads.py), that builds each one, runs it
with `MAYC_GC_STATS=1` and records time, GC share and pauses. The current
baseline is [gc-baseline.md](../backend/gc-baseline.md).

| Workload | Source | What it stresses |
| --- | --- | --- |
| `selfhost` | `compiler/mayc/main.may` compiled by a fresh `mayc` | the largest real heap: a live set growing to ~200 MiB, 300+ global roots |
| `trees`, `hashmap`, `strings`, `nbody` | [`../backend/xlang/may/`](../backend/xlang/may/) | short-lived records with one long-lived tree; a growing map; short strings; struct updates |
| `maylsp` | `tools/maylsp/main.may`, replayed session | a long-lived index with per-request garbage: `strict.may` opened, then 20 incremental edits with hover and completion, and pull diagnostics and document symbols every tenth edit |
| `random_graph` | [`random_graph.may`](random_graph.may) | adversarial: a uniformly random graph, so lifetime is unrelated to allocation site or time |
| `cache_mix` | [`cache_mix.may`](cache_mix.may) | adversarial: a long-lived map cache that keeps receiving young values, mixed with temporaries |
| `cross_mutation` | [`cross_mutation.may`](cross_mutation.may) | adversarial: groups that die together but receive cross-group pointers to young objects on every step |

The adversarial programs are deterministic: the runner checks their checksums
(and those of the cross-language programs), which were cross-checked against
straight Python ports, so a collector that frees or corrupts a live object
fails the run instead of skewing the numbers. The `maylsp` run must answer
every request. Mayboard's snapshot mode, which the roadmap also names, is left
out: it renders one frame, and a program with C externs starts and exits
through libc, so it never reaches the runtime's exit report.

```sh
python3 compiler/mayc/tests/gc_workloads.py --self-test
python3 compiler/mayc/tests/gc_workloads.py --runs 5 --cpu 6 --json /tmp/gc.json --markdown /tmp/gc.md
python3 compiler/mayc/tests/gc_workloads.py --only trees cache_mix \
    --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288
```

`--self-test` runs every workload except `selfhost` and `maylsp`
once and checks outputs and summaries; it takes a few seconds. A full run
repeats each workload (`--runs`, default 5), optionally pinned to one CPU, and
reports medians of wall time, CPU time and pause statistics, the GC share
(total pause over wall time), and the counts, which must not vary between
runs. `--env` passes the collector's policy overrides, so the workloads that
never collect at the default heap can be measured under a smaller one. The
JSON report records the compiler and sidecar hashes, the commit, the host and
every sample. Timings do not gate CI.
