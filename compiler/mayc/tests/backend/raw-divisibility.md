# RAW signed divisibility branches — issue #76, tenth pass

An exclusive branch predicate `n % 2^k == 0` or `n % 2^k != 0` now emits a
bit test and conditional branch, including when zero is the left comparison
operand. Signed remainder is zero exactly when the dividend's low `k` bits
are zero. This holds for negative dividends and `INT64_MIN`; it does not
replace an observable signed remainder with an unsigned mask.

The rule applies only to freestanding x86-64 code, positive literal powers of
two through `2^30`, and single-definition results. The remainder must have one
actual consumer, and the comparison must feed an exclusive branch. Only
rematerialized integer definitions, dead copies and already discarded IR can
intervene. Calls, loads, assignments, labels and other effects block fusion.
The divisor must still be a rematerializable constant. Other uses, comparisons
against nonzero values and dynamic runtime arithmetic retain their previous
lowering. Dividend evaluation, including load faults, still executes.

The Collatz parity branch previously emitted:

```asm
mov rcx, rax
sar rcx, 63
and rcx, 1
add rax, rcx
and rax, 1
sub rax, rcx
cmp rax, 0
jne odd
```

It now emits:

```asm
test rax, 1
jne odd
```

Register allocation and private homes for loop-carried values are unchanged.

## Measurements

[Complete report](raw-divisibility-performance.json), recorded 2026-10-17 UTC
on Intel Core i5-13500H, Linux, GCC 14.2.0, pinned performance
CPU 2. There are 100 interleaved samples per executable, 10 warmups and five
hardware-counter samples. All six checksums match on every execution. The
updated compiler is identified by its binary and source hashes in the report;
the parent revision is `6967db53eca651fb416d86164b9fd2039eb19d21`.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW (`f551c97`) | 44.251 ms | 0.681 ms |
| Previous branch head (`6967db5`) | 26.855 ms | 0.678 ms |
| Divisibility branch pass | 25.791 ms | 0.643 ms |
| GCC `-O3 -march=native` | 18.020 ms | 0.400 ms |
| GCC, also `-fno-tree-vectorize` | 17.573 ms | 0.398 ms |

This pass reduces median time by **4.0%** versus the previous head. The complete
branch reduces time by **41.7%** (1.72× speedup) versus the original compiler;
the remaining ratio to GCC is 1.43×. A separate preceding 100-run trial measured
26.944 → 25.781 ms (4.3%). These are observations on a pinned, non-isolated host,
without timing thresholds in CI.

| Workload | Previous head | This pass |
|---|---:|---:|
| PRNG | 3.012 ms | 3.013 ms |
| Collatz | 7.232 ms | 5.942 ms |
| Byte histogram | 0.534 ms | 0.659 ms |
| Cellular automaton | 1.754 ms | 1.752 ms |
| Pointer chase | 3.931 ms | 3.955 ms |
| Random walk | 8.800 ms | 8.772 ms |

Collatz improves **17.8%**. Histogram regresses **23.3%**, or 0.125 ms. Its
instruction/operand sequence is unchanged after normalizing branch addresses;
code layout is a possible explanation, not a demonstrated cause. The preceding
trial also observed this regression (0.536 → 0.661 ms). The net whole-suite gain
includes that loss; this change does not improve every workload.

Five-run medians of performance-core user-mode counters:

| Counter | Previous head | This pass | Change |
|---|---:|---:|---:|
| Instructions | 249,293,490 | 232,187,254 | -6.9% |
| Cycles | 118,423,259 | 115,564,032 | -2.4% |
| Branches | 26,159,982 | 26,205,213 | +0.2% |
| Branch misses | 1,218,159 | 1,209,151 | -0.7% |

Whole-executable static instructions fall from 1,230 to 1,224. Against the
original compiler, dynamic instructions fall from 777,647,110 to 232,187,254
(-70.1%). The report retains every timing sample, PMU runtime/coverage, compiler
and executable hashes, source hashes, kernel, CPU and GCC identity. Workload
timers exclude output; end-to-end measurements include process launch and
capture overhead. Disassembly and raw perf logs are produced next to the JSON.

```sh
python3 compiler/mayc/tests/raw_performance.py \
  --compiler compiler/mayc/mayc_new \
  --baseline-compiler /path/to/6967db5/mayc \
  --baseline-revision 6967db53eca651fb416d86164b9fd2039eb19d21 \
  --baseline-compiler /path/to/f551c97/mayc \
  --baseline-revision f551c97 \
  --cpu 2 --runs 100 --warmup 10 --perf \
  --output /tmp/divisibility-performance.json
```

## Correctness coverage

`raw_codegen.py` executes 792 signed divisibility predicates with full-width
boundaries and deterministic random inputs, six divisor widths, equality and
inequality, and both comparison operand orders. It also checks observable
remainders, nonzero comparisons, non-power divisors and retained load faults.
The IR tests cover both branch polarities, additional result consumers,
multiple divisor definitions, nonzero constants, CFG barriers and dynamic mode.
The existing signed division oracle and six benchmark checksums remain enabled.

Raw backend, allocator/forced-GC and core-runtime checks execute on all emulated
targets with Unicorn 2.1.4. The broad native verifier reports 115 passes and zero
failures. LLVM behavior tests pass. Source-bootstrap convergence
passes, including byte-identical stages 2 and 3. The first bootstrap attempt
failed with `out of memory` while building stage 3; a direct self-compile and a
complete retry passed. That intermittent memory failure remains unexplained;
this pass does not change runtime heap sizing or GC policy.
