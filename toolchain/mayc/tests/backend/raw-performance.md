# RAW x86-64 operand lowering — issue #76, first pass

The first pass uses allocated registers and spill homes directly for raw binary
operations, loads store values directly into `rcx`, fuses branch-only signed
comparisons, skips copies with no readers, and selects compact immediate moves.
Operand evaluation still happens in IR order. Register allocation, private homes
for loop-carried/multiple-definition values, GC rooting, and dynamic arithmetic
fallbacks retain their existing rules. Compact moves preserve flags and select
zero-extension, sign-extension, or a full 64-bit immediate according to the value.

This addresses P0–P2 and the immediate-selection part of P3. Non-power-of-two
constant division, general copy propagation/dead-code elimination, address
selection, and CFG-aware allocation remain follow-up work. Issue #76 should
remain open for those improvements.

The subsequent [signed constant-division pass](raw-constant-division.md)
implements non-power-of-two literal division and records a fresh, interleaved
comparison of the original compiler, this first pass, and the combined changes.

The latest [bounded scalar arithmetic report](raw-recurrences.md) records the
complete branch at 24.694 ms versus 44.291 ms for the original compiler, with
100 interleaved runs, all checksums matching, and remaining workload regressions
reported alongside the gains.

## Reproduce

Save the old compiler with its runtime sidecars before rebuilding. Run from the
repository root (choose a performance CPU allowed by the current affinity):

```sh
sh toolchain/rust/build.sh
python3 toolchain/mayc/tests/raw_codegen.py --compiler toolchain/mayc/mayc_new
python3 toolchain/mayc/tests/raw_performance.py \
  --compiler toolchain/mayc/mayc_new \
  --baseline-compiler /path/to/baseline/mayc \
  --baseline-revision f551c97 \
  --cpu 2 --runs 50 --warmup 10 --perf --output /tmp/raw-performance.json
```

The runner checks all six checksums on every run, compiles both GCC variants,
rotates execution order, and records all timing samples, five separate perf
samples per executable, compiler/source/binary hashes, revision, GCC version,
kernel, CPU model, affinity, static instruction counts, and counter coverage.
Full disassembly and raw perf CSV logs are written beside the requested JSON.
The compiler is invoked before timing. The default run requires neither perf nor
CPU pinning. There are no machine-specific speed thresholds in verification.

## Recorded comparison

[Machine-readable report](raw-performance.json): 2026-10-16 UTC / 2026-10-17
Vilnius, Debian Linux x86-64, Intel Core i5-13500H, performance CPU 2, GCC
14.2.0, baseline `f551c97`. The updated compiler is identified by its binary and
source hashes because it was measured before committing the change.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Baseline RAW | 44.220 ms | 1.050 ms |
| Updated RAW | 36.975 ms | 1.080 ms |
| GCC `-O3 -march=native` | 17.876 ms | 0.569 ms |
| GCC, also `-fno-tree-vectorize` | 17.245 ms | 0.496 ms |

| Workload | Baseline median | Updated median | Checksum (both and C) |
|---|---:|---:|---:|
| PRNG | 4.757 ms | 4.765 ms | 1263606197 |
| Collatz | 11.017 ms | 8.077 ms | 2864311 |
| Byte histogram | 1.756 ms | 1.118 ms | 33685504 |
| Cellular automaton | 6.463 ms | 4.122 ms | 44849 |
| Pointer chase | 6.651 ms | 6.560 ms | 578415528 |
| Random walk | 12.059 ms | 10.986 ms | 1997581997722 |

Five-run median performance-core user-mode counters:

| Counter | Baseline | Updated | Change |
|---|---:|---:|---:|
| Instructions | 778,107,645 | 503,793,934 | -35.3% |
| Cycles | 200,179,890 | 165,868,069 | -17.1% |
| Branches | 25,973,947 | 26,053,505 | +0.3% |
| Branch misses | 1,196,155 | 1,223,894 | +2.3% |

The combined change reduces median end-to-end time by 16.4% (1.20× speedup).
Workload times exclude output; end-to-end samples include process launch,
`taskset`, and Python output capture. The host was pinned but not isolated;
frequency, sibling activity, sampling noise, and PMU coverage affect these
numbers. GCC scalar disables only tree vectorization. These measurements do
not attribute a gain to an individual optimization or establish SIMD's impact.
PRNG is essentially unchanged, consistent with its remaining `idiv` bottleneck.

Whole-executable static counts drop from 2,980 to 2,321 instructions, `push`
from 245 to 112, and `pop` from 179 to 48. Calls, syscalls, and prologues still
use the stack. Static counts are distinct from dynamic instruction counts.

Representative PRNG multiply, before:

```asm
mov    rax,r14
push   rax
mov    rax,r15
mov    rcx,rax
pop    rax
imul   rax,rcx
```

After:

```asm
mov    rax,r14
imul   rax,r15
```

Representative automaton loop condition, before:

```asm
mov    rax,r15
push   rax
mov    rax,r14
mov    rcx,rax
pop    rax
cmp    rax,rcx
setl   al
movzx  eax,al
mov    QWORD PTR [rbp-0x10],rax
mov    rax,QWORD PTR [rbp-0x10]
test   rax,rax
je     done
```

After:

```asm
mov    rax,r15
cmp    rax,r14
jge    done
```

## Correctness coverage

`raw_codegen.py` checks register and spilled operands, nested expressions,
store widths, pointer/byte loads, side-effect order, calls and syscall clobbers,
loop backedges, swapped values, signed comparisons in both directions, Boolean
values that remain observable, and short-circuit evaluation. It constructs full
64-bit inputs for a deterministic signed division/remainder oracle, including
negative divisors, boundary values, and existing division traps. Raw addition,
subtraction, and multiplication retain hardware 64-bit wrapping. Raw division
by zero and `INT64_MIN / -1` (including the remainder instruction) retain the
x86 `SIGFPE` trap. The encoder/IR
fixture checks immediate boundaries, both branch polarities, multiple users,
and multiple definitions. It also executes the six benchmark workloads three
times and compares their checksums with the C counterpart.

Existing backend, allocator/forced-GC, core-runtime, LLVM, and source-bootstrap
convergence checks pass. The broad native verification run reports 114 passes
and one environment failure: `examples/ui_showcase.may` cannot load
`libmayui.so`. Building the existing UI library and rerunning that same binary
with `LD_LIBRARY_PATH` set passes both light and dark headless snapshots.
Cross-architecture format checks run, but Unicorn is not installed on this
host, so cross-architecture execution is skipped.
