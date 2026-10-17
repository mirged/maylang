# Unread RAW branch-result copies — issue #76, twelfth pass

The backward raw dead-expression pass can now remove an unread `IR_COPY` even
when its destination has multiple definitions. Each removed copy decrements
the destination's definition count and its source's read count. This lets an
unused outer branch result release unused inner branch results and comparison
copies. Branch-only comparison fusion can then emit direct conditional jumps
through a nested `else if` chain.

The condition is still zero readers across the whole function. Observable
joins, copies with readers and other multiple-definition expressions retain
their previous handling. CFG positions and boundaries remain in place, and
register allocation/private homes are unchanged. Calls, memory operations and
arithmetic traps retain their evaluation. This extends dead-copy deletion; it
does not treat mutable control-flow values as SSA.

In the random walk, the later comparisons previously used this pattern:

```asm
cmp rax, 1
sete al
movzx eax, al
mov [boolean_home], rax
mov [unused_branch_home], rax
mov rax, [boolean_home]
test rax, rax
je next_case
```

They now use `cmp rax, 1; jne next_case`, with no Boolean homes or unused
branch-result stores.

## Measurements

[Complete report](raw-branch-copy-performance.json), 2026-10-17 UTC, Intel Core
i5-13500H, GCC 14.2.0, pinned performance CPU 2. Each executable has 100
interleaved runs, 10 warmups and five counter samples. Every execution matches
all six checksums. The parent is `353bcd5`; measured compiler/source hashes are
recorded in the JSON.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW (`f551c97`) | 44.287 ms | 0.675 ms |
| Divisibility pass (`4357da1`) | 25.719 ms | 0.623 ms |
| Bounded arithmetic (`353bcd5`) | 24.695 ms | 0.607 ms |
| Unread branch copies | 24.086 ms | 0.592 ms |
| GCC `-O3 -march=native` | 17.981 ms | 1.673 ms |
| GCC, also `-fno-tree-vectorize` | 17.532 ms | 0.439 ms |

This pass reduces median time **2.5%** versus its parent. Together with bounded
arithmetic, it improves **6.4%** versus `4357da1`. The complete branch improves
**45.6%** (1.84× speedup) versus the original compiler, with a remaining 1.34×
ratio to GCC. GCC's end-to-end dispersion is higher in this trial; every sample
is retained. The host is pinned, not isolated; these are observations without
timing thresholds in CI.

| Workload | Bounded arithmetic | This pass |
|---|---:|---:|
| PRNG | 2.803 ms | 2.807 ms |
| Collatz | 5.620 ms | 5.830 ms |
| Byte histogram | 0.542 ms | 0.545 ms |
| Cellular automaton | 1.746 ms | 1.762 ms |
| Pointer chase | 3.931 ms | 3.970 ms |
| Random walk | 8.341 ms | 7.488 ms |

Random walk improves **10.2%** versus the parent and **14.7%** versus `4357da1`.
Collatz regresses 3.7% versus the parent; the overall gain includes that loss.
Code layout and host variation can affect timings beyond the changed kernel.

Five-run median performance-core user-mode counters:

| Counter | Bounded arithmetic | This pass | Change |
|---|---:|---:|---:|
| Instructions | 221,213,503 | 207,283,283 | -6.3% |
| Cycles | 111,535,289 | 104,354,313 | -6.4% |
| Branches | 26,225,625 | 26,256,055 | +0.1% |
| Branch misses | 1,243,487 | 1,223,397 | -1.6% |

Static instructions fall from 1,213 to 1,180. Versus `4357da1`, instructions
fall 10.6% and cycles 8.8%; versus the original compiler, instructions fall
73.4% and cycles 48.0%. The report includes counter coverage/runtime, hashes
and host details. Workload timers exclude output; end-to-end times include
process launch and capture overhead. Reproduce with `raw_performance.py` as
in the [divisibility report](raw-divisibility.md), adding saved compilers for
`353bcd5`, `4357da1` and `f551c97`.

## Correctness

New execution tests cover discarded nested branches with observable local
assignments, observable branch-expression results and effectful calls in each
branch. Disassembly requires three direct comparisons in a nested chain, with
no Boolean materialization/reload/test. IR regressions remove unread copies
with multiple definitions while preserving a label and observable copies.
Existing loop/backedge, trapping arithmetic, signed oracle, call/syscall, GC
and six-workload checks remain enabled.

The final broad verifier reports **115 passed, 0 failed** with emulation
enabled. LLVM behavior checks pass. Source-bootstrap convergence passes on its
first attempt with byte-identical stages 2 and 3. The preceding `4357da1` push
workflow also completed successfully on GitHub; its separate PR workflow had
an OOM in the IR-inspection test and was requested again. The intermittent
memory failure remains unresolved; this pass changes neither heap sizing nor
GC policy.
