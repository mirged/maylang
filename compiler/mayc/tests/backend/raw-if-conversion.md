# Branch-free RAW scalar diamonds — issue #78

Short statement `if`/`else if` diamonds over dedicated local registers are now
lowered without branches. Both arms are evaluated speculatively into
caller-saved scratch registers (`rax`, `rcx`, `rdx`, `rsi`, `rdi`, `r8`–`r11`).
Conditional moves select each value that differs between the arms, and every
dedicated home is written once after the outermost diamond. Nested diamonds
merge bottom-up: a scratch register born in exactly one arm becomes the
destination, with the condition inverted when the then-value owns it.

The random-walk direction chain previously emitted three compare/branch pairs:

```asm
cmp    r15,0x0
jne    .L1
add    rbx,0x1
jmp    .done
.L1: cmp r15,0x1
...
```

It now emits:

```asm
lea    rax,[rbx+0x1]
lea    rcx,[rbx-0x1]
lea    rdx,[r12+0x1]
lea    rsi,[r12-0x1]
cmp    r15,0x2
cmove  rsi,rdx
cmp    r15,0x1
cmovne rcx,rbx
cmove  rsi,r12
cmp    r15,0x0
cmove  rcx,rax
cmove  rsi,r12
mov    rbx,rcx
mov    r12,rsi
```

Collatz selects `n / 2` or `3n + 1` with `test rbx,0x1; cmove rdx,rax`.

## Safety

Only register arithmetic is speculated: `lea`, `add`, `sub`, `imul`, `neg`,
shifts, literal moves and signed division or remainder by a positive
power-of-two literal. None of these can call, access memory or trap, and each
wraps at 64 bits exactly like the branch form. Signed quotients and remainders
use the same truncating bias as the existing lowering. Predicates compare a
register with a register or an imm32 literal (either order), test a register's
truthiness, or test signed `n % 2^k` against zero.

These keep their branches:

- calls, loads/stores and syscalls;
- division or remainder by zero, a negative or a non-power-of-two divisor;
- frame-home, global and function names (only dedicated registers qualify);
- observable `if` results, and temporaries that outlive the region or cross a
  nested diamond;
- `break`, `continue`, returns, labels and any other control flow;
- arms beyond 16 speculated instructions or the nine scratch registers.

Tagged/full-runtime functions are unchanged. A rejected match restores the code
buffer; the lowering never adds labels, fixups or relocations, so rollback is
complete. Assignments never alias another local's register, so the final writes
are independent moves.

## Predictability heuristic

A conditional move puts the select on the data-dependency chain; a predicted
branch does not. Predicates that read only *induction locals* (written solely
as `v = literal` or `v = v ± literal`) and literals follow periodic or monotone
patterns that branch predictors learn, so those diamonds keep the branch form.
Data-dependent predicates are converted.

Median of 25 interleaved runs (10 million iterations each, ms, standard
deviation in parentheses), pinned to CPU 2:

| Loop | Baseline | Without heuristic | This pass | GCC `-O3` choice |
|---|---:|---:|---:|---|
| `if i % 1024 == 1023` two arms | 5.172 (0.206) | 7.022 (0.517) | 5.244 (0.160) | branch |
| PRNG parity, two arms | 53.002 (0.601) | 28.305 (0.225) | 28.325 (0.270) | `cmov` |
| PRNG parity, one arm | 53.043 (0.563) | 28.246 (0.255) | 28.307 (0.170) | `cmov` |
| Running maximum of PRNG values | 28.305 (0.323) | 28.263 (0.220) | 28.301 (0.201) | `cmov` |
| `x = x + i; if x > 1000000000 { x = 0; }` | 3.604 (0.131) | 6.523 (0.187) | 6.492 (0.323) | `cmov` |

On these loops the conversions match GCC 14.2 `-O3 -march=native`. The
remaining tradeoff is the last row: a rarely taken guard on a loop-carried
accumulator is predicted well, and the conditional move adds latency to every
iteration, about 1.8× slower in this microbenchmark. GCC makes the same choice
there. Without profile data the backend cannot tell such guards from
data-dependent diamonds such as a branch-free `abs`. The 10^12 threshold in the
original guard microbenchmark is not imm32 and keeps its branch.

## Measurements

[Complete report](raw-if-conversion-performance.json), 2026-10-17 UTC, Intel
Core i5-13500H, GCC 14.2.0, pinned performance CPU 2. Each executable has 100
interleaved samples, 10 warmups and five hardware-counter samples. Every run
matches all six checksums. The baseline is the merged #77 compiler at
`c3d3ea8`; the measured compiler is `28dc597`.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Baseline (`c3d3ea8`) | 21.667 ms | 0.360 ms |
| Branch-free diamonds | 16.742 ms | 0.335 ms |
| GCC `-O3 -march=native` | 17.954 ms | 0.297 ms |
| GCC, also `-fno-tree-vectorize` | 17.597 ms | 0.291 ms |

The median improves **22.7%** (1.29× speedup) and is now 0.93× of GCC's.

| Workload | Baseline | This pass | Change | GCC |
|---|---:|---:|---:|---:|
| PRNG | 2.804 ms | 2.804 ms | 0.0% | 2.799 ms |
| Collatz | 4.013 ms | 3.332 ms | −17.0% | 3.488 ms |
| Byte histogram | 0.537 ms | 0.539 ms | +0.4% | 0.214 ms |
| Cellular automaton | 1.753 ms | 1.757 ms | +0.3% | 0.467 ms |
| Pointer chase | 3.924 ms | 3.913 ms | −0.3% | 3.900 ms |
| Random walk | 6.983 ms | 2.796 ms | −60.0% | 5.348 ms |

Random walk and Collatz are now faster than GCC's output. The memory-heavy
kernels have no dedicated local registers and are unchanged within noise; see
#79. The host is pinned, not isolated; there are no machine-specific timing
gates.

Five-run median performance-core user-mode counters:

| Counter | Baseline | This pass | Change |
|---|---:|---:|---:|
| Instructions | 181,771,171 | 197,926,385 | +8.9% |
| Cycles | 97,324,403 | 72,765,362 | −25.2% |
| Branches | 26,358,337 | 18,500,848 | −29.8% |
| Branch misses | 1,222,224 | 31,753 | −97.4% |

Speculation executes both arms, so instructions rise while mispredictions
nearly disappear. Static instructions change from 1,164 to 1,169. Every timing
sample, counter coverage, compiler/executable/source hash and host detail is
retained in the JSON. Reproduce with `raw_performance.py` as in the
[divisibility report](raw-divisibility.md), using a saved `c3d3ea8` compiler.

## Correctness coverage

`raw_codegen.py` generates 160 seeded functions with nested diamonds and
`else if` chains inside loops, then checks 480 calls against a Python oracle
with exact 64-bit wrapping, signed truncating division/remainder by powers of
two, all signed comparisons in both operand orders, remainder and truthiness
predicates, observable `if` results and full-width inputs including
`INT64_MIN`/`INT64_MAX`. At least 40 generated functions must use `cmov`.
Fixed checks cover a walk with a single remaining loop branch, untaken
`/ 0` and loads (which must keep branches), `INT64_MIN` halving, sequential
aliasing (`x = y; y = x`), imm64 additions and empty arms. Swapping the
`cmov` polarity or dropping the signed remainder bias makes the oracle fail.

IR tests check the `cmp`/`cmove` encoding and the final home write, one-armed
selection with the inverted condition, induction-predicate rejection, frame
locals, non-power and zero divisors, loads, escaping temporaries, extra labels,
mismatched joins, scratch/size limits and tagged/dynamic functions; every
rejection emits zero bytes.

The broad verifier passes 115/115, including RAW workload checksums, ABI,
allocator/GC roots and the cross-format backend checks. Compliance (69), LLVM
behavior (41), Rust tests and source-bootstrap convergence pass, as do all 34
native-target fixtures emitted locally and their x86-64 Linux execution.
Cross-architecture execution needs emulators that are not installed here and
runs in CI.
