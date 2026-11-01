# MOSAIC GC roadmap

Status: research proposal. Nothing here is implemented. This plan replaces
[Phase 5](PERFORMANCE_ROADMAP.md#phase-5-allocation-and-collection) of the
performance roadmap only if the research gate in M1 passes; every step before
that gate also pays off for a conventional collector.

MOSAIC (Mortality-Oriented Segmented Allocation and Intelligent Collection)
groups objects that are expected to die together into **cohorts**, keeps a
graph of references *between cohorts*, and reclaims whole unreachable cohorts
without tracing their members. The bet, in one line:

> If a program's objects can be grouped so that the number of cohorts `C` and
> of cross-cohort references `E_C` are much smaller than the number of objects
> `N` and references `E`, a collection costs `O(R + C + E_C + D)` instead of
> `O(R + N + E)` (`R` roots, `D` references on dirty cards).

That is a hypothesis about Maylang programs, so the roadmap measures it on
real Maylang allocation traces before building the collector, and keeps the
current collector as the fallback throughout.

## Starting point

The full runtime's collector (`compiler/mayc/runtime/fat_linux.may`,
[GC.md](../internals/GC.md)) is:

- **Conservative and non-moving.** Stacks, callee-saved registers and
  suspended fiber stacks are scanned word by word; `Int` payloads in value
  blocks are also checked, because `cstr`/`addr` pointers travel as `Int`.
  Objects never move, so pointers on the stack never need updating.
- **Mark-sweep over one contiguous heap.** A 1 GiB reservation, a 16-byte
  header (size with the mark bit, then a magic word), and `GCSTARTS`, one byte
  per heap word recording allocation starts and the block kind (words,
  bytes, values). Value blocks are traced precisely by their type words.
- **Bump allocation plus size bins.** `rt_alloc_kind` bumps `HP`, reusing
  swept blocks through 256 size bins (up to 2 KiB) and a free list. Every
  allocation is a call; there is no inline fast path yet.
- **Full collections only.** Each collection marks from all roots and sweeps
  the entire heap. Collection starts at 256 MiB and the threshold grows by
  64 MiB when a collection frees too little.
- **No write barrier, no generations, no stack maps.**
- **One mutator thread.** Fibers are cooperative and switch inside the
  runtime, so there are no thread-local buffers or concurrent mutators.

Things that make MOSAIC easier here than in a JVM:

- The compiler emits every allocation, so each one can carry an exact
  **static allocation-site ID** at no runtime cost beyond an immediate.
- Heap stores go through a small set of paths: `rt_index_set`, `rt_push`,
  `rt_map_set`, `rt_field_set`, `rt_cell` and their callers in
  `runtime/fat.may` and `native.may`, plus the inline list store (#99) and the
  inline field-cache paths (#98) in `src/backend/x86_64_fat.may`. A write
  barrier can be added in one place per path.
- Fibers are a natural **phase signal**: objects allocated by a fiber often
  die when it finishes.

Things that make it harder:

- **Conservative roots.** A stack word that looks like a pointer into a
  cohort keeps that cohort alive, and nothing referenced from the stack can
  move. Fracturing must therefore start non-moving (M5).
- **Raw memory writes.** `store64` and friends can write heap addresses into
  heap memory, and word blocks are scanned conservatively. Either the raw
  store intrinsics apply the barrier when their target is inside the heap, or
  cohorts holding word blocks are always rescanned.
- **The toolchain rule.** Maylang does not link Rust, C or LLVM into the
  compiler or its runtime, so integrating with MMTk is not an option. The
  collector is written in Maylang inside the runtime. Research tooling (the
  simulator) is Python, like the other harnesses.

## Principles

1. **Measure first.** No collector code before the simulator shows learned
   cohorts beating static grouping on real traces (M1 gate).
2. **Never free a live object.** The cohort graph may over-approximate
   reachability, never under-approximate it. A verifier mode compares every
   MOSAIC decision with a full trace (M3).
3. **The current collector stays as the fallback.** MOSAIC is selected per
   cohort and per collection; pathological heaps fall back to full mark-sweep.
4. **Each milestone ships something useful.** M0–M2 improve allocation and
   GC observability even if MOSAIC is abandoned.
5. **Optimizations preserve behavior.** Program output, faults and
   finalization order (there are no finalizers today) stay the same; the
   existing `gc.py`, `gc_stress.py` and `make test-limits` suites must pass
   under every policy.

## M0: measurement and workloads

Goal: know what the current collector costs, on which programs.

- GC telemetry in the runtime, printed at exit with `MAYC_GC_STATS=1`:
  collections, objects and bytes marked, bytes swept, pause time per
  collection (p50, p99, max), peak committed heap, allocation count and bytes.
- A tracked GC workload suite under `compiler/mayc/tests/gc_workloads/`:
  - mayc compiling itself (the largest real heap, close to 256 MiB live);
  - binary trees, hashmap, strings and n-body from the cross-language suite;
  - a `maylsp` session replaying edits (long-lived index plus per-request
    garbage);
  - Mayboard in snapshot mode (UI frames);
  - adversarial cases: a uniformly random object graph, a long-lived cache
    mixed with temporary allocations, and a graph mutated across groups on
    every step. The last two are the cases expected to defeat MOSAIC.
- A benchmark runner that records medians, sample counts and compiler
  identity, as `compiler/mayc/tests/benchmark.py` does, with a Markdown report
  under `compiler/mayc/tests/backend/`.

Exit: a baseline report with GC share of run time and pause distribution for
every workload.

## M1: allocation traces and the simulator (research gate)

Goal: answer "can we predict which objects die together well enough to stop
tracing them individually?" on Maylang's own programs.

- **Trace mode.** A runtime build option (`MAYC_GC_TRACE=path`) that logs, in
  a compact binary format:
  - allocations: object ID, site ID, size, kind, fiber, allocation clock;
  - pointer stores into the heap: source object, slot, target object;
  - each collection: the set of objects found live;
  - fiber start and finish.

  Site IDs come from the compiler (`--gc-sites` passes a per-site immediate
  to the allocation entry points; the default build passes nothing).
- **Simulator** (`compiler/mayc/tests/gc_sim/`, Python). It replays a trace
  under several grouping policies and reports, per collection, objects
  examined, cohort graph size (`C`, `E_C`), dirty-card work (`D`),
  dead-but-retained bytes, and metadata bytes:
  1. object-level mark-sweep (today's collector, the baseline);
  2. static groups: fixed-size allocation windows (a generational proxy);
  3. static groups by allocation site;
  4. static groups by fiber;
  5. learned cohorts: online survival histograms per site and context,
     cross-site co-death clustering, and fracturing.
- **Ground truth.** The simulator's reclaim decisions are checked against the
  trace's live sets; any freed live object is a simulator bug.

**Gate.** Continue to M3 only if learned cohorts (policy 5), on at least four
of the real workloads (not the adversarial ones), beat the best static
policy (2–4) by at least 2× in objects examined per collection, retain at
most 10% more dead bytes than object-level mark-sweep, and keep `E_C` below
one tenth of `E`. Otherwise record the result as a report and take the
conventional path in M2's "if the gate fails" list.

## M2: groundwork useful for any collector

These land regardless of the gate, in this order:

- **Inline bump allocation.** The compiler emits the fast path (load `HP`,
  add, compare with the limit, store) and calls the runtime only on overflow.
  This is already in Phase 5 of the performance roadmap.
- **Segmented heap.** Split the reservation into aligned 64 KiB segments with
  a side table indexed by `(address - HEAP) >> 16`: owner policy, bump cursor,
  live estimate, card bits. `GCSTARTS` stays as the allocation-start oracle
  for conservative roots. Objects above 16 KiB get their own segment runs.
- **Allocation-site IDs** in normal builds, if M1 showed they are useful.
- **Write-barrier audit and card table.** Route every heap pointer store
  (the runtime paths and inline codegen paths listed above, plus raw
  `store64`/`store32` with a heap target) through one barrier: mark the
  source card dirty, 512-byte cards, one byte per card. A debug mode checks,
  at each collection, that every cross-segment pointer lies on a dirty or
  already-summarized card.

If the gate fails, M2 continues with the conventional plan instead of M3:
size-class segments, sticky-mark-bit generational collection using the card
table (non-moving minor collections), and live-bytes-based thresholds.

## M3: static cohorts in the real runtime

Goal: a correct cohort collector with fixed classification, to validate the
mechanics before adding learning.

- **Cohort classes.** Each class has its own bump segment: ephemeral, medium
  and persistent to start with. The class comes from the allocation site,
  using a profile written by M1's trace mode or a compiler heuristic (for
  example, objects allocated in a loop body that never escape the loop are
  ephemeral).
- **Cohort graph.** Each segment keeps a summary of outgoing edges by target
  segment, with counts. At collection time, dirty cards are rescanned and
  their summaries recomputed before any reclaim decision; summaries only
  shrink during that rescan, never between collections.
- **Collection.**
  1. Enumerate roots as today (globals, registers, stacks, fibers). A root
     word marks the *segment* it points into, after the `GCSTARTS` check.
  2. Rescan dirty cards.
  3. Traverse the segment graph from the marked segments.
  4. Reclaim every unmarked segment as a whole: reset its cursor, clear its
     `GCSTARTS` bytes and cards, and return it to the segment pool.
  5. Run object-level mark-sweep only inside segments selected for
     fracturing (M5) and, periodically or on demand, over the whole heap.
- **Verifier.** `MAYC_GC_VERIFY=1` runs a full object-level trace after each
  MOSAIC collection and fails loudly if a reclaimed segment held a reachable
  object. `gc_stress.py` gains a `--policy mosaic` mode, and its Python
  graph model checks results as it does today.

Exit: all GC suites pass under MOSAIC with the verifier on. There is a
measured comparison against the baseline on the M0 suite, even if MOSAIC is
slower at this stage.

## M4: mortality learning

- **Survival histograms** per (site, fiber-or-phase) context, updated from
  sampled objects at each collection epoch, off the allocation fast path.
- **Reclassification.** A site whose objects outlive their class moves to a
  longer-lived class for future allocations, and vice versa. Decisions take
  effect at segment refill, so the fast path stays a bump.
- **Co-death clustering.** Sites whose objects repeatedly die in the same
  epoch share a cohort class, even when they are unrelated in the source.
- **Phase contexts.** Fiber identity, and optionally a compiler-provided
  "request" marker (function entry/exit of designated functions), split one
  site into several classes when its lifetimes differ by phase.
- Metadata stays bounded: a fixed-size table of contexts with eviction.

Exit: on the M0 suite, learned classification examines fewer objects than
static classification, and retained dead bytes stay within the M1 gate's
bound.

## M5: fracturing

- **Detecting dispersion.** A segment whose sampled survivors span several
  lifetime buckets, or which survives many epochs while its live estimate
  falls, is selected for fracturing.
- **Non-moving fracture first.** Run a local object-level trace inside the
  segment. Roots for that trace are the segment's incoming summarized edges,
  plus conservative roots that point into it. Then sweep it in place. Its
  free space becomes size-bin memory and the segment is reclassified as
  "mixed". This needs no stack maps.
- **Evacuating fracture later.** Moving survivors into better-classified
  cohorts requires knowing every pointer to them. That means precise stack
  maps from the code generator, the long-term item in performance Phase 5.
  Until then, only objects reachable solely from heap slots (none from
  conservative roots) may move, and pinned objects stay in place
  (mostly-copying, as in Bartlett's collector).

## M6: adaptive policy and fallback

- Per-segment policy: cohort collection where `E_C` is small, object-level
  tracing where it is not. Segments whose edge summaries approach their
  object count are merged or repartitioned.
- A whole-program switch: if MOSAIC's collections examine more than a set
  fraction of the objects a full trace would, fall back to full mark-sweep
  for the rest of the run (or until the next phase change).
- Thresholds based on live bytes, so peak memory tracks the live set.

Exit: MOSAIC becomes the default only if, on the M0 suite, it is never more
than 5% slower than the baseline collector on any workload. It must also be
faster in total GC time and p99 pause on the median workload, and peak
memory may not grow by more than 10%. Otherwise it stays opt-in
(`MAYC_GC=mosaic`) and documented as experimental.

## M7: evaluation and write-up

- A report in `compiler/mayc/tests/backend/` with the raw JSON. It covers
  total run time, GC CPU time, allocation throughput, p99.9 pause, peak
  heap, objects examined per collection, cohort fragmentation (dead bytes in
  live cohorts) and write-barrier overhead (measured by running with the
  barrier but without MOSAIC).
- Workload classes: correlated short-lived objects, caches mixed with
  temporaries, random graphs, and graphs mutated across cohorts.
- Context against other runtimes through the cross-language suites. Those
  comparisons are only indicative: the JVM collectors (G1, ZGC, Shenandoah)
  and LXR are moving, concurrent and precise, while Maylang's is not.
- Related work to cite and position against: Memento Mori (allocation-site
  lifetime prediction, 2015), LXR (PLDI 2022), Iso (request-private
  collection, 2025), Immix, sticky-mark-bit generational collection, and
  region inference. Whether MOSAIC's combination of cross-site co-death
  clustering, physical cohorts, cohort-graph collection and adaptive
  fracturing is new has not been established.

## Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Lifetimes are not predictable in Maylang programs | No gain over static grouping | The M1 gate stops the project before collector work |
| Cohort graph nearly as large as the object graph | Collection costs more than tracing | Merge/repartition and per-segment fallback (M6) |
| Conservative roots pin many segments | Dead cohorts retained | Measure pinned bytes in M1/M3; precise stack maps as the long-term fix |
| A missed write barrier | A live object freed | One barrier per store path, debug cross-check (M2), verifier mode (M3) |
| Raw `store64` into the heap | Barrier bypass | Barrier in the raw store intrinsics for heap targets, or always rescan word blocks |
| Barrier cost on store-heavy code | Mutator slowdown | Measure separately (M7); keep the barrier a single byte store on the fast path |
| Fragmentation from non-moving fracture | Memory growth | Size-bin reuse inside mixed segments; evacuation after stack maps |

## Progress

| Milestone | State |
| --- | --- |
| M0 Measurement and workloads | not started |
| M1 Traces and simulator (gate) | not started |
| M2 Groundwork (bump, segments, sites, barrier) | not started (inline bump allocation is also performance Phase 5) |
| M3 Static cohorts | blocked on M1 gate |
| M4 Mortality learning | blocked on M3 |
| M5 Fracturing | blocked on M3; evacuation also on precise stack maps |
| M6 Adaptive policy | blocked on M4 |
| M7 Evaluation | blocked on M6 |
