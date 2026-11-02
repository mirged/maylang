# Inline record construction — issue #135

Small-object construction used to pay a runtime call for every record slot.
[inline-alloc.md](inline-alloc.md) tried to inline the *allocation* and measured
it neutral-to-negative, concluding that the profitable direction was inlining
construction *initialization* or allocating whole construction sequences. This
is that experiment for fixed-slot struct and enum construction: the allocation
stays a runtime call, and the header writes plus every slot write are emitted as
one generated block. **It pays: the construction-heavy workloads drop 18-36% in
CPU time.** The compiler's own self-compile is 4% slower with 2.3% more peak RSS
in this experiment; that trade and its evidence are recorded below.

## Mechanism

A struct or enum constructor is a generated function whose body is a record
literal (#134). It lowers to `rt_struct_new(n)` and one `rt_struct_set` per
entry, so building an `n`-field record was one allocation call plus `n` calls
that each pushed four fat values (eight words) and entered a trampoline.

`fat_record_new` and `fat_record_set` (`src/backend/x86_64_fat.may`, #135) now
recognise that sequence in the constructor body while it is emitted:

- `rt_struct_new` with a forwarded constant size, inside a constructor body:
  push the size and call `rt_alloc_record(n)`, then set the type word to 6 and
  write `rt_struct_new`'s header directly (`count = n`, `capacity = 2n`,
  `entries = p + 48`). The hash-table fields at 24 and 32 are left zeroed, as
  the runtime leaves them, because the allocator zeroes every payload.
- the `rt_struct_set(record, slot, key, value)` calls that follow for the same
  temporary: load the record, the key and the value and write the entry's four
  words at `p + 48 + 32 * slot` with no runtime call.

Everything unproven keeps the old path: a size that is not a forwarded constant,
a size above 4096 slots, a slot that is not a constant or arrives out of order,
a set that does not follow its own `rt_struct_new`, and `--no-opt`. The
`FAT_RECORD_STACK` keeps the records whose header this body wrote while their
slots fill, so nested record constructors (an inner record completes before the
outer record's next slot) and their fallbacks stay matched.

Evaluation order and effects are unchanged: `rt_struct_new` still happens at the
same point (before the constructor arguments' values are written in the body),
each slot write happens where the call was, and only the call boundary between
them disappears. The allocation itself deliberately stays a runtime call: gc-135
already measured that inlining the bump/free-bin path is not where the time
goes, and the runtime call is what keeps the collector, the allocation counters
and the zeroing exactly as they were.

The heap and the collector are untouched. The block is the kind-4 record block
of [STRUCT_LAYOUT.md](../../../../docs/design/STRUCT_LAYOUT.md): a 48-byte map
header, the entries at `p + 48` on the payload's 16-byte grid, and a hash table
that stays empty. The header is written immediately after the allocation and
before any value evaluation, and the allocator zeroes the payload, so a
collection during construction sees `count = n` with nil entries exactly as it
did before. The bytes written are the bytes `rt_struct_set` writes, in the same
order, so the heap is bit-identical whenever the fast path is taken.

## Measurements

Intel i5-13500H, Linux 6.12.113, full runtime, `struct_slots/run.py`: each
compiler builds every workload, all outputs must match, then interleaved rounds
(alternating the order) record whole-process wall time, user+system CPU time and
peak RSS, every child pinned to CPU 4 with `taskset`. Three separate runs of 7
rounds for the workloads (21 samples per side) and a separate 15-round run for
the self-compile row. The machine ran other builds throughout (load average 3.7
to 6.8), so the table gives the least-contended (minimum) CPU sample per side,
as [struct-slots.md](struct-slots.md) does; medians and RSS are in the raw
samples. "before" is a compiler built from `62c3c45` (the integrated base) with
its own sidecars; "after" is this change. Both are `mayc 0.15.0`; the runtime
sidecars are unchanged.

| Workload | Before, ms (min CPU) | After, ms (min CPU) | CPU change | Wall change |
| --- | ---: | ---: | ---: | ---: |
| `trees`, binary trees depth 16 | 974.7 | 802.6 | **-17.7%** | -14.9% |
| `construct`, 2M two-field constructions | 93.4 | 72.0 | **-22.9%** | -18.9% |
| `record_gc`, short-lived records over a live tree | 302.6 | 195.0 | **-35.6%** | -19.6% |
| `nbody`, 5 bodies × 200k steps | 75.3 | 74.8 | -0.7% | +0.7% |
| `read_field2`, 5M typed field reads (control) | 9.0 | 8.8 | -2.4% | -4.0% |
| `read_local`, field reads of a local (control) | 4.1 | 4.0 | -1.0% | -4.9% |
| `self_compile`, mayc compiling its own source | 2222.5 | 2330.8 | +4.9% | +4.0% |

The construction-heavy workloads are where the calls were: `trees` and
`construct` build one- and two-field records in their hot loops, and
`record_gc` churns three-field records while a tree stays live. `nbody`
constructs only its five bodies at startup and then spends all its time on
field arithmetic, and the two read controls construct one record (or none)
before their loop, so they stay inside the spread (-1% to -2.4% is layout
noise, see below).

**Self-compile.** The 15-round run is consistent: the after side is 4.0% slower
by median CPU and 4.9% by minimum, with peak RSS 441.7 to 451.8 MiB (+2.3%).
The two compiler binaries are different programs (one calls the runtime for
construction, one writes the slots inline), so the change also changes the
compiler's own heap retention: with conservative stack scanning, a different
code shape retains a different live set, and the collection threshold follows.
This is a real cost of building the compiler with the change, not a change in
what the compiled workloads allocate (their counters are identical, below). It
was not chased further; medium-file compiles are mixed (-6% to +16% across four
examples, dominated by the same layout noise) and the construction workloads win
by far more than the self-compile loses.

Peak RSS for every workload is unchanged: `trees` 239,644 KiB on both sides,
`record_gc` 184,340, `construct` 147,472, `nbody` 18,908. The one exception is
self-compile, above.

**Image size.** The compiler image grows 2,964,768 to 2,981,408 bytes (+0.56%)
because the header writes and slot stores are now in every constructor body and
the runtime record helpers become unreachable; a compiler self-compile emits
2,977,384 bytes before and 2,981,408 after (+0.14%) for the same source. Workload
images mostly shrink slightly because `rt_struct_new`/`rt_struct_set` (and, for
`construct`, map helpers that the record path no longer reaches) leave the
image: `construct` 109,912 to 105,736 (-3.8%), `trees` 110,384 to 110,304,
`record_gc` 110,128 to 110,048, `nbody` 142,944 to 142,872.

**Heap counters (MAYC_GC_STATS).** With statistics on, every workload binary
reports the same collections, allocated bytes, peak and threshold, and the same
live bytes except where conservative stack retention differs by construction
shape:

```
trees          before: collections=11 allocated=1885689824 live=41946016 peak=218103712 threshold=226492320
               after:  collections=11 allocated=1885689824 live=41945632 peak=218103712 threshold=226492320
record_gc      before: collections=5  allocated=789171376  live=6484848  peak=167771184 threshold=176159792
               after:  collections=5  allocated=789171376  live=6484848  peak=167771184 threshold=176159792
record_construct (fixture, no collection)
               before: collections=0  allocated=33058176   peak=33062608
               after:  collections=0  allocated=33058176   peak=33062608
```

Raw samples, image sizes and the full counter lines:
[construction-inline-performance.json](construction-inline-performance.json).

## Tests

- `tests/record_construct.may` pins the fast path's shape: an eight-field record
  (a slot past the disp8 range), nested records, enum variants with and without
  payload, argument evaluation order and effects, growth through an `Any` alias
  and a write after that growth, a fault while an argument is evaluated and
  recovery, observation through keys/indexing/`to_map`/display/JSON, and 200k
  constructions. Its output is pinned in `tests/legacy_behavior.json`.
- `tests/oracle.py` requires the same output with and without `--no-opt`, i.e.
  the inline block against the runtime calls, for every fixture; the existing
  `record_layout.may`, `record_dup_keys.may`, `enums.may` and
  `field_cache.may` fixtures also compare byte-identical across the base
  compiler, the optimized build and the `--no-opt` build.
- `make test-compiler`: 139 checks pass. `gc.py` passes including the #134
  record-slot probe (the collector still traces grown records' moved entries and
  hash table), `gc_stress.py` passes its seeds, and `raw_codegen.py`,
  `backends.py` and `make test-compliance` pass.
- `make test-bootstrap` passes twice: source-only stage 2 = stage 3 with the
  inline construction in place, and the compiler's self-compile is
  deterministic (three identical images).

## Risks and limits

- The generated block duplicates `rt_struct_new`'s header wiring. The runtime
  layout and the backend must stay in sync; both are commented with a pointer to
  [STRUCT_LAYOUT.md](../../../../docs/design/STRUCT_LAYOUT.md), and a layout change
  must update `fat_record_new` in the same commit.
- Only the full fat runtime is in scope (Linux x86-64), as everywhere.
- The constructor body is assumed to be the straight-line record literal the
  parser generates. The backend still verifies each call and falls back when the
  shape or a constant is not what it proves, so a different lowering keeps
  working, just without the fast path.
- A record that later grows through an `Any` alias moves its entries out of the
  block and behaves exactly as before; the fixture covers the observation and a
  write after growth.
- The compiler self-compile cost above is the main trade: a 4% slower compiler
  build (and 2.3% more peak RSS) for 18-36% faster construction-heavy
  workloads. If the project values compiler throughput over the benchmark
  suite, gate or revert this; the mechanism is self-contained in the fat
  backend.
