# Extended-suite gaps — issues #84–#87

The [extended suite](raw-extended-suite.md) found four RAW code-generation gaps
that the six core kernels did not exercise. Each is a separate commit, measured
on both suites.

## #84: power-of-two division beyond 2^30

The signed power-of-two `/` and `%` lowering stopped at 2^30 because its bias
and mask were positive sign-extended imm32 operands, so `% 4294967296` fell back
to `cqo; idiv` on the hash kernel's dependency chain. Every positive power of
two up to 2^59, the compiler's own tagged literal range, now uses shifts:

```asm
mov    rcx,rax
sar    rcx,0x3f
shr    rcx,0x20        ; bias: 2^32 - 1 for negative dividends
add    rax,rcx
mov    eax,eax         ; mask; shl/shr for other shifts above 30
sub    rax,rcx
```

Proven-nonnegative dividends use the mask alone. Dedicated-local arithmetic,
zero-remainder branches and #78 selection still encode `divisor - 1` as imm32 and
keep the 2^30 limit; multiplication by any such power becomes `shl`.

## #85: short-circuit conditions

An `and`/`or` that only steers an `if`, `while` or return-`if` branch now lowers
in IR to a chain of conditional jumps, so each operand reaches the existing
compare-branch fusion. Insertion sort's `while j >= 0 and load64(a + j * 8) > key`
became two `cmp`/`jcc` pairs instead of `setcc`, two frame stores, a reload,
`test` and a second `setcc`. The right operand, with its effects and faults,
runs only when the left does not decide the result. An else-less `if` still
yields 0 on its false path. Booleans that are assigned, returned or passed keep
their materialized form. The change applies in RAW mode only.

Earlier operands of such a chain jump directly to the `if`'s else label. The #78
diamond lowering assumed that only its own branch reached the labels it removes,
and a call-free function could then jump to label 0. Selected regions now
must own every jump to their labels.

## #86: parameters and loop-hot locals

Parameters are now candidates for RBX/r12–r15. The prologue moves each promoted
parameter from its ABI register or stack slot instead of storing it to the
frame. Bodies with direct calls to resolved, non-foreign user functions,
`syscall`, `exit` and the pure `addr`/`cstr`/`len`/`ptr` builtins are eligible
too. Callees save the callee-saved registers they use, and `syscall` clobbers
`rax`/`rcx`/`r11` only. `__sp` and the other `__` builtins, unresolved or
shadowed callees, captures and boxed values still exclude a body.

Candidates are ranked by visits weighted 8× per enclosing loop (at most three
levels). The last backward jump to a label closes one loop, so `continue` edges
do not count twice. The weighting gave `left`/`right` in the cellular automaton
registers, which made `if right == width { right = 0; }` eligible for `cmov` and
slowed the kernel 10%. The #78 predictability rule now also keeps branches for
locals written as an offset of another induction local, which recovered it.

## #87: per-call cost

Linear scan takes an optional volatile pool. In promoted bodies with calls, an
interval uses r8–r10 when no call lies in (start, end]. It uses r10 alone when
the only such call is a user call at its end, where the value is an argument:
user calls take arguments in `rdi`–`r9` and never read r10. Syscall arguments use
r10/r8/r9, so their values stay in callee-saved registers or the frame. Unneeded
callee-saved registers are not saved. RAW code after an unconditional jump or
return is skipped until the next label, and a jump or return whose target
directly follows emits nothing.

`fib` previously saved three registers, stored `n` to the frame and reloaded it
three times, and ended with a jump to the next instruction. It now keeps `n` in
RBX, passes `n - 1` through r10, and saves only RBX and r15. r15 holds the first
result across the second call.

Frame sizing is unchanged; `sub rsp, imm` costs the same at any size.

## Measurements

[Extended](raw-call-gaps-performance.json) and
[core](raw-call-gaps-core-performance.json) reports, 2026-10-17 UTC, Intel Core
i5-13500H, GCC 14.2.0, pinned performance CPU 2. The host is not isolated. Each
executable has 100 interleaved samples, 10 warmups and five hardware-counter
samples, and every run matches all checksums. The baseline is the 0.13.102
release `bdfae89`; the measured compiler is `bdc5844`.

| Workload | 0.13.102 | This branch | Change | GCC `-O3` | ÷ GCC before | ÷ GCC after |
|---|---:|---:|---:|---:|---:|---:|
| Sieve | 4.449 | 4.125 | −7.3% | 2.989 | 1.49× | 1.38× |
| Matrix multiply | 0.917 | 0.914 | −0.3% | 0.326 | 2.82× | 2.81× |
| Recursive fib | 1.191 | 0.978 | −17.9% | 0.225 | 5.30× | 4.35× |
| Insertion sort | 4.685 | 1.733 | −63.0% | 0.888 | 5.28× | 1.95× |
| GCD grid | 1.713 | 1.701 | −0.7% | 1.701 | 1.01× | 1.00× |
| Hash | 23.902 | 11.053 | −53.8% | 8.363 | 2.86× | 1.32× |
| Binary search | 13.756 | 12.484 | −9.2% | 11.744 | 1.17× | 1.06× |
| Mandelbrot | 1.053 | 1.056 | +0.3% | 0.803 | 1.31× | 1.31× |
| N-queens | 2.210 | 1.327 | −40.0% | 1.132 | 1.95× | 1.17× |
| Dot product | 2.189 | 2.005 | −8.4% | 0.643 | 3.40× | 3.12× |
| Knapsack | 1.668 | 1.296 | −22.3% | 0.528 | 3.16× | 2.46× |
| **Sum of medians** | **57.733** | **38.672** | **−33.0%** | **29.341** | **1.97×** | **1.32×** |

The core suite is unchanged within noise (14.365 → 14.262 ms, −0.7%). The
byte histogram is 12.3% faster, and the other five kernels move by at most
1.5%. Per-workload dispersion is at most 10.7%.

| Executable | End-to-end median | Instructions | Cycles | Static instructions |
|---|---:|---:|---:|---:|
| 0.13.102, extended | 59.422 ms | 565,326,931 | 267,656,996 | 2,151 |
| This branch, extended | 40.134 ms | 457,780,276 | 179,644,180 | 2,040 |
| GCC `-O3`, extended | 31.125 ms | 188,815,635 | 136,149,782 | 1,873 |
| 0.13.102, core | 15.667 ms | 166,972,302 | 69,022,224 | 1,089 |
| This branch, core | 15.566 ms | 163,898,387 | 68,855,459 | 1,058 |

The steps were measured separately with 25 interleaved runs of compilers built
at each commit. Sums of medians over both suites, in ms:

| 0.13.102 | #84 | #85 | #86 | #87 |
|---:|---:|---:|---:|---:|
| 72.522 | 59.774 | 57.132 | 53.956 | 53.561 |

#84 accounts for the hash, #85 for half of insertion sort and N-queens, #86 for
the rest of those plus sieve, binary search, knapsack and histogram, and #87 for
fib and knapsack.

## Remaining gaps

- **Dot product and matrix multiply (2.8–3.1×):** GCC unrolls and vectorizes;
  RAW does one scalar step per iteration. The dot product also spills its
  product because the `sum` snapshot is taken before the two loads.
- **Recursive fib (4.35×):** GCC turns one recursive call into a loop.
  Arguments are still computed in `rax` and copied twice (`mov r10,rax; mov
  rdi,r10`) instead of being formed directly with `lea rdi,[rbx-1]`.
- **Knapsack (2.46×) and insertion sort (1.95×):** stores through `(j + 1) * 8`
  are not fused, because address fusion does not distribute a scaled sum.

## Correctness coverage

`raw_codegen.py` adds:

- 1,264 full-width quotient and remainder checks and 632 divisibility checks
  for every shift from 30 through 59, plus tagged execution (#84);
- 2,400 short-circuit checks over 240 functions built from random `and`/`or`
  trees whose leaves record evaluation order, in `if`, `if`/`else`, `if`-value,
  return-`if` and `while` forms, plus load guards, faults, an observable Boolean
  and a shared else label (#85);
- promoted parameters, stack arguments, locals live across calls, recursion and
  syscalls, `__sp` exclusion, and an `mmap` whose computed fifth and sixth
  arguments would be clobbered through r10 (#86, #87).

Allocator unit tests cover spanning values, user-call and syscall arguments and
call results; codegen unit tests cover label ownership and the planner rules.
Mutations of the wide bias, branch inversion, else-less value, call-spanning
volatile rule and syscall-argument rule each make a check fail.

The broad verifier passes 115/115, compliance 69/69, LLVM behavior and
source-bootstrap convergence pass. Cross-architecture execution runs in CI.
