# Bounded RAW scalar arithmetic — issue #76, eleventh pass

The x86 backend proves a nonnegative bound for a literal-initialized local when
every write has the form `state = state * c % d`. For a proposed bound `B`, the
initializer and every `d - 1` must fit in `[0, B]`, every `c` must be nonnegative,
and `B * c` must fit within `2^60 - 1`. This is an inductive proof over all
writes, including loop backedges and alternative branches. It does not assume
that a positive seed alone guarantees a positive sequence.

Only scalar functions without calls, memory operations, captures or other
aliasing constructs qualify. Parameter names, duplicate declarations, reads
before declaration, unknown writes, negative seeds and possible overflow block
the proof. Literal-initialized locals with no writes also have a proven bound.
Facts attach to single-definition read snapshots. Loop cells keep their original
private homes and register allocation.

The existing range propagation carries these bounds through products and
remainders. A proven nonnegative dividend needs no signed reciprocal rounding
correction, and power-of-two remainder can use a mask. The PRNG and random walk
meet these conditions. In the random walk, `% 4` changes from:

```asm
mov rcx, rax
sar rcx, 63
and rcx, 3
add rax, rcx
and rax, 3
sub rax, rcx
```

to:

```asm
and rax, 3
```

There are two accompanying arithmetic selections. Signed division/remainder by
two extracts its one-bit bias with `shr rcx, 63`, replacing `sar` plus a mask.
Multiplication by 0/1 emits a zero/copy, powers of two through `2^30` use a shift,
and 3/5/9 use `lea`. These preserve raw 64-bit wrapping, operand evaluation and
faults. Tagged multiplication retains its overflow and runtime fallback path.

## Measurements

[Complete report](raw-recurrence-performance.json), 2026-10-17 UTC, Intel Core
i5-13500H, GCC 14.2.0, pinned performance CPU 2. Each binary has 100 interleaved
samples, 10 warmups and five hardware-counter samples. All six checksums match
on every execution. The parent is `4357da184ce7456407a05b05294d87c39a367421`;
the report records the measured compiler and source hashes.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW (`f551c97`) | 44.291 ms | 0.875 ms |
| Divisibility pass (`4357da1`) | 25.834 ms | 0.636 ms |
| Bounded scalar arithmetic | 24.694 ms | 0.781 ms |
| GCC `-O3 -march=native` | 18.015 ms | 0.274 ms |
| GCC, also `-fno-tree-vectorize` | 17.546 ms | 0.364 ms |

The combined change reduces median time **4.4%** versus the previous head.
The complete branch reduces time **44.2%** (1.79× speedup) versus the original
compiler; the remaining ratio to GCC is 1.37×. A preceding 100-run comparison
measured 25.834 → 24.784 ms (4.1%). The small arithmetic changes alone measured
25.834 → 25.660 ms in that preceding trial; these combined results do not
attribute each workload's timing change to a particular instruction selection.

| Workload | Previous head | This pass |
|---|---:|---:|
| PRNG | 3.020 ms | 2.805 ms |
| Collatz | 5.858 ms | 5.631 ms |
| Byte histogram | 0.665 ms | 0.545 ms |
| Cellular automaton | 1.755 ms | 1.747 ms |
| Pointer chase | 3.969 ms | 4.028 ms |
| Random walk | 8.952 ms | 8.348 ms |

PRNG improves 7.1% and random walk 6.7%. Pointer chase regresses 1.5%; histogram
recovers part of the previous pass's regression. Layout and host variation can
affect kernels whose instruction sequences did not change. The host is pinned,
not isolated, and no timing gates are imposed in CI.

Five-run median performance-core user-mode counters:

| Counter | Previous head | This pass | Change |
|---|---:|---:|---:|
| Instructions | 232,019,900 | 221,226,445 | -4.7% |
| Cycles | 113,494,318 | 109,151,761 | -3.8% |
| Branches | 26,186,306 | 26,227,159 | +0.2% |
| Branch misses | 1,210,681 | 1,244,066 | +2.8% |

Static instructions fall from 1,224 to 1,213. The report retains every timing
sample, counter runtime/coverage, compiler/source/executable hashes and host
identity. Workload timers exclude output; end-to-end samples include process
launch and capture overhead. Reproduce with `raw_performance.py` as in the
[previous report](raw-divisibility.md), using `4357da1` as the saved baseline.

## Validation and limitations

Execution tests cover 377 full-width products, wrapping, retained effects and
faults, and 47 recurrence oracles with alternative branches, random constants,
negative/unknown/reset values, overflow and memory barriers. IR checks reject
parameters, captures, duplicate declarations, calls, reads before declaration
and non-preserving writes. Existing signed arithmetic and all six workload
oracles remain enabled.

The broad native verifier reports 115 passes and zero failures. Cross-target
raw/core/allocator checks execute with Unicorn 2.1.4; LLVM behavior and signed
strength-reduction tests pass. Local source-bootstrap convergence passes on
retry. As with the preceding pass, the first stage-3 attempt reported an OOM.
GitHub's preceding `4357da1` run also reported an OOM while compiling the
IR-inspection test, after its bootstrap convergence and raw codegen checks
passed. That run was requested again; the memory failure remains unresolved.
