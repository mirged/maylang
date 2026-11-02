# Precise stack maps

Status: `design:discussion` (roadmap phase 5, #135). Nothing here is
implemented. The measurements below were taken on the integrated tip
`62c3c45` with `compiler/mayc/tests/stack_retention.py`, which is committed as
the measuring instrument for a future implementation; the earlier attempts at
this phase are recorded in the [roadmap](PERFORMANCE_ROADMAP.md#phase-5-allocation-and-collection)
and in [inline-alloc.md](../../compiler/mayc/tests/backend/inline-alloc.md).

The collector is conservative and non-moving: `rt_gc` marks from the encoded
global roots and from a word-by-word scan of the stack, the five callee-saved
registers, and suspended fiber stacks
([GC.md](../internals/GC.md), [MOSAIC_GC.md](MOSAIC_GC.md)). A word that looks
like a pointer into the heap keeps its object alive, and an `Int` payload is
checked too because `addr`/`cstr` pointers travel as `Int`. Precise stack maps
would replace that scan with per-safepoint descriptions of the live fat values
so that a dead slot cannot pin an object, and so that a later generational or
moving nursery has somewhere to find the roots it must update.

This note records what the maps must describe, how the collector would consume
them, a migration order, and what the change is worth on the #135 acceptance
metrics. It also records the part of the RSS problem the maps *do not* solve.

## 1. What conservative roots retain, measured

The harness builds a probe (or one of the cross-language workloads) against a
copy of the runtime whose sweeps report the marked bytes (`live`), the
allocation frontier (`extent`, after the sweep's rewind) and the next threshold.
Each probe keeps a live set the harness can compute exactly, so

    retained >= reported live - (known kept bytes + known true transient bytes)

where the transient bound is generous (the object under construction counts as
truly live). `HSTACK` is 4,112 bytes and `GROOTS` 1,048,592 bytes once any
global root is registered; the meter reports `roots=` so the harness adds them
only when present. All numbers are a lower bound on removable garbage, not an
exact figure.

### 1.1 Small-object churn retains almost nothing

Heap 8 MiB, eleven collections each; known live set is one 2-field record
(128 B) plus runtime blocks.

| Probe | reported live max | known true live | retained |
| --- | --- | --- | --- |
| 2-field record per iteration | 1.00 MiB | 1.00 MiB | 0.4 KiB |
| 2-entry map literal per iteration | 1.00 MiB | 1.00 MiB | 0.5 KiB |
| 2-element `List<Int>` per iteration | 1.00 MiB | 1.00 MiB | 0.5 KiB |
| the same record loop, `--no-opt` | 1.00 MiB | 1.00 MiB | 0.7 KiB |

So the scan is not leaking arbitrary garbage: a hot allocation loop with one
stale slot retains the last object or two, not the loop's history.

### 1.2 A dropped large graph is retained as a whole

The same loop, but each iteration builds and drops a binary tree of
`struct Node { left: Any, right: Any }` (128-byte records). Retention scales
with the size of the graph whose pointer is left in a slot.

| Probe (heap) | tree nodes | reported live max | known true max | retained lower | retained upper | peak RSS |
| --- | --- | --- | --- | --- | --- | --- |
| depth 6, 64 MiB | 127 | 1.03 MiB | 1.02 MiB | 0.01 MiB | 0.02 MiB | 80 MiB |
| depth 12, 64 MiB | 4,095 | 3.01 MiB | 1.50 MiB | 1.51 MiB | 2.01 MiB | 104 MiB |
| depth 14, 64 MiB | 16,383 | 8.00 MiB | 3.00 MiB | 5.00 MiB | 7.00 MiB | 110 MiB |
| depth 16, 64 MiB | 131,071 | 40.00 MiB | 17.00 MiB | 23.00 MiB | 39.00 MiB | 216 MiB |
| depth 16, 128 MiB | 131,071 | 40.00 MiB | 17.00 MiB | 23.00 MiB | 39.00 MiB | 294 MiB |
| keep one depth-16 tree, churn records | - | 17.00 MiB | 17.00 MiB | 0.4 KiB | 0.4 KiB | 90 MiB |

The last row is the control: when the only live tree is genuinely live and the
churn is small, nothing is retained. The depth-16 churn rows retain roughly two
16.8 MiB trees at their worst sweep: the tree built in the previous iteration is
semantically dead but one of its pointers is still in a frame slot or a
callee-saved register when the next allocation triggers the collection.

### 1.3 The real binary-trees workload

`compiler/mayc/tests/backend/xlang/may/trees.may` (depth 16, one long-lived
tree, iterations from depth 4 to 16), instrumented runtime, per-sweep values:

| Nominal heap | collections | live min / median / max | retained lower | extent max | peak RSS | time |
| --- | --- | --- | --- | --- | --- | --- |
| 32 MiB | 37 | 16.00 / 17.12 / 46.02 MiB | 13.01 MiB | 104.02 MiB | 119 MiB | 1.71 s |
| 64 MiB | 26 | 17.01 / 17.10 / 46.02 MiB | 13.02 MiB | 134.02 MiB | 153 MiB | 1.28 s |
| 256 MiB (default) | 11 | 17.01 / 17.32 / 40.00 MiB | 7.00 MiB | 208.00 MiB | 234 MiB | 1.12 s |

The median is exactly the long-lived tree (16.78 MB) plus the 1 MB global root
table, i.e. no conservative retention at all; a few heavy sweeps hold a second
tree (partly the one under construction, partly retained). The same workload
with the long-lived tree deleted (`trees_nolived`) shows the split clearly:

| Nominal heap | collections | live min / median / max | retained lower | peak RSS |
| --- | --- | --- | --- | --- |
| 32 MiB | 36 | 1.01 / 1.10 / 30.00 MiB | 13.00 MiB | 100 MiB |
| 64 MiB | 24 | 1.01 / 1.09 / 32.00 MiB | 15.00 MiB | 142 MiB |
| 256 MiB (default) | 10 | 1.01 / 1.27 / 32.00 MiB | 15.00 MiB | 226 MiB |

Most sweeps there have under 2 MiB of genuinely live data, yet peak RSS is
226 MiB. So on the workload the acceptance is about, **retention is a few
megabytes and peak RSS is not retention-driven**. Section 1.4 shows what drives
it.

### 1.4 Frontier creep dominates peak RSS

In the default configuration the post-sweep frontier of `trees` and
`trees_nolived` grows by exactly `GCMARGIN` (8 MiB) per collection:
128, 136, 144, ..., 208 MiB. A collection is triggered in the middle of a tree
construction, so the most recently allocated records are genuinely live and sit
at the top of the heap; the sweep only rewinds over a *trailing garbage run*, so
it cannot rewind at all, and the next threshold is `HP + GCMARGIN`. Every
collection therefore raises the high-water mark by one margin. That is why a
workload with ~1 MiB of true live data peaks at 226 MiB: 128 MiB initial floor
+ 10 × 8 MiB of creep + runtime overhead ≈ 226 MiB.

Precise roots do not change this: the blocks that pin the frontier are live.
What precise maps change is the meaning of the `live` input to the threshold
`max(GCMIN, 2 * live + GCMARGIN, HP + GCMARGIN)`, which matters once the floor
and margin are tuned (section 1.5).

### 1.5 Threshold policy is the stronger RSS lever today

`GCMIN` and `GCMARGIN` are constants derived from the nominal 256 MiB heap
(`sz / 2` and `sz / 16` capped at 8 MiB). Replacing those two lines in a runtime
copy and re-running the workload changes the peak far more than the measured
retention does (three runs each, minimum of peak RSS):

| Policy | trees peak | trees time | collections | trees_nolived peak |
| --- | --- | --- | --- | --- |
| default (`GCMIN`=128 MiB, `GCMARGIN`=8 MiB) | 233 MiB | 1.20 s | 11 | 225 MiB |
| `GCMARGIN`=2 MiB | 173 MiB | 1.19 s | 14 | 171 MiB |
| `GCMARGIN`=512 KiB | 151 MiB | 1.34 s | 16 | 151 MiB |
| `GCMIN`=32 MiB | 200 MiB | 1.18 s | 19 | 190 MiB |
| `GCMIN`=8 MiB | 202 MiB | 1.24 s | 20 | 180 MiB |
| `GCMIN`=8 MiB + `GCMARGIN`=512 KiB | **94 MiB** | 1.90 s | 60 | **63 MiB** |

The last row is the interesting one: with a small floor and margin, peak RSS
tracks `2 * live + margin`, which is exactly the quantity precise maps make
meaningful (max live 46 MiB → 34 MiB with retention removed on trees). It also
costs 60 collections against 11, and 1.9 s against 1.2 s, so it is not free.

### 1.6 Other workloads and the compiler

At the default heap only `trees` collects; the others allocate less than the
128 MiB first threshold and never collect, so conservative retention does not
affect them at all (peak RSS is just the allocation extent):

| Workload | collections | allocated | live after last sweep | peak RSS |
| --- | --- | --- | --- | --- |
| trees | 11 | 1,885,689,824 | 41,946,016 | 234 MiB |
| hashmap | 0 | 65,529,120 | 0 | 67 MiB |
| strings | 0 | 62,413,360 | 0 | 62 MiB |
| sieve | 0 | 1,048,704 | 0 | 11 MiB |
| n-body, fib, collatz, mandelbrot | 0 | ~1 MB | 0 | ~4 MiB |

(`sieve` allocates only 1 MB of blocks because its one growing list buffer is
the newest block and `rt_grow_in_place` extends it; nothing else allocates.)

The compiler compiling itself is the largest real heap. `MAYC_GC_STATS` is not
enough for it because a program that writes no output never reaches the runtime
report, so a metered compiler copy was used (section 9). It registers **318
global roots** and its seven sweeps report live 60, 70, 70, 81, 98, 165 and
191 MiB (in sweep order) while the post-sweep `extent` reaches 338 MiB and the
threshold 390 MiB. The true live set is not computable from outside, so no
retention number is claimed for it; it shows that any precise-map design must
handle a growing live set of ~200 MiB and a large global root table.

## 2. What the code generator must emit

### 2.1 Safepoint inventory

A safepoint is a call site where a collection can start while the caller's
frames are live. Collections start only in `rt_alloc_kind` (and therefore in
every runtime helper that calls it: map growth, list growth, string creation,
error maps, closures and cells, file/process helpers, `rt_ffi_result` string
copies, ...). Fault construction also allocates (`rt_mkerr`), so faulting calls
are safepoints too: a `may`/`otherwise` can therefore collect while the
protected frame is live. Indirect calls (`E_ICALL`, closures, function values)
must be treated as allocating unless a whole-program analysis proves the
target.

The compiler already has the call graph of fat functions (its reachability
queue and the raw backend's function table); the inventory pass would compute
the fixpoint "can reach `rt_alloc_kind`" over fat *and* raw runtime functions,
mark every IR call site that reaches it, and either emit a map for it or, for
sites with no live values, a shared empty descriptor. The inventory is worth
committing on its own: it is pure analysis, output identical, and it can be
asserted in the backend (every call to an allocating runtime name has a
descriptor).

Rough size, measured by scanning an existing image for
`push rbp; mov rbp, rsp; sub rsp, imm32` prologues and the `E8` calls between
them (`stack_retention.py --inventory`; every call counted, so an upper bound):

| Image | code bytes | functions | frame max | median slots | calls | maps, 2 bits/slot |
| --- | --- | --- | --- | --- | --- | --- |
| `trees` | 94,208 | 129 | 2,368 B | 8 | 1,343 | 15.8 KiB (16.8% of code) |
| `hashmap` | 94,208 | 120 | 2,368 B | 8 | 1,301 | 15.8 KiB |
| compiler self-build | 2,830,336 | 943 | 7,696 B | 16 | 36,301 | 1.08 MiB (38% of code) |

Only the allocating subset needs maps, and a real encoding should be much
smaller than a per-call bitset over every frame slot (delta-compressed live
lists, one entry per function plus per-call deltas); the numbers are the budget
the prototype must beat. A map that costs a few percent of the image is
acceptable; 38% is not, so map encoding and compression are a design task of
their own.

### 2.2 What one frame descriptor says

The fat backend's frame is rbp-based: `fatBase + maxLocals` 16-byte value slots
(plus shared temporary slots assigned by the interval pass), saved home
registers below them, the closure environment slot, and the outgoing argument
area below the frame. Per safepoint the descriptor must classify:

- **frame slots**: dead, fat value (trace the payload when the slot's type word
  is 4-8, the same rule the collector already uses for kind-3 blocks), or a raw
  word. Raw words fall into: a `Ptr`/`Int` that may be an interior pointer
  (`addr`/`cstr` results, `load64` reads), the closure environment pointer
  (`envSlot`, a kind-1 block pointer), and never-pointer words (`Float` bits,
  `Bool`, counts). Only "may be a pointer" raw words need conservative
  treatment; the rest is the precision the maps buy.
- **callee-saved homes** (`RBX`, `R12`-`R15`): which of the function's chosen
  homes are live at this safepoint and their kind (fat pair, or payload-only
  for a proven type; a proven `Int` payload is again a may-interior-pointer
  word). XMM homes are always `Float` bits and never traced.
- **calling-convention registers**: direct calls (#132) pass up to three fat
  arguments in `RDX/RAX`, `RDI/RSI`, `R8/R9`, and native-word callees take
  payloads in SysV registers. A GC cannot start between the call and the
  callee's prologue stores, so the *caller* need not describe them provided the
  callee's prologue stores before its first safepoint (true today: prologue,
  then body). The outgoing argument area of a runtime call (`fat_rt` pushes two
  words per fat value) sits below the frame and is part of the conservative gap
  in the shadow-stack design.
- **held-slot values**: the `fat_get` rewind keeps a value in `RDX/RAX` only
  between its definition and the instruction that consumes it; no call lies in
  that window, so it does not need a map, but the backend must assert that.
- **temporaries**: liveness comes from the interval pass the backend already
  runs; a slot shared by non-overlapping temporaries is simply live or dead at
  that safepoint, so no new analysis is needed, but the maps must be emitted
  from the same liveness the code uses.

### 2.3 Safepoint identity and how the collector finds the descriptor

Two placements are possible:

- **Shadow stack (recommended).** A runtime-managed stack of frame records
  (descriptor id, `rbp`, frame bottom, fiber) is pushed in the fat prologue and
  popped in the epilogue. At a safepoint the call site stores its descriptor id
  into the top record (one store per allocating call). `rt_gc` then walks the
  records instead of guessing frames. Raw and native-word frames between two
  fat frames have no record; they are the conservative gap and are scanned by
  word between two recorded frame bounds. The GC's own raw frames are the gap
  from `__sp()` to the innermost fat frame. This needs no frame-pointer
  convention for raw code, which is why it is the recommended first step.
- **Frame-pointer chain + return-address maps.** Fat frames already keep `rbp`,
  and a table from code address to descriptor replaces the shadow stack; but
  every intermediate raw frame would have to be walkable, and the raw backend
  does not guarantee that, so it is a later optimization if it is needed.

Handlers and fibers share the mechanism: `may`/`otherwise` restores the stack
and callee-saved registers, so the longjmp path must also pop the shadow-stack
records between the raising frame and the handler's frame and restore the
descriptor pointer; a fiber switch swaps the shadow-stack base and its top, and
each suspended stack keeps its records alive for the collector.

### 2.4 Residual conservatism the maps do not remove

- **Word blocks** (list headers and buffers of `List<Int>`, map headers, closure
  environments, `rt_alloc` blocks) are scanned as words because an `Int` may be
  an interior pointer from `addr`/`cstr`. Precise *roots* cannot fix that;
  options are a typed-`Int` analysis, an interior-pointer side table, or an
  explicit pin/root API for address-derived values.
- **Raw/native-word frames and C extern frames** stay conservative (the gap
  scan), which is small but not zero.
- **`rt_candidate`** keeps validating every marked word against the allocation
  start table; precise maps can mark block payloads directly, but keeping the
  validation as an assertion in a verification mode is cheap insurance against
  a bad map.

## 3. How the collector consumes them

`rt_gc` would mark from the encoded global roots as today, then:

1. walk the shadow stack from the innermost fat frame to the outermost:
   - for the innermost, conservatively scan `[__sp(), frame_bottom)` (the
     collector's own raw frames and the outgoing arguments);
   - for the frame itself, apply its descriptor: mark the payload of every live
     fat slot whose type word is 4-8, mark each "may be a pointer" raw word
     through `rt_candidate`, and mark live register homes;
   - conservatively scan the gap to the next outer fat frame (raw and
     native-word calls);
2. after the outermost fat frame, conservatively scan to `CSTOP` (host stack);
3. repeat for every suspended fiber from its saved stack pointer and shadow
   stack top;
4. keep the existing mark stack, mark bits, `rt_candidate` validation, sweep and
   threshold policy unchanged: only the root enumeration changes.

Verify mode (step 3 of the migration) would run both enumerations at every
collection, mark conservatively first, then record: `conservative_live -
precise_live` (the retention being reclaimed) and any object the precise mark
found that the conservative scan did not (must be zero; a non-zero count means
the map misses a root and is a correctness bug).

The pause effect should be positive: the bytes marked per cycle drop by the
retained bytes measured in section 1 (and by more once word blocks are
precise), so marking does less work; the mutator pays the shadow-stack push/pop
and one store per allocating call.

## 4. Interaction with existing mechanisms

- **Fat values and block kinds.** The collector already traces kind-3 values
  and record (kind-4) entries precisely via type words; kind-1 word blocks and
  record headers stay conservative. Maps change *root* enumeration only.
- **Closures, captures, cells.** A closure environment is a kind-1 block; the
  map needs the environment pointer as a "may be a pointer" raw word (or, for a
  closure value, the fat value in a slot), not its contents.
- **Top-level main locals (#96).** They are ordinary frame slots of the fat
  `main` function and are described like any other slot. True globals are
  already precise: the compiler registers their addresses (318 in the compiler
  self-build).
- **`--no-opt`.** The same backend emits both variants, with a different slot
  layout; maps must be generated from that layout, and `oracle.py` already
  requires identical behavior. `--no-opt` has no register homes and no
  forwarding, so its maps are the simpler case.
- **Bootstrap.** Descriptor data must be deterministic (no map iteration order
  dependence), no new heap allocation at startup, and stage 2 must equal
  stage 3. Map data lives in `rodata`; growth must be measured with the
  inventory tool.
- **Debug traces.** The runtime's trace stack stores strings; it is a runtime
  root and stays as it is. Faults allocate error maps, so faulting calls are
  safepoints (section 2.1).

## 5. Migration order

Each step is independently revertable and leaves the compiler green.

1. **Measure, choose thresholds.** The retention tool and the policy table of
   section 1.5 are the input. A small, separate change to `GCMIN`/`GCMARGIN`
   (or a per-workload adaptive start) buys more peak RSS today than precise
   maps alone; it must be measured for throughput cost (60 vs 11 collections on
   trees) before deciding.
2. **Safepoint inventory.** Pure analysis pass: mark every IR call site that can
   reach an allocation or a fault, over fat and raw call graphs; assert in the
   backend that every allocating runtime call has one. Output, oracle and
   bootstrap unchanged.
3. **Shadow stack and descriptor emission, collector unchanged.** Fat prologues
   push records, epilogues pop, safepoints store descriptor ids; the collector
   still scans conservatively and only verifies that the records are well formed
   (bounded stack depth, popped in order, fiber switches balanced). Measure the
   prologue/call overhead. Exit: suite and bootstrap green, no output change.
4. **Verification mode.** Mark both ways; report `conservative_live`,
   `precise_live`, and any object precise marking found that conservative did
   not. Run `gc.py`, `gc_stress.py`, `limits.py --self-test`,
   `MAYC_GC_STATS` workloads and the compiler self-build under it. Exit: zero
   missing roots over a long run.
5. **Switch to precise roots for fat frames.** Keep conservative gaps and C
   externs. Exit: retention on the section-1 probes drops to the noise floor,
   `stack_retention.py` reports it, all suites green, and the suite/benchmark
   time is inside the noise budget.
6. **Extend word maps to native-word and raw frames (optional).** The raw
   backend can emit may-pointer bits per safepoint from its register allocator;
   this removes the conservative gaps but is a second code generator change.
7. **Then a moving/generational collector.** With precise roots a nursery or a
   moving old generation becomes possible ([MOSAIC_GC.md](MOSAIC_GC.md) M5);
   that is what can remove the frontier creep and move peak RSS toward the
   acceptance target.

## 6. Risks

- **Under-marking is a use-after-free**, not a slowdown. Conservative
  over-marking is benign; every missed root is a crash or silent corruption.
  Mitigation: verification mode (step 4), the existing `gc_stress.py` /
  `limits.py --self-test` oracles, `gc.py` record probes, oracle tests and the
  bootstrap fixpoint. The collector's `rt_candidate` validation stays.
- **Frame-layout coupling.** Maps depend on slot numbering, shared temporary
  slots, register homes, spills, the environment slot, boxed cells and versioned
  function bodies. The backend should assert that a safepoint's descriptor
  covers the frame and that nothing moved between the prologue and the
  safepoint; the `--no-opt` path has a different layout and must be tested.
- **Register arguments and held values.** Direct-call registers (#132) and the
  `fat_get` rewind must be modelled or provably absent at safepoints, as
  discussed in section 2.2.
- **Handlers and fibers.** Longjmp and fiber switches must maintain the shadow
  stack; a stale record reads freed frames. These paths have their own tests
  (fibers, `may`/`otherwise`) and need dedicated stress cases.
- **Image size and compile time.** The naive map size is 17-38% of code; a
  compact encoding must be designed and measured, and the compiler image growth
  checked against the bootstrap fixpoint and compile time.
- **Mutator cost.** Shadow-stack push/pop per call and one store per allocating
  call are small but must be measured; the collector's mark work drops, so the
  net effect on pause is likely positive.
- **Interior pointers.** `addr`/`cstr` values in `Int` slots cannot be dropped
  without an analysis or a pin API; water this down to "Int slots stay
  conservative" is a design decision the note leaves open.
- **The frontier creep is not solved by maps.** Section 1.4: the collections
  happen mid-construction, the newest blocks are live, `HP` cannot rewind and
  the threshold grows by `GCMARGIN` per cycle. Precise maps do not change this;
  a nursery, compaction, page return or a collection-at-quiescent-point scheme
  is needed for the last factor.

## 7. Expected effect on the #135 acceptance

The acceptance is binary trees within 3x Java in time and peak RSS within 2x
CPython (~42 MiB for trees) on every benchmark. Measured levers:

| Change | trees peak RSS | comment |
| --- | --- | --- |
| today | 234 MiB | 11 collections, 1.12 s |
| precise roots only, default policy | est. 210-230 MiB | removes 7-13 MiB of retained live at heavy sweeps; floor and creep unchanged |
| policy only: `GCMIN`=8 MiB, `GCMARGIN`=512 KiB | 94 MiB | 60 collections, 1.9 s; no codegen change |
| precise roots + tuned policy | est. 45-75 MiB | with live' max ≈ 34 MiB, threshold ≈ 2*live + margin; worst case depends on the trigger point (the tree under construction is genuinely live) |
| moving/compacting collector on top | target 42 MiB | needed to remove frontier creep/holes; out of scope here |

So the realistic estimate is that precise stack maps **alone reduce the trees
peak by only a few percent**, because the peak is dominated by the initial
floor (128 MiB) and by frontier creep (8 MiB per collection), not by retained
garbage. They become valuable in combination with a lower initial threshold and
margin (measured: 233 → 94 MiB for the policy alone; with precise live the
`2 * live` term is meaningful and the estimate is 45-75 MiB), and they are a
prerequisite for the moving/generational collector that is the only measured
path to the 42 MiB target. The other benchmarks do not collect at the default
heap and are already at 1.4-4x CPython: sieve 11 MiB, n-body 4 MiB, strings
62 MiB, hashmap 67 MiB. The binding case is binary trees, and precise maps are
necessary but not sufficient for it.

## 8. Open questions

1. Shadow stack or frame-pointer chain: the shadow stack is simpler with raw
   frames but costs one store per allocating call and a per-call push/pop; the
   chain is cheaper but needs every raw frame walkable. No cost model yet.
2. Map encoding: what is the smallest format that describes live fat slots,
   may-pointer words and register homes, and what is the compiled-image growth
   of the compiler at that size? The 2-bit upper bound (1.08 MiB, 38% of code
   for the self-build) is not acceptable as-is.
3. Interior pointers: keep all `Int` slots conservative, add a typed-`Int`
   analysis, add an explicit pin API for `addr`/`cstr`, or an
   interior-pointer side table? This decides how much of the word-block
   conservatism survives.
4. Safepoint set for faults: `rt_mkerr` allocates during a fault, so faulting
   calls need maps too; is it acceptable to treat every runtime call as a
   safepoint, and what does that cost in descriptor count?
5. Handlers/fibers: should the shadow stack be per fiber with a runtime swap,
   or a single stack with fiber records? What happens to records across a
   `may`/`otherwise` longjmp?
6. Threshold policy: with precise live available, should `GCMIN`/`GCMARGIN` be
   lowered (94 MiB at 1.9 s) or made adaptive, and what is the throughput
   budget on the other workloads (which do not collect today)?
7. Frontier creep: which scheme should be evaluated to stop the `HP + margin`
   growth — a nursery, compaction, page return, or collection at quiescent
   points — and does any of them land before precise maps?

## 9. Reproduction

```sh
# Retention probes and the real workload; the harness builds a test compiler
# with an instrumented runtime copy (heap size replaced and a sweep meter) in a
# temporary directory and prints per-sweep live/extent/threshold.
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --heaps 64 --modes big12_churn big14_churn big16_churn big16_kept
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --heaps 32 64 256 --workload trees trees_nolived

# Safepoint inventory of an existing image.
python3 compiler/mayc/tests/stack_retention.py --inventory \
    compiler/mayc/build/bin/mayc_new

# Stock statistics (trees is the only xlang workload that collects at the
# default heap; the report is written after each output line and at exit).
MAYC_GC_STATS=1 compiler/mayc/mayc_new compiler/mayc/tests/backend/xlang/may/trees.may -o /tmp/trees
MAYC_GC_STATS=1 /tmp/trees | tail -1
```

The compiler self-build number in section 1.6 was taken with a metered compiler
built the same way as the harness does it: copy the compiler binary and its
sidecars, add the sweep meter and leave the heap size at 256 MiB, build the
compiler with that copy (so the built compiler embeds the metered runtime), then
run it on `compiler/mayc/main.may`. The policy table of section 1.5 replaces
`GCMIN = sz / 2;`, `GCMARGIN = sz / 16;` and the 8 MiB cap in the runtime copy
before building the program under test.

Caveats: the harness measures test builds with an instrumented runtime, not the
production binary; `live` counts block sizes including 16-byte headers; the
known-live model assumes the `HSTACK`/`GROOTS` sizes stated above and reports
`roots=` so the harness can add `GROOTS` only when a global root exists; the
retained numbers are lower bounds because the transient bound is generous; and
peak RSS from `rusage` includes the runtime's reservations and the compiler
image's pages.

## 10. Earlier negative results in this phase

- **Returning pages to the OS** (`madvise` on reclaimed tails, size-class bins
  already present): peak RSS did not move, because conservative scanning keeps
  most of the garbage that the pages contain (recorded on #135).
- **Inline allocation** (inline bump and exact-size free-bin claim for
  construction sites): bit-identical heap behavior but neutral on the roadmap
  workloads and 2-7% slower on several controls, so the code was dropped
  ([report](../../compiler/mayc/tests/backend/inline-alloc.md)). Both results
  point at the same conclusion: the remaining memory cost is retention and
  frontier policy, not allocation or page accounting.
