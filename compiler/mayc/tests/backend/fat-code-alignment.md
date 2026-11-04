# Fat code alignment — issue #131, measured not merged

The [roadmap](../../../../docs/design/PERFORMANCE_ROADMAP.md#phase-4-ir-optimizer)
lists the raw-backend wins that are still missing for fat code. Code alignment
is one: the raw backend already aligns function bodies and loop heads
([#83](raw-code-alignment.md)) and `--no-code-align` turns it off, but fat-value
functions emitted by `x86_64_fat.may` were not aligned at all. That means a FAT
program's hot loops move whenever a function earlier in the image changes size.

The change was implemented, measured against the unaligned compiler, and
reverted: it does not move the roadmap workloads, and the full variant is a
consistent small regression. This page and its two raw sample files are the
deliverable.

## What was implemented

The raw backend's behaviour was mirrored exactly, using its constants and its
loop-head definition (`x86_64.may`):

- function bodies start on a 16-byte boundary (`X86_FUNCTION_ALIGN`), padding
  after the previous body's `ret` so the entry is reachable but the padding is
  not executed;
- loop heads - a label a later branch in the same body targets, computed with
  the raw backend's `x86_loop_heads` - are padded to 16 bytes
  (`X86_LOOP_ALIGN`) when the padding is at most 15 bytes
  (`X86_LOOP_SKIP`), using the raw backend's multi-byte NOP forms;
- the public entry label of a versioned/register fat function, the body labels
  the version dispatcher jumps to, and the top-level block are covered;
- everything is gated by the existing `--no-code-align` flag through
  `backend_disable_code_alignment()`, which zeroes the same globals, and
  `--no-opt` behaviour is untouched.

Two variants were built and measured separately: **function + loop** alignment
(the full port) and **loop heads only** (the raw backend's layout experiment
found function alignment alone did not help while loop alignment did).

Scope check: with `--no-code-align` the prototype compiler and the unaligned
compiler produce **byte-identical binaries** for all eight suite programs, so
the only difference the prototype can make is padding, and the flag gives a
byte-exact A/B. All eight programs also printed identical output in the
aligned, unaligned and old builds.

## Measurements

Intel i5-13500H, Linux 6.12, full runtime, identical sidecar hashes on both
sides. The host was shared (load average 2.7-3.6), so the metric is child CPU
time (`user+sys`) of whole-process runs, interleaved: each round runs every
command once per side, alternating the order, 25 rounds after one warm-up;
every child was pinned with `taskset -c 4`. "Change" is after-vs-before (positive
is slower); "paired" is the median of the per-round before-minus-after
difference, which cancels load drift (positive means the candidate was faster);
"wins" counts rounds the candidate ran faster. Every program printed identical
output. Harness: [run.py](fat-code-alignment/run.py).

Compilers: before
`c161b20f80a792a01bc0bcf536b43967c456a159b3966700c90b8a20e3cf71ba` (committed
tree); after (function + loop)
`e0204a0f8ea0e7affeaf2a82a23e7fb5fe6b7ce9263540be591fb3716ca0d85b`, after
(loop only) `054318c7ca5fbbc7f0d2e8c735041a80d41b8ce483c476a3a40d8f7457dfcd6e`.

### Variant A — function bodies and loop heads

Raw samples: [fat-code-alignment-performance.json](fat-code-alignment/fat-code-alignment-performance.json).

| Workload | before, ms | after, ms | change | paired | wins | minima |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fib | 60.3 | 60.1 | -0.2% | -0.3% | 7/25 | 57 / 57 |
| collatz | 43.4 | 43.3 | -0.1% | -0.3% | 10/25 | 42 / 42 |
| sieve | 204.8 | 209.8 | **+2.5%** | -1.9% | 5/25 | 190 / 191 |
| hashmap | 94.8 | 96.8 | +2.1% | -1.9% | 5/25 | 83 / 85 |
| strings | 47.0 | 47.8 | +1.7% | -4.1% | **2/25** | 42 / 44 |
| mandelbrot | 45.0 | 45.6 | +1.5% | -1.6% | 4/25 | 44 / 45 |
| n-body | 87.3 | 87.8 | +0.7% | -0.5% | 10/25 | 81 / 82 |
| binary trees | 920.9 | 929.8 | +1.0% | -0.3% | 11/25 | 811 / 816 |
| compiler self-compile | 2584.1 | 2603.9 | +0.8% | -0.3% | 10/25 | 2356 / 2366 |
| `features.may` compile | 115.2 | 113.5 | -1.5% | -0.0% | 12/25 | 101 / 101 |

Nothing moves positively. Seven of ten side medians are slower, the paired
median is negative (slower) on every workload except the flat `features.may`
compile, the win count is at or below half on eight of ten, and the minimum is
equal or worse on every workload with a signal (strings 2/25 with a 2 ms worse
minimum, sieve 5/25). This is a small, consistent regression, not noise.

### Variant B — loop heads only

Raw samples: [fat-loop-alignment-performance.json](fat-code-alignment/fat-loop-alignment-performance.json).

| Workload | before, ms | after, ms | change | paired | wins | minima |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fib | 60.0 | 60.3 | +0.6% | -0.6% | 5/25 | 58 / 59 |
| collatz | 44.0 | 44.0 | -0.0% | -0.6% | 11/25 | 42 / 42 |
| sieve | 205.8 | 207.5 | +0.8% | -1.3% | 6/25 | 198 / 201 |
| hashmap | 93.8 | **92.9** | **-1.0%** | +1.2% | **19/25** | 88 / 86 |
| strings | 46.9 | 47.5 | +1.2% | -1.5% | 7/25 | 44 / 45 |
| mandelbrot | 45.5 | 45.4 | -0.1% | -0.1% | 12/25 | 44 / 44 |
| n-body | 87.6 | 87.9 | +0.3% | -0.2% | 10/25 | 85 / 86 |
| binary trees | 914.6 | 922.5 | +0.9% | +0.2% | 14/25 | 844 / 842 |
| compiler self-compile | 2577.0 | 2576.1 | -0.0% | +0.2% | 16/25 | 2358 / 2358 |
| `features.may` compile | 114.6 | 116.4 | +1.5% | +0.5% | 13/25 | 102 / 102 |

Loop alignment is the closer call: hashmap is consistently faster (-1.0% side,
+1.2% paired, 19/25 rounds, 2 ms better minimum), and self-compile and mandelbrot
are flat. But strings (7/25, +1.2% side, worse minimum), sieve (6/25), fib
(5/25) and the `features.may` compile (13/25, +1.5% side) are consistently
slower, and n-body/trees/collatz are flat. The net is a wash with regressions,
not a win.

## Why it does not transfer from the raw backend

The raw layout experiment measured a real 3-5% placement sensitivity on
Collatz- and pointer-chase-like kernels, and alignment halved that spread. The
fat suite does not show such sensitivity: the fat workload loops are longer and
dominated by type-word checks and memory traffic (the check-elimination report
measured the same effect), and the raw experiment already showed that function
alignment alone does not help. Adding 16-byte padding in the fat backend buys
no measurable speed and costs a little, most plausibly I-cache/padding and the
removal of the old accidental layout. A future attempt should start from a
layout-sensitivity experiment for a fat kernel (the raw `raw_layout.py` method
with `--cycles`), not from the raw result.

Decision: no variant passes the bar ("no workload regresses beyond noise and
something moves"), so the code was reverted. The fat backend, `--no-code-align`
and the raw alignment path are unchanged; this page and the raw samples record
the negative and the harness for a future attempt.

## Reproduce

The prototype was a small edit to `compiler/mayc/src/backend/x86_64_fat.may`
(mirroring the raw calls to `x86_align_code` at body entries and at
`loopHeads`-carrying labels in `fat_ir`); it is not in the tree. With such a
build:

```
python3 compiler/mayc/tests/backend/fat-code-alignment/run.py OLD_MAYC NEW_MAYC out.json --rounds 25 --self-compile --cpu 4
python3 compiler/mayc/tests/backend/fat-code-alignment/run.py OLD_MAYC NEW_MAYC out.json --rounds 25 --cpu 4
```

The first form includes the eight xlang workloads, the compiler self-compile
and the `features.may` compile; the second only the workloads. Check
`--no-code-align` byte-identity between the two compilers before trusting a
measurement: it isolates alignment as the only difference.
