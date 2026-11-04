# Collector pause and the default threshold policy — issue #135

Status: two measured changes, both default-on and both in
`runtime/fat_linux.may` (no compiler-source change). On binary trees depth 16
at the default 256 MiB nominal heap, paired against the pre-change compiler:

| | before | after | delta |
| --- | ---: | ---: | ---: |
| CPU time (wait4 user+sys) | 0.9138 s | 0.8345 s | **-8.7%** |
| peak RSS (`ru_maxrss`) | 236 MiB | 146 MiB | **-38%** |
| collections | 11 | 16 | +5 |
| total pause (`MAYC_GC_STATS`) | 352 ms | 248 ms | -30% |

The other seven roadmap workloads are unchanged within the run-to-run spread
(worst case sieve +1.2%, re-measured at +0.6% over 100 pairs), because they do
not reach the default 128 MiB first threshold and therefore never collect. The
change is also a small compiler win: compiling `compiler/mayc/main.may` takes
5.0% less CPU with an unchanged compiler peak RSS.

This report also records the pause profile that motivated the collector change,
the threshold measurements behind the policy change, the opt-in tuned policy
under the new default, and two measured negatives.

## 1. Where a collection's pause goes

A temporary instrumented copy of the runtime (per-collection
`clock_gettime` around the root scan, the mark drain and the sweep, plus
candidate-probe and mark counters) was built in a scratch directory and was not
committed. On trees at the default policy, over the 11 collections:

| phase | share of pause | evidence |
| --- | --- | --- |
| roots (stack, registers, globals, fibers) | <2% (<1 ms total) | phase timer |
| mark drain | ~35% (~250 ms total) | phase timer |
| sweep | ~65% (~470 ms total) | phase timer |

The mark drain was dominated by the conservative treatment of kind-4 records.
`rt_alloc_record(n)` allocates a 48-byte map header followed by `n` 32-byte
entries, and the old drain scanned the header as six words and then every entry
as two 16-byte fat slots (the key pair and the value pair). For the depth-16
tree's 131,071 records per collection that is 10 conservative word probes per
record, and the counter in the instrumented build measured **2,493,009
`rt_candidate` probes per collection**. Only 131,123 of them could ever
succeed: the entries pointer inside the block, the key payloads (field-name
strings in the image) and the record's small integer header words all fail the
allocation-start test, and each failing probe still touches the 1-byte-per-heap-
word `GCSTARTS` table.

## 2. Change: trace sealed records directly, and keep the global-root table out
of the scan

Two runtime edits, measured together in isolation (same compiler, a copied
runtime with only these edits, 30 interleaved pairs on trees):

**2.1 Sealed records.** A record whose entries are still in its own block and
which has no hash table has only one kind of pointer that can point into the
heap: the value slot of each entry. The mark drain now recognizes that shape
with two header loads (`entries == p + 48`, `hash table == 0`) and scans each
32-byte entry's value slot (`p + 48 + 32i + 16` type, `+24` payload) instead of
probing the header and both key words. The key is always an image field-name
pointer, never a heap pointer, and the rest of the header is the count, the
capacity and the in-block entries pointer. A record that later grows through a
dynamic field write (`rt_map_put`) moves its entries out of the block, so it
fails the test and keeps the old conservative scan; the inline constructor path
in the backend emits the same zeros for the hash-table fields, which it already
relied on the runtime zeroing to do.

**2.2 Global roots as a byte block.** `rt_gc_root` allocates a 1 MiB table for
the addresses of registered global slots. The collector marks the table with
`rt_mark_word` and walks the registered addresses itself, but the table was
allocated as a word block, so every cycle also conservatively probed all
131,072 words it contains. They are data-segment addresses, never heap
pointers, so the table is now `rt_alloc_bytes(1048576)` (kind 2, marked but not
scanned). That removes a fixed ~262,000 candidate probes per collection.

Counters in the instrumented build, same trees run: candidate probes per
collection fell from 2,493,009 to 132,948 (-95%), and the mark phase total over
the 11 collections fell from ~250 ms to ~35 ms. End to end, the two edits alone
are **-10.5% CPU on trees** (30/30 paired samples; `collector_fast_paths_only_pair`
in the raw JSON). The sweep is untouched and becomes the majority of the
remaining pause.

## 3. Change: bound the post-sweep threshold at the frontier itself

The old post-sweep policy was

    next = max(HEAP + 2*live + GCMARGIN, HEAP + GCMIN, HP + GCMARGIN)

The `HP + GCMARGIN` term is the cause of the frontier creep measured in
[STACK_MAPS.md](../../../../docs/design/STACK_MAPS.md) §1.4: a collection on
trees always fires in the middle of a tree construction, the newest records are
live and the top of the heap cannot be rewound, so the frontier rises by one
margin per collection. With the default 128 MiB floor and 8 MiB margin that is
`128 + 11 * 8 = 216 MiB` of extent plus overhead — the 234 MiB peak.

The new policy keeps the same inputs but bounds the threshold at the frontier
instead of a margin above it:

    next = max(HEAP + 2*live + GCMARGIN, HEAP + GCMIN, HP)

This is not the same as dropping the term: `HP` is still a lower bound, so the
stored threshold never sits below the allocation frontier (the heap invariant
asserted by `gc_stress.py` still holds). Allocations continue from the blocks
the sweep just freed, and a collection starts only when the free list cannot
satisfy a request. The rare request that still does not fit above the threshold
is given room by the allocator's existing fallback
(`HEAPEND = HP + need + GCMARGIN`), so a collection that frees nothing useful
cannot livelock the program.

Measured per-sweep trace on trees at the default policy, instrumented runtime
(`creep_trace_default` in the raw JSON): the post-sweep extent and threshold
are pinned at exactly 128.00 MiB for all 16 collections instead of climbing
128, 136, ..., 208 MiB. Peak RSS drops from 236 to 146 MiB. Collection count
rises from 11 to 16 (1.45x, not the 5x the tuned floor+margin policy costs) and
the total pause falls anyway (352 -> 248 ms) because the smaller extent makes
each sweep cheaper.

### Policy table on trees

Each row is the same binary with environment overrides, five runs, `MAYC_GC_STATS=1`
for collections/pause/RSS; time is the median of five CPU-time samples
(absolute times move with host load; compare rows comparatively).

| policy | CPU s | peak RSS | collections | total pause |
| --- | ---: | ---: | ---: | ---: |
| old default (pre-change runtime) | 0.917 | 236 MiB | 11 | 352 ms |
| **new default** | 0.876 | **146 MiB** | 16 | 248 ms |
| `MAYC_GC_MARGIN=1MiB` | 0.853 | 146 MiB | 16 | 267 ms |
| `MAYC_GC_MIN=64MiB` | 0.956 | 104 MiB | 38 | 397 ms |
| `MAYC_GC_MIN=64MiB MAYC_GC_MARGIN=1MiB` | 0.973 | 116 MiB | 38 | 403 ms |
| `MAYC_GC_MIN=32MiB MAYC_GC_MARGIN=1MiB` | 1.215 | 114 MiB | 85 | 661 ms |
| `MAYC_GC_MIN=8MiB MAYC_GC_MARGIN=512KiB` (tuned) | 1.226 | 116 MiB | 89 | 639 ms |

The frontier bound is what makes the default policy stop paying the 8 MiB
creep. Lower floors trade time for RSS below that; they are not made default
because the six workloads that never collect at 128 MiB would start collecting
(`hashmap` 0 -> 7 collections at 8 MiB, `strings` 0 -> 7, and those two pay
1.3x and 2.9x time, see the opt-in table below).

The `gc_policy` limits case (`limits.py --mode gc --gc-case gc_policy`) still
passes: on its 4 MiB heap the default collects 3 times at a 2,375,936-byte
threshold instead of the old 2,626,656, and the tuned policy still collects
more often at a lower threshold. The prose numbers in
[gc-policy.md](gc-policy.md) that quote the old default threshold and the
"defaults unchanged" status are superseded by this report; the overrides
themselves still work.

## 4. All eight workloads, default policy

Builds made by the pre-change compiler (pristine runtime sidecars) and the
post-change compiler (new sidecars), same source and same compiler otherwise;
interleaved ABAB, CPU time from `wait4`, peak RSS from `ru_maxrss`, identical
program output required and verified. Samples per side: 60 fib, 40 collatz,
30 sieve, 30 hashmap, 40 strings, 40 mandelbrot, 40 n-body, 30 trees.

| workload | CPU before | CPU after | delta | wins | RSS before | RSS after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fib | 0.0596 s | 0.0597 s | +0.2% | 29/31 | 11.7 MiB | 11.7 MiB |
| collatz | 0.0435 s | 0.0434 s | -0.3% | 21/19 | 11.6 MiB | 11.6 MiB |
| sieve | 0.1974 s | 0.1998 s | +1.2% | 20/10 | 18.0 MiB | 18.0 MiB |
| hashmap | 0.0870 s | 0.0861 s | -1.0% | 7/23 | 72.0 MiB | 72.0 MiB |
| strings | 0.0442 s | 0.0445 s | +0.9% | 29/11 | 66.0 MiB | 66.0 MiB |
| mandelbrot | 0.0445 s | 0.0443 s | -0.4% | 16/24 | 11.7 MiB | 11.7 MiB |
| n-body | 0.0811 s | 0.0807 s | -0.5% | 13/27 | 11.7 MiB | 11.7 MiB |
| binary trees | 0.9138 s | 0.8345 s | **-8.7%** | 0/30 | 236.0 MiB | **146.0 MiB** |

The only surviving wobble is sieve at +1.2% over 30 pairs; a 100-pair re-run of
the same builds gives +0.6% (66/34), i.e. a binary-layout effect inside the
known ±2% spread, not a policy effect — sieve does not collect. No workload
regresses beyond that spread. The seven non-collecting workloads also allocate
below 128 MiB, so their peak RSS is the allocation extent and cannot change
without changing the default floor; the raw pair JSON records their equality.

### Compiler throughput

The compiler itself embeds the runtime when it is built, so the change was
measured by having the pre-change and post-change compiler compile the same
large input, five interleaved runs each:

| input | compiler CPU before | after | delta | compiler peak RSS |
| --- | ---: | ---: | ---: | ---: |
| `compiler/mayc/main.may` | 2.678 s | 2.543 s | **-5.0%** | 478.3 -> 478.3 MiB |
| trees.may (84 ms compile) | 0.0842 s | 0.0881 s | +4.6% | 110.6 -> 110.7 MiB |

The self-compile (the case that matters for the build) is faster and uses the
same peak RSS; the small compile is inside the layout noise of an 84 ms run.

## 5. Opt-in: the tuned floor+margin policy under the new default

Measured with `stack_retention.py --xlang --compare --runs 6`, i.e. an
instrumented runtime that reports per-sweep values, alternating base and tuned
environment on the same binary; times are whole-process wall time of that
instrumented build:

| workload | time base | time tuned | peak RSS base | peak RSS tuned | collections |
| --- | ---: | ---: | ---: | ---: | ---: |
| trees | 0.712 s | 1.083 s | 146 MiB | 108 MiB | 16 -> 90 |
| hashmap | 0.096 s | 0.124 s | 72 MiB | 52 MiB | 0 -> 7 |
| strings | 0.047 s | 0.135 s | 66 MiB | 46 MiB | 0 -> 7 |
| other five | within 1% | within 1% | unchanged | unchanged | 0 -> 0 |

`MAYC_GC_MIN=8388608 MAYC_GC_MARGIN=524288` still selects the small-heap
behaviour, and it is now cheaper than the 1.75x-1.9 s recorded in
[gc-policy.md](gc-policy.md): trees is 1.08 s instead of 1.90 s at 108-116 MiB
instead of 95 MiB, and hashmap/strings keep most of their RSS win. The frontier
bound also reaches the small-threshold regime without the old creep: the tuned
trace settles at a 34.5 MiB extent for the first ~74 collections and only grows
in the final depth-16 iterations (`creep_trace_tuned` in the raw JSON).

## 6. Remaining gap to the acceptance targets

Acceptance: binary trees within 3x Java time (~0.6 s) and within 2x CPython peak
RSS (~42 MiB). Current: 0.835 s CPU and 146 MiB.

- **Time.** The 16 default collections cost ~248 ms of pause, so the mutator
  alone is ~0.59 s. The target is therefore reachable only by making collection
  pause close to free, not by tuning the threshold: the sweep is now ~65% of
  the remaining pause and it is bandwidth-bound (walking the whole extent by
  block headers). That is the precise-stack-map + moving/nursery collector
  direction, out of scope for this session.
- **RSS.** 146 MiB is the 128 MiB first threshold plus ~18 MiB of working set:
  the default floor is now the binding term. 42 MiB needs a floor near the live
  set (`2*live + margin`), which today costs 38-89 collections (104-116 MiB at
  0.96-1.23 s in the policy table) and makes the six currently non-collecting
  workloads collect. Getting from ~104 MiB to 42 MiB needs the same
  precise/moving collector work: the tree-under-construction live set plus the
  long-lived tree is ~34 MiB at the trigger point and no non-moving policy can
  sit much below that.

So this increment improves both sides of the trade-off at once on the binding
workload, but the acceptance targets still require the collector architecture
change that [STACK_MAPS.md](../../../../docs/design/STACK_MAPS.md) §5 and §7
describe. The default floor is the remaining RSS lever that can be pulled
without codegen work, and the policy table above gives its measured curve.

## 7. Honest negatives

- **Skipping the record zeroing on allocation** (`rt_claim`/`rt_alloc_kind`
  skip the 112-byte `rt_zero` for kind 4, with the constructor writing the three
  header words instead): -7.8% CPU on trees in isolation, -19.4% together with
  the fast paths, but partially constructed records then conservatively retain
  stale payload words. Compiling `compiler/mayc/main.may` with that runtime kept
  the same CPU only by giving up the collector win and raised the compiler's
  peak RSS from 478 to 492 MiB. The stale-hash-table field also broke the
  backend's inline record constructor (it relies on `rt_alloc_record` zeroing);
  that was found by `verify.py` during this work and would have needed a codegen
  change to fix. Reverted; not included.
- **Restructuring the sweep's `GCSTARTS` clearing** (clear each freed run's
  byte range in a tight loop after the walk instead of one store per free
  block): +1.6% CPU on trees, and removing the table store entirely only buys
  ~3.5%. The sweep is limited by walking the extents and touching block
  headers, not by the table stores, so the loop shape was left alone. Both
  numbers are from scratch variants, not committed.
- **A 1 MiB default margin with the old frontier term**: peak RSS moved
  236 -> 161 MiB at +9% CPU — dominated by the frontier bound below, which
  reaches 146 MiB at no time cost.

## 8. Reproduction

```sh
sh compiler/rust/build.sh

# Eight workload pairs: compile each with a pre-change compiler copy (its old
# runtime sidecars restored) and this tree's compiler, then
python3 compiler/mayc/tests/stack_retention.py --pair OLD/new/trees \
    --pair-runs 30 --cpu 6 --json /tmp/pair-trees.json

# Policy table on trees (default vs overrides), five runs each.
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --workload trees --heaps 256 --json /tmp/creep-default.json
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --workload trees --heaps 256 \
    --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288 --json /tmp/creep-tuned.json

# Eight workloads base vs tuned opt-in (instrumented runtime).
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --xlang --compare --runs 6 \
    --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288 \
    --json /tmp/policy-compare.json
```

Raw samples, per-sweep traces and the gate record:
[gc-pause-performance.json](gc-pause-performance.json).

Caveats: the machine is shared and the absolute CPU times drift between
measurement sessions; the paired ratios and the RSS values are the meaningful
numbers. `ru_maxrss` includes the resident image (~11 MiB) and the runtime's
reservation is committed on demand. The pause profile used a scratch
instrumented runtime; its phase timers and counters are not in the committed
runtime.

Files changed: `compiler/mayc/runtime/fat_linux.may` (`rt_gc_root`,
`rt_gc`'s mark drain, `rt_threshold`). `docs/internals/GC.md` and
[gc-policy.md](gc-policy.md) still describe the old `HP + GCMARGIN` policy and
should be updated by the integration owner.
