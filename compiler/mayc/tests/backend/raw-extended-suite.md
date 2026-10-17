# Extended RAW benchmark suite

The six issue #76 kernels guided the RAW backend work, so they say little about
code they were not tuned for. This suite adds eleven different workloads in
[`raw_suite.may`](raw_suite.may), with the same algorithms and inputs in
[`raw_suite.c`](raw_suite.c):

| Workload | Exercises |
|---|---|
| Sieve | strided byte stores, nested loops, a data-dependent guard |
| Matrix multiply | 96×96 `int64` triple loop, scaled 2-D indexing |
| Recursive fib | `fib(27)`: call/return overhead |
| Insertion sort | 4,000 values; `and` loop condition with a load, shifting stores |
| GCD grid | Euclid over 300×300 pairs: variable-divisor `%` |
| Hash | 4 MiB of multiply–add–`% 2^32` steps on one dependency chain |
| Binary search | 150,000 lower-bound searches over 65,536 sorted values |
| Mandelbrot | 160×120, 64 iterations in 12-bit fixed point; signed division, `break` |
| N-queens | 10-queens backtracking: recursion, byte arrays, three-way `and` |
| Dot product | 20 passes over two 131,072-element arrays |
| Knapsack | 0/1 DP, 200 items × capacity 10,000; conditional store |

Maylang has no bitwise operators, so the kernels use only arithmetic,
comparisons, loads and stores. `raw_codegen.py` checks all eleven checksums for
the current compiler and the GCC build.

## Measurements

[Complete report](raw-extended-suite-performance.json), 2026-10-17 UTC, Intel
Core i5-13500H, GCC 14.2.0, pinned performance CPU 2, host not isolated. Each
executable has 100 interleaved samples, 10 warmups and five hardware-counter
samples; every run matches all eleven checksums. Compilers: `f551c97` (before
any #76 work; it reports `0.13.0`), the 0.13.101 release `c3d3ea8`, and
0.13.102 `bdfae89`.

Median per-workload time in ms:

| Workload | f551c97 | 0.13.101 | 0.13.102 | GCC `-O3` | GCC no-vec | vs 0.13.101 | vs f551c97 | ÷ GCC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sieve | 17.561 | 7.911 | 4.506 | 3.052 | 3.156 | −43.0% | −74.3% | 1.48× |
| Matrix multiply | 4.484 | 1.317 | 0.916 | 0.334 | 0.297 | −30.4% | −79.6% | 2.74× |
| Recursive fib | 2.495 | 1.202 | 1.190 | 0.227 | 0.220 | −1.0% | −52.3% | 5.23× |
| Insertion sort | 20.249 | 7.482 | 4.682 | 0.887 | 1.074 | −37.4% | −76.9% | 5.28× |
| GCD grid | 2.205 | 1.720 | 1.711 | 1.700 | 1.679 | −0.5% | −22.4% | 1.01× |
| Hash | 25.807 | 24.541 | 24.234 | 8.372 | 7.732 | −1.3% | −6.1% | 2.89× |
| Binary search | 20.308 | 14.919 | 13.772 | 12.042 | 12.603 | −7.7% | −32.2% | 1.14× |
| Mandelbrot | 2.526 | 1.047 | 1.055 | 0.806 | 0.794 | +0.7% | −58.3% | 1.31× |
| N-queens | 2.973 | 2.328 | 2.215 | 1.134 | 1.160 | −4.9% | −25.5% | 1.95× |
| Dot product | 10.326 | 3.733 | 2.197 | 0.678 | 1.329 | −41.1% | −78.7% | 3.24× |
| Knapsack | 10.206 | 3.036 | 1.669 | 0.527 | 0.530 | −45.0% | −83.6% | 3.17× |
| **Sum of medians** | **119.139** | **69.237** | **58.147** | **29.759** | **30.573** | **−16.0%** | **−51.2%** | **1.95×** |

Per-workload dispersion for 0.13.102 is 1.8–8.0% of the median, except dot
product (13.0%) and knapsack (12.5%); treat differences below that as noise.
Mandelbrot's +0.7% and GCD's −0.5% are within it.

Whole executables, five-run median user-mode counters:

| Executable | End-to-end median | Stdev | Instructions | Cycles | IPC | Static instructions |
|---|---:|---:|---:|---:|---:|---:|
| f551c97 | 120.529 ms | 3.706 ms | 2,549,844,192 | 560,116,569 | 4.55 | 5,997 |
| 0.13.101 | 70.786 ms | 2.166 ms | 779,841,689 | 321,780,618 | 2.42 | 2,345 |
| 0.13.102 | 59.807 ms | 1.410 ms | 565,603,184 | 274,134,448 | 2.06 | 2,151 |
| GCC `-O3` | 31.686 ms | 0.998 ms | 188,866,539 | 139,238,505 | 1.36 | 1,873 |
| GCC no-vec | 32.422 ms | 1.374 ms | 221,708,599 | 143,303,461 | 1.55 | 1,668 |

End-to-end times include process launch. Branch misses are about 1.64 million
for every executable, dominated by binary search.

## Findings

The #78/#79 gains carry over to code they were not written for: the memory
loops (sieve, sort, dot product, knapsack, matrix multiply) are 30–45% faster
than 0.13.101. Recursion, division and the hash chain are essentially
unchanged, and GCD and binary search are already near GCC.

The largest remaining gaps, from the disassembly in the report artifacts:

- **Hash (2.89×).** `% 4294967296` is a power of two outside imm32, so it
  falls back to `cqo; idiv` on the loop-carried chain. GCC uses a
  shift/add/subtract sequence. The power-of-two remainder lowering is limited
  to imm32 divisors.
- **Insertion sort (5.28×).** `while j >= 0 and load64(...) > key` produces a
  0/1 value per operand with `setcc`, frame stores, reloads and `test`
  instead of fused compare-branches. The array parameter and `key` also stay
  in frame slots, reloaded every iteration.
- **Recursive fib (5.23×).** GCC converts one of the two calls into a loop
  and drops the frame; RAW keeps both calls and a full prologue.
- **Dot product and matrix multiply (2.7–3.2×).** GCC vectorizes the dot
  product (no-vec: 1.329 ms) and unrolls both; RAW does one scalar step per
  iteration.

Issues #84–#87 address the first four; see the
[follow-up report](raw-call-gaps.md).

[`raw_performance.py --suite extended`](../raw_performance.py) reproduces the
measurement with the same options as the core suite; pass saved compilers with
`--baseline-compiler`.
