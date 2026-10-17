# RAW signed constant division — issue #76, second pass

This follows the operand/branch pass in `f9776ac`. RAW x86-64 division and
remainder by positive, non-power-of-two literals use a signed high multiply,
an optional dividend addition, an arithmetic shift, and a sign correction.
Remainders are reconstructed as `n - quotient * divisor`. The original dividend
and every allocated operand home remain available throughout the sequence.
Only `rax`, `rcx`, and `rdx` are scratch registers.

Positive literal divisors through the compiler's maximum integer literal
(`2^60 - 1`) are supported. The dividend can contain any signed 64-bit value.
The existing small power-of-two path is retained. Other power-of-two divisors,
negative divisors, nonliteral divisors, and zero retain hardware `idiv`.
`INT64_MIN / -1` and the corresponding remainder retain the existing `SIGFPE`
overflow trap. Dynamic arithmetic and its type, float, overflow, and operator
fallbacks are unchanged.

## Reciprocal generation and rounding

The general multiply/add/shift strategy is also described in
[LLVM's signed constant-division documentation](https://llvm.org/doxygen/structllvm_1_1SignedDivisionByConstantInfo.html).
This implementation chooses a sufficient round-up reciprocal bound directly:

- Set `p = 64 + shift`, `m = ceil(2^p / d)`, and `e = m*d - 2^p`.
- Increase `shift` from zero until `0 < e <= 2^(shift + 1)`.
- Then `floor(n*m / 2^p) + (n < 0)` is the quotient truncated toward zero.

For `0 <= n < 2^63`, `0 <= n*e/2^p < 1`. Writing `n = q*d + r`,
`0 <= r < d`, the fractional numerator `r + n*e/2^p` stays below `d`, so the
floor is exactly `q`. For `n = -u < 0`, `0 < u*e/2^p <= 1`, including
`u = 2^63`. The fractional numerator `r + u*e/2^p` is in `(0, d]`;
the floor is therefore one below the truncated quotient. Adding one corrects
it. Powers of two have zero reciprocal error and are excluded from this rule.

The selected multiplier fits in 64 bits. The search terminates by
`shift = ceil(log2(d)) - 1`, when the bound exceeds the error, which is less
than `d`. At this shift, `2^(64+shift)/d < 2^64 - 1` for supported non-power
divisors. The generator stores the floor quotient in two 32-bit limbs and
rounds up once. It never stores the multiplier in a tagged compiler integer.
Remainder doubling uses `rest - (d - rest)` when carrying, and the error bound
saturates at `d`; neither operation overflows near the tagged integer limit.

If the multiplier's high bit is set, its encoded signed value is `m - 2^64`.
Adding the original dividend to the signed high product restores the missing
term before shifting. This avoids unsigned absolute-value conversion and its
`INT64_MIN` special case.

## Validation

`raw_codegen.py` independently models the reciprocal with Python arbitrary
precision and exhausts every signed dividend and positive non-power divisor
for widths 3 through 10. Native generated programs also test every dividend
from -4097 through 4097 for every non-power divisor from 3 through 63, plus
2,697 full-width cases with signed endpoints, deterministic random values,
large divisors, and values next to exact multiples. Disassembly checks require
`imul rdx` and no `idiv` for selected divisors, and retain `idiv` for fallback
cases. Encoder tests check exact multiplier limbs and shifts, including both
signed encodings and the largest supported divisor.

All six issue workloads match C on repeated runs. Existing raw/backend,
allocator/forced-GC, core-runtime, strength-reduction/runtime-fallback, LLVM,
and source-bootstrap convergence checks pass. Unicorn is unavailable, so
cross-architecture execution is skipped; format checks still run.

## Reproduce and measurements

The [benchmark runner](../raw_performance.py) now accepts repeated
`--baseline-compiler` and `--baseline-revision` options. This compares the
original compiler, the operand pass, the current compiler, and both GCC
variants in one rotated, pinned run:

```sh
python3 toolchain/mayc/tests/raw_performance.py \
  --compiler toolchain/mayc/mayc_new \
  --baseline-compiler /path/to/original/mayc --baseline-revision f551c97 \
  --baseline-compiler /path/to/operand-pass/mayc --baseline-revision f9776ac \
  --cpu 2 --runs 50 --warmup 10 --perf --output /tmp/constant-performance.json
```

Results are recorded in [raw-constant-performance.json](raw-constant-performance.json).
The original [first-pass report](raw-performance.md) remains available separately.

On the same Debian/i5-13500H host, pinned to performance CPU 2, 50 samples with
10 warmups give:

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW (`f551c97`, `before`) | 44.361 ms | 0.682 ms |
| Operand pass (`f9776ac`, `before_2`) | 37.097 ms | 0.602 ms |
| Operand + reciprocal passes (`may`) | 31.374 ms | 0.608 ms |
| GCC `-O3 -march=native` | 17.911 ms | 0.403 ms |
| GCC, also `-fno-tree-vectorize` | 17.708 ms | 0.406 ms |

| Workload | Original | Operand pass | Combined |
|---|---:|---:|---:|
| PRNG | 4.741 ms | 4.743 ms | 3.011 ms |
| Collatz | 11.007 ms | 8.083 ms | 8.159 ms |
| Byte histogram | 1.758 ms | 1.119 ms | 1.109 ms |
| Cellular automaton | 6.428 ms | 4.087 ms | 4.064 ms |
| Pointer chase | 6.609 ms | 6.534 ms | 3.986 ms |
| Random walk | 12.019 ms | 10.937 ms | 9.465 ms |

Five-run median performance-core user counters:

| Counter | Original | Operand pass | Combined |
|---|---:|---:|---:|
| Cycles | 203,044,394 | 168,366,243 | 141,088,923 |
| Instructions | 777,647,870 | 503,125,873 | 529,560,227 |
| Branches | 25,958,599 | 26,018,954 | 26,094,221 |
| Branch misses | 1,201,609 | 1,221,303 | 1,232,436 |

The reciprocal pass reduces median runtime another 15.4% and median cycles
another 16.2%. It increases instructions by 5.3% relative to the operand pass:
the multiply/shift sequence replaces a smaller but slower division sequence.
Cumulatively, runtime is 29.3% lower, cycles 30.5% lower, and instructions
31.9% lower than the original compiler. All checksums match on every run.
The benchmark executable has no `idiv` instructions after the reciprocal pass.

Workload timers exclude reporting; end-to-end measurements include `taskset`,
process launch, and Python output capture. The host was pinned, not isolated.
The report includes PMU runtime/coverage and every sample; these measurements
do not impose a CI threshold. Remaining large deficits include Collatz and
automaton code. General copy propagation, address selection, and CFG-aware
allocation remain further work for issue #76.

The subsequent [literal rematerialization pass](raw-literals.md) removes
constant temporaries and selects immediate operands.
