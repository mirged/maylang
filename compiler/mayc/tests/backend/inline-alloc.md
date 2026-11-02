# Inline allocation — issue #135

Small-object construction used to call into the runtime for every allocation.
This report records what happens when the construction sites the compiler can
size at compile time allocate inline: the bump branch of `rt_alloc_kind`, and
an exact-size free-bin claim when one exists, with `rt_alloc_kind` as the
fallback for everything else. **The measured result is neutral on the roadmap
workloads and slightly slower on several controls, so the change is not
recommended for merging on performance grounds and was dropped rather than
merged.** The code and the fixture live on branch `perf/gc-135` (commits
`9b1323a` and this report's commit); the mechanism, the two defects the heap
audit found and the measurements are recorded here because the diagnosis is
useful for future allocation work.

## Mechanism

The experiment added `fat_alloc_fast` (`src/backend/x86_64_fat.may`), which
recognizes the `IR_RUNTIME`
sites whose block shapes are known at compile time and whose size argument is a
constant: `rt_map_new`, `rt_map_new_sized`, `rt_struct_new` and the list
constructors `rt_list_new`/`_int`/`_float`/`_bool`. For those it emits either

- the bump path: `HP + total <= HEAPEND`, `FREECOUNT == 0`, `GCSTATS == 0`,
  then advance HP, raise `HEAPDIRTY`, write both headers (size, magic word and
  the `GCSTARTS` kind byte), zero the second block's payload and write the
  fixed header fields; or
- the size-class path: when the exact bins `need1/8` and `need2/8` are both
  non-empty, pop and claim the blocks, decrement `FREECOUNT`, and advance
  `FREEBIN_LOW` past the bins the claim emptied.

Everything else — statistics on, a larger reclaimed block the runtime splits, a
full chunk (which may collect), a non-constant size — jumps to the original
runtime helper with the arguments pushed exactly as before. Both paths copy the
runtime's block sizes, kind bytes, magic word and zeroing, so whenever a fast
path is taken the heap is bit-identical to the runtime call. The counters make
that checkable: with `MAYC_GC_STATS=1` (statistics also force the fallback) the
`GC collections/allocated/live/peak/threshold` numbers are identical before and
after on every workload below.

The fast paths are skipped under `--no-opt`.

Two defects found while validating the first version are worth recording:

- the block base register was advanced to the new frontier before the header
  writes, so headers landed one block late (caught by a heap audit at the first
  collection);
- the second block's kind byte reused the register that the field stores had
  already overwritten, leaving the entry array unmarked (caught by the same
  audit: 34 of 34 marked maps had an unmarked entry array).

An earlier bump-only version (no size-class path) was 10% slower on binary
trees, because after the first collection most allocations reuse a freed block
from a size class, and the check overhead before falling back was pure cost.
The size-class path fixed that, but it also has to maintain `FREEBIN_LOW` — a
version that did not was 3.5x slower, since `rt_fit` then scans empty bins.

## Measurements

Intel i5-13500H, Linux 6.12, full runtime, whole-process wall time, whole
benchmark runs interleaved before/after, 5 samples each, identical output.
"before" is a compiler built from `f8b716b` (the integration tree that already
has the fixed-slot records of #134 and the register direct calls of #132);
"after" is the experiment branch (not merged) on the same base. Both were
built from source; the
runtime sidecars are unmodified and shared.

| Benchmark | before, ms | after, ms | change |
| --- | --- | --- | --- |
| fib | 57.8 | 57.1 | -1.3% |
| collatz | 87.7 | 87.9 | +0.2% |
| sieve | 191.6 | 196.4 | +2.5% |
| hashmap | 93.7 | 91.4 | -2.5% |
| strings | 44.3 | 47.4 | +7.1% |
| mandelbrot | 46.2 | 46.0 | -0.5% |
| n-body | 89.3 | 92.7 | +3.8% |
| binary trees | 1037.3 | 1020.0 | -1.7% |

Binary trees is the only allocation-heavy workload, and it is the number this
issue is about: **-1.7% is inside the run-to-run spread** (a separate 10-run
interleaved sample put it at 1012.0 vs 1009.0 ms, i.e. -0.3%). The other
workloads do not allocate in their hot loops; the ±2-7% is layout noise from
the larger code, not an allocation effect.

Peak RSS is unchanged everywhere: at the end of binary trees both builds report
`peak=218103712 rss_kb=241792/241796`, with identical collection counts
(11), allocated bytes (1,885,689,824) and live bytes (41,946,144). The string,
hashmap and sieve buildings also match exactly.

An allocation-only microbenchmark (`{"a": i, "b": i + 1}` 3M times with a heap
large enough that no collection runs) shows what the bump path is worth when it
is actually taken: 347.3 to 303.1 ms, **-12.7%** (12 runs each). With the
default heap and three collections, the same program is 370.0 to 362.8 ms
(-1.9%), because the collections hand most allocations to the size-class path.

The compiler image grows 3,110,552 to 3,628,112 bytes (+16.6%): every
construction site carries both allocation branches inline.

## Tests

These checks ran on the experiment branch, where `tests/inline_alloc.may` and
its pinned entry exist; neither the fixture nor the code is part of this tree.

- `tests/inline_alloc.may` exercises struct, map and list construction (all
  list element kinds), empty and grown maps, nested records, and a live set
  kept across six collections; its output is pinned in
  `tests/legacy_behavior.json`. `oracle.py` requires the same output with and
  without `--no-opt`.
- `make test-compiler` (138 checks), `gc.py` (including the #134 record probe),
  `gc_stress.py` (seeds 1, 7, 42 × 300 steps), `limits.py --self-test
  --runtime-gc-stats`, `raw_codegen.py`, `backends.py` and the bootstrap
  fixpoint (stage 2 = stage 3) pass.
- The reduced-heap probes used during validation are not committed: a GC
  churn program that builds trees and keeps maps alive across collections, run
  with `sz` reduced to 8 MiB, reproduces the marking defects above quickly.

## Conclusion

Inline allocation only pays where the bump path is taken, i.e. in programs that
allocate without collecting. Once the collector runs, the size-class path
dominates and the saved call is offset by the claim and `FREEBIN_LOW`
bookkeeping; larger, hotter runtime helpers (map insertion, record slot
writes, list growth) hide the remaining call overhead. A profitable next step
is to inline those helpers' *initialization* as well, or to allocate whole
construction sequences (record plus its fields) in one place, rather than
extending the allocation fast path alone.

Raw samples: [inline-alloc-performance.json](inline-alloc-performance.json).

Compiler identity: before `918e96e5…` (3,110,552 bytes), experiment
`583e208e…` (3,628,112 bytes). Runtime sidecars unchanged (`fat.may`
`1a4c10aa…`, `fat_linux.may` `40409a6f…`).
