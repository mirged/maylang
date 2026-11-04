# GC baseline — MOSAIC M0

Status: the M0 measurement baseline of the [MOSAIC GC roadmap](../../../../docs/design/MOSAIC_GC.md).
It records what the current collector (conservative, non-moving mark-sweep,
[GC.md](../../../../docs/internals/GC.md)) costs on the
[GC workload suite](../gc_workloads/README.md), under the default policy and
under the small-heap policy of the [GC policy report](gc-policy.md)
(`MAYC_GC_MIN=8388608 MAYC_GC_MARGIN=524288`).

## Instruments

- `MAYC_GC_STATS=1` now also reports `objects` (allocations), cumulative
  `marked` bytes and `marked_objects`, heap bytes `swept`, and the
  nearest-rank `pause_p50_ns`, `pause_p99_ns` and `pause_max_ns`. It reports
  at a normal exit and at `exit()` too, so the compiler compiling itself (which
  writes nothing) is measurable. `gc.py` checks the counters against an
  independent heap walk and checks the exit reports.
- Code layout: the counters live on the statistics scratch page, not in new
  globals (every runtime global is registered as a root by the start-up code,
  so a new one moves every program). User code and the first ~30 runtime
  functions keep their addresses; later runtime functions move because new
  helpers join the emission order. Paired pinned runs of the previous and new
  runtime (`stack_retention.py --pair`, CPU time, interleaved): fib +0.08%
  (120 pairs, 63/57 wins), collatz -0.12%, sieve -0.22%, hashmap -0.28%,
  strings -0.11%, mandelbrot -0.15%, n-body +0.03% (60 pairs each), trees
  -0.56% (30 pairs). The normal-exit report replaces the 9-byte exit sequence
  of `_start` with a jump and a nop of the same size, so `_start` and every
  function keep their addresses; only `_start`'s bytes and a stub in the end
  padding differ.
- The live object count is read from the allocation-start table after the
  pause clock stops, so stats-mode wall time includes some bookkeeping that the
  pause excludes.

## Method

`python3 compiler/mayc/tests/gc_workloads.py --runs 5 --cpu 6 --json ...`, then
again with `--env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288`. Host: 13th
Gen Intel Core i5-13500H, Linux 6.12; compiler from 2def37e plus this change
(working tree, identity hashes in the JSON). Medians of 5 runs; counts are
identical across runs except maylsp, whose worker scheduling makes them vary
slightly. Raw samples: [gc-baseline-default.json](gc-baseline-default.json),
[gc-baseline-small.json](gc-baseline-small.json).

**Caveat:** other benchmarks from another worktree were running on the host
(pinned to other CPUs) during the default-policy run; its short workloads
(hashmap, strings, nbody, random_graph) took up to twice their earlier pinned
times. GC shares, pause distributions and counts are the useful part; absolute
times there are upper bounds.

## Default policy

| Workload | wall (s) | GC pause (s) | GC share | collections | p50 / p99 / max pause (ms) | allocated (MiB / objects) | marked per collection (objects) | peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |
| selfhost | 2.554 | 0.754 | 29.5% | 7 | 89.1 / 188.5 / 188.5 | 908.8 / 8,439,714 | 593,357 | 468.2 |
| trees | 0.928 | 0.305 | 32.7% | 11 | 25.7 / 44.6 / 44.6 | 1798.3 / 14,723,762 | 160,580 | 236.0 |
| hashmap | 0.201 | 0.000 | 0.0% | 0 | - | 62.5 / 1,200,037 | - | 72.0 |
| strings | 0.100 | 0.000 | 0.0% | 0 | - | 59.5 / 900,025 | - | 66.0 |
| nbody | 0.164 | 0.000 | 0.0% | 0 | - | 1.0 / 704 | - | 12.1 |
| maylsp | 10.152 | 1.190 | 11.7% | 10 | 103.0 / 276.2 / 276.2 | ~22.0M objects | - | 319.3 |
| random_graph | 2.344 | 0.697 | 29.8% | 2 | 252.2 / 447.6 / 447.6 | 316.9 / 4,897,563 | 1,349,868 | 272.0 |
| cache_mix | 2.653 | 0.158 | 5.8% | 4 | 39.1 / 44.8 / 44.8 | 568.5 / 14,117,081 | 95,713 | 182.0 |
| cross_mutation | 2.220 | 0.317 | 14.3% | 4 | 79.3 / 82.9 / 82.9 | 576.3 / 3,198,828 | 154,105 | 174.0 |

## Small-heap policy (8 MiB floor, 512 KiB margin)

| Workload | wall (s) | GC pause (s) | GC share | collections | p50 / p99 / max pause (ms) | allocated (MiB / objects) | marked per collection (objects) | peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |
| selfhost | 2.881 | 0.915 | 31.7% | 14 | 45.9 / 191.6 / 191.6 | 892.4 / 8,316,790 | 364,498 | 462.3 |
| trees | 1.659 | 0.990 | 60.0% | 60 | 14.7 / 32.4 / 32.4 | 1798.3 / 14,723,762 | 153,025 | 100.0 |
| hashmap | 0.140 | 0.031 | 22.3% | 7 | 3.5 / 10.2 / 10.2 | 62.5 / 1,200,037 | 109,901 | 52.0 |
| strings | 0.145 | 0.035 | 24.3% | 7 | 3.8 / 8.7 / 8.7 | 59.5 / 900,025 | 152,300 | 44.5 |
| nbody | 0.078 | 0.000 | 0.0% | 0 | - | 1.0 / 704 | - | 12.3 |
| maylsp | 16.909 | 6.673 | 36.2% | 95-108 | 66.7 / 138.9 / 138.9 | ~22.8M objects | - | 115.3 |
| random_graph | 3.329 | 1.334 | 39.0% | 7 | 103.6 / 599.9 / 599.9 | 316.9 / 4,897,563 | 726,861 | 254.0 |
| cache_mix | 5.019 | 0.557 | 11.2% | 39 | 15.6 / 22.0 / 22.0 | 604.2 / 14,584,689 | 88,900 | 42.0 |
| cross_mutation | 3.662 | 1.639 | 44.6% | 24 | 77.7 / 89.5 / 89.5 | 576.2 / 3,198,825 | 139,263 | 68.0 |

## Reading

- On the allocation-heavy real workloads the collector already costs about a
  third of run time at the default heap (self-compile 29.5%, trees 32.7%), and
  pauses are long: the self-compile's worst pause is 189 ms because every
  collection marks a growing ~200 MiB live set and sweeps the whole heap.
- The small-heap policy trades memory for time as the policy report found:
  trees 60% GC share at 100 MiB instead of 33% at 236 MiB; maylsp 36% at
  115 MiB instead of 12% at 319 MiB.
- hashmap, strings and nbody never collect at the default heap.
