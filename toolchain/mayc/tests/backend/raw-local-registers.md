# Dedicated RAW local registers — issue #76, thirteenth pass

Freestanding scalar functions can now keep frequently used unboxed locals in
dedicated callee-saved registers for their entire execution. The planner ranks
local declarations by static reads/writes, requires at least four visits, and
reserves up to five registers: RBX and r12-r15. Those registers are removed
from the virtual-temporary pool. Every selected register is saved on entry and
restored on return. Parameters retain their existing frame homes.

This is a whole-function home for each selected local, not a relaxation of
linear-scan liveness. Locals keep that home across every branch, loop backedge,
break and continue. Other virtual values retain their existing allocation,
spill slots and private homes for control-flow/multiple-definition intervals.
If all five registers are reserved, virtual temporaries spill normally.

Eligibility is deliberately strict: the function must contain only scalar
arithmetic, declarations/assignments and control flow. Runtime calls, pointer
loads/stores, captures, boxed variables and other aliasing constructs exclude
the body. Unknown/global/function-name reads also exclude it. Parameter names,
duplicate declarations and reads before declaration cannot become promoted
locals. Tagged/runtime functions are unchanged and retain GC root handling.

## Direct operations

Exclusive read/arithmetic/write chains now operate on the local register
directly. Examples include `i = i + 1`, `n = n / 2`, and `n = n * 3 + 1`.
Branch-only comparisons can compare the local register without copying it to
`rax`. Signed division/remainder keeps the negative-dividend correction;
positive power-of-two divisors through `2^30` are supported. Zero divisors and
`INT64_MIN / -1` retain the general trapping path.

Affine updates use `lea` for multipliers 3, 5 or 9 and a signed 32-bit additive
constant. Arithmetic still wraps at 64 bits. An observable intermediate value,
another reader, an intervening effect or a CFG boundary blocks fusion. The
existing adjacent-right-operand borrowing rule can read a promoted local's
register directly while preserving snapshots in other cases.

For example, a hot counter previously emitted:

```asm
mov rax, [counter_home]
add rax, 1
mov [counter_home], rax
```

It now emits `add r14, 1`. A Collatz odd step changes from a load, `lea`, add
and store to `lea rbx, [rbx + rbx*2 + 1]`. Its signed halving step updates RBX
using RCX for the one-bit negative-dividend bias, without a round trip through
RAX or the local's frame slot.

## Measurements

[Complete report](raw-local-register-performance.json), 2026-10-17 UTC, Intel
Core i5-13500H, GCC 14.2.0, pinned performance CPU 2. Each executable has 100
interleaved samples, 10 warmups and five hardware-counter samples. Every run
matches all six checksums. The parent is
`1fca7baa300a17328c2101681ac707d9be518767`; compiler/source hashes identify the
measured update in the JSON.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW (`f551c97`) | 44.499 ms | 0.772 ms |
| Previous head (`1fca7ba`) | 24.068 ms | 0.702 ms |
| Dedicated local registers/direct operations | 21.700 ms | 0.322 ms |
| GCC `-O3 -march=native` | 18.057 ms | 0.359 ms |
| GCC, also `-fno-tree-vectorize` | 17.593 ms | 0.363 ms |

The combined change improves median runtime **9.8%** versus the previous head.
The complete branch improves **51.2%** (**2.05× speedup**) versus the original
compiler. The remaining ratio to GCC is **1.20×**. A preceding 100-run trial
measured 24.121 → 21.704 ms (10.0%). The timed Maylang executable has the same
hash in both trials, including after tightening the planner's eligibility.

| Workload | Previous head | This pass |
|---|---:|---:|
| PRNG | 2.802 ms | 2.804 ms |
| Collatz | 5.887 ms | 4.047 ms |
| Byte histogram | 0.545 ms | 0.538 ms |
| Cellular automaton | 1.763 ms | 1.763 ms |
| Pointer chase | 3.937 ms | 3.928 ms |
| Random walk | 7.436 ms | 7.008 ms |

Collatz improves **31.3%** and random walk **5.8%**. The memory-heavy kernels
are outside the promotion rule. Small differences there can reflect layout or
host variation rather than this optimization. The host is pinned, not isolated;
there are no machine-specific timing gates.

Five-run median performance-core user-mode counters:

| Counter | Previous head | This pass | Change |
|---|---:|---:|---:|
| Instructions | 206,997,636 | 181,598,885 | -12.3% |
| Cycles | 106,915,058 | 96,883,675 | -9.4% |
| Branches | 26,219,874 | 26,333,352 | +0.4% |
| Branch misses | 1,224,346 | 1,221,345 | -0.2% |

Static instructions fall from 1,180 to 1,164. Versus the original compiler,
instructions fall **76.7%** and cycles **52.3%**. Every timing sample, counter
runtime/coverage, compiler/executable/source hash and host detail is retained.
Workload timers exclude output; end-to-end samples include launch/capture
overhead. Reproduce with `raw_performance.py` as in the
[divisibility report](raw-divisibility.md), using saved compilers for `1fca7ba`
and `f551c97`.

## Correctness coverage

New execution oracles cover 720 full-width direct-local arithmetic cases
across RBX and r12-r15, signed division/remainder, wrapping affine updates,
observable assignment results and unchanged division traps. Further tests
cover seven competing locals with spilled snapshots, nested loop joins,
break/continue, old values live across mutations, live caller operands, and
eight-argument callees with promoted state.

IR tests cover register-pool separation, both comparison branch polarities,
all signed comparisons, extra readers, labels, parameter/captured/boxed names,
duplicate declarations, unknown reads and runtime-call exclusion. Low/extended
register move and borrowed-operand encodings are checked. The Windows emulator
now initializes and verifies RBX as well as r12-r15 around a promoted loop.
All existing signed arithmetic, effects/faults, GC and six-workload checks
remain enabled.

Source-bootstrap convergence passes on its first attempt with byte-identical
stages 2 and 3, and LLVM behavior checks pass. The broad verifier reports
114 passes and one failure: compiling the IR-inspection driver hit an OOM.
A focused rerun of that test passes. Both GitHub bootstrap runs at the preceding
`1fca7ba` head also reported a stage-3 OOM, while native target, repository and
browser checks passed. This pre-existing memory failure remains unresolved;
the optimization changes neither runtime heap sizing nor GC policy.
