# Proven nonnegative RAW arithmetic — issue #76, sixth pass

The x86 backend tracks conservative nonnegative bounds on single-definition
raw values. Sources include nonnegative literals, zero-extending 8-/16-/32-bit
load intrinsics, raw Booleans, and copies of proven values. Addition and
multiplication propagate a bound only if their maximum result fits within the
compiler's tagged arithmetic range, a conservative subset of signed 64-bit
values. Positive literal division/remainder propagate bounds as well.

Mutable/multiple-definition values, use-before-definition intervals, signed
loads, unknown inputs, and possible wrapping arithmetic retain unknown bounds.
Load intrinsic names must not resolve to a shadowing local/global/function.
No loop induction assumptions, alias assumptions about loaded data, or
control-flow-sensitive range claims are made.

A proven nonnegative dividend uses an unsigned shift or mask for power-of-two
division/remainder. In particular, the automaton's sum of three zero-extended
bytes is in `[0, 765]`, so its `% 2` can safely use `and rax, 1`. An arbitrary
signed dividend retains the existing bias-and-subtract sequence. Division by
positive one is separately an identity, and remainder by one is zero for every
signed dividend.

Regression fixtures check the byte sum and a zero-extended 32-bit quotient.
They also construct `(2^60 - 1) * 16 + load8(p)`, which can wrap negative:
the optimizer must decline the nonnegative shortcut, and the actual negative
remainder and signed bias are verified. Existing exhaustive/full-width signed
oracles and repeated six-workload checksums pass. Backend/core/allocator checks
execute with Unicorn 2.1.4, including Windows ABI preservation, and LLVM and
bootstrap convergence checks pass.

The pinned 50-run report is [raw-range-performance.json](raw-range-performance.json),
comparing the original compiler with `ef11661` and this pass. The small
whole-suite timing change should be interpreted alongside the recorded
instruction counts and per-workload samples, not as a machine-independent
speed guarantee.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW | 46.075 ms | 0.964 ms |
| Local operand pass (`ef11661`) | 28.207 ms | 2.003 ms |
| Range pass | 28.071 ms | 0.870 ms |
| GCC `-O3 -march=native` | 18.926 ms | 0.443 ms |
| GCC, also `-fno-tree-vectorize` | 18.453 ms | 0.885 ms |

The 0.5% whole-suite median change is smaller than the observed dispersion;
no stable runtime gain is claimed for this pass alone. Five-run median
instructions fall from 256,023,951 to 252,049,799 and cycles from 124,375,109
to 120,808,499. The recorded automaton medians are 1.853 and 1.850 ms, also
effectively unchanged at this measurement resolution. Static instructions
fall from 1,476 to 1,470. All checksums match. These results retain the earlier
pinned/non-isolated-host and PMU-coverage caveats.
