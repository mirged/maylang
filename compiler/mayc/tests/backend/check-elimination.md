# Check elimination and LICM — issue #131, measured not merged

Phase 4's next items are bounds-check elimination, overflow-check elimination
for proven-range induction variables and loop-invariant code motion. All three
were evaluated on the integrated base `40ae868` and all three came out
negative, so the code was reverted: this page and its raw samples are the
deliverable. The measurement method is the one the other backend reports use:
interleaved before/after child CPU time on one host, with the paired median
reported next to the side medians because the machine is shared.

## Why remove checks at all — and the ceiling

The fat backend emits its own checks:

- `xs[i]` loads (and stores) compare the index against the list length before
  the in-range access (`x86_64_fat.may` `fat_index_load`, `fat_index_set`):
  `mov r10, [r8]; cmp rax, r10; jae slow`.
- Inline `Int` `+`, `-`, `*` follow the operation with `jo slow`, whose slow
  path raises the runtime's `arithmetic` fault.
- A `while (i < len(xs)) { xs[i] ... }` loop seems like the ideal case: the
  loop guard proves `i < len(xs)` for the body, so the load's bounds check is
  redundant on every iteration. The equivalent for arithmetic is an induction
  variable whose range is proven from a constant guard (`while (i < 10000000)`),
  where `i += 1` cannot overflow.

Any sound version of the pass can only remove a subset of those checks: it
needs the guard, a proven zero-based induction variable, an unchanged receiver,
and no call or store that could alter the receiver or the field before the
access. To bound what the whole item could ever pay, a deliberately **unsound**
experimental build removed every list bounds check and every inline `Int`
overflow check unconditionally. Every benchmark printed identical output on it.
25 paired runs against the unchanged base:

| Benchmark | baseline ms | checks removed, ms | change | paired median |
| --- | --- | --- | --- | --- |
| fib (control) | 56.4 | 56.0 | -0.6% | -0.4% |
| collatz | 86.3 | 83.8 | **-2.9%** | -2.8% |
| sieve | 195.2 | 197.6 | +1.3% | +2.5% |
| hashmap | 97.8 | 97.0 | -0.8% | -0.6% |
| strings | 50.4 | 50.3 | -0.1% | -0.3% |
| mandelbrot | 45.1 | 43.9 | **-2.5%** | -2.4% |
| n-body | 75.5 | 75.5 | -0.0% | -0.1% |
| binary trees | 915.2 | 908.1 | -0.8% | -0.2% |

Even removing **all** of them is worth at most 2.9% on collatz and 2.5% on
Mandelbrot, is negative on sieve, and is inside the control's spread everywhere
else. Sieve is the instructive one: it has roughly 60M list indexes and 50M
inline increments, yet dropping every bounds and overflow check does not make
it faster — those loops are bound by list memory traffic and the index type
checks, not by the three-instruction bounds compare or the `jo`.

The specific `while (i < len(xs)) { xs[i] }` idiom is equally disappointing in
a dedicated microbenchmark. Removing every bounds check from these loops (same
unsound build) over 101 paired runs:

| Microbenchmark | baseline ms | no bounds check, ms | change | paired median | minimum |
| --- | --- | --- | --- | --- | --- |
| [list_loop](check-elimination/list_loop.may), sum 1M `List<Int>` | 8.39 | 8.23 | -1.8% | +1.9% | 5.69 / 5.71 |
| [list_store](check-elimination/list_store.may), write + read 1M | 15.73 | 15.67 | -0.4% | -0.9% | 12.78 / 12.65 |

The paired median and the side medians disagree in sign and the minima are
equal: the bounds check is below this workload's noise, because a sequential
list walk is dominated by the element load and the index type checks. A tight
loop written to expose the check would need to defeat the memory traffic, which
is not what real code looks like.

**Conclusion:** the ceiling for the whole item is ~3% on two benchmarks and zero
or negative elsewhere. A sound analysis proves a strict subset of those sites
(it cannot prove sieve's `i < 10000000` index into a list whose length it does
not know), so the realised win would be smaller than the noise floor. Not
implemented in this increment. The measurement also explains why: eliminating
these checks targets instruction count on loops that are memory- and
type-check-bound.

## LICM — implemented, measured, reverted

A loop-invariant field-read hoister was implemented in `src/ir_opt.may` and
removed again after measurement. It moved `E_GET` reads (and the `E_VAR` read
of the receiver) to just before the loop header when:

- the loop is a straight back-edge (`while`) with no exception region in the
  function, and the fat-value path is active;
- the receiver binding does not change in the loop and exists before the
  header (or the receiver temp is already defined before the loop);
- no `S_SETPROP` in the loop writes the same field name (safe under aliasing:
  only a store to that field can change that field's value);
- the receiver does not escape: the function-level escape analysis marks values
  passed to non-pure calls, stored into containers, captured by closures or
  whose source list escaped. Only read-only builtins and read-only runtime
  calls (`len`, `str`, conversions, math, `rt_len`, `rt_index_get`, ...) let
  their arguments stay unescaped;
- a global receiver additionally requires the loop to contain no call, runtime
  call, indirect call or closure (any of them can assign a global).

Moving `E_GET` is safe from a fault point of view because the fat field read is
total: the fixed-slot path falls back to the cache probe and then to
`rt_field_get`, which returns nil for a non-record, non-map receiver. Hoisting
therefore only changes how often a pure, non-faulting read runs. After the move
the normal propagation/CSE/dead-code passes run on the rewritten function.

On the eight xlang sources only n-body has eligible reads: the `b.mass`,
`b.x`, `b.y`, `b.z` reads inside `advance`'s inner `j` loop (the loop body
stores `vx`/`vy`/`vz`, not those fields) and `b.*` inside `energy`. The
prototype moved 12 instructions in `advance` and 8 in `energy`, and regenerated
`advance` +4.6% larger statically. Measured on n-body, 61 paired runs:

| n-body | baseline | with LICM | change | paired median | minimum |
| --- | --- | --- | --- | --- | --- |
| CPU time, ms | 76.46 | 80.21 | **+4.9%** | **+3.4%** | 73.94 / 76.35 |

It is consistently slower, not just noisy: the minimum is 3.3% worse too. The
reason the theoretical saving did not appear: hoisting six typed field reads out
of a four-trip inner loop moves their (large — slot check plus inline cache
fallback) code into the five-trip outer body, the block-local CSE that runs
afterwards cannot merge the three separate `b.mass` hoists because their
readers are in the loop body, and the hoisted `Float` results now live across
the loop (frame loads instead of being consumed in the held slot). The inner
loop is memory-bound enough that the saved reads do not cover it.

**Conclusion:** reverted. A profitable LICM would need cross-block value
numbering (so the repeated `b.mass` hoists become one read) and a hotness
argument for hoisting over a low-trip-count inner loop; that is a larger
change than this increment, and on the current workload set it is not
justified.

## Reproduction

- Ceiling build: remove the two bounds-compare blocks in `fat_index_load` /
  `fat_index_set` and the two `jo` emissions in `fat_binary` /
  `fat_binary_immediate` (temporary, unsound; do not commit), rebuild with
  `sh compiler/rust/build.sh`, compile the benchmarks, then compare the two
  binaries interleaved. The base compiler used was the build of `40ae868`
  (sha256 recorded in the raw file).
- LICM: the prototype is described above; its samples are the `licm` section of
  the raw file. It was reverted.
- Checks run on the delivered (reverted) branch: build, `verify.py` 138/138,
  `raw_codegen.py`, `backends.py`, `oracle.py` 61/61, `compiler/rust/test.py`
  twice with byte-identical stage 2/3, and `make check`.

Raw samples: [check-elimination.json](check-elimination.json) — suite ceiling
(25 pairs), list-loop microbenchmarks (101 pairs), LICM n-body (61 pairs),
compiler identity and host load.
