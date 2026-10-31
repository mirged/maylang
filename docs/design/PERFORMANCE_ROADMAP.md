# Performance roadmap

Status: proposed. Tracked in the
[Performance milestone](https://github.com/mirged/maylang/milestone/4) and the
tracking issue linked from [ROADMAP.md](../../ROADMAP.md#performance).

Maylang compiles to native code with its own backends, so it should run like
a compiled language: faster than CPython everywhere and close to the JIT
runtimes (Java, Node) on typed code. Today it does that only for integer
functions. This document records where the time goes and the order in which
to fix it. Every step stays inside the toolchain: no LLVM, external assembler
or C compiler.

## Baseline

Measured on `233909e` (fat values default), Intel i5-13500H, Linux 6.12, full
runtime, default flags. Whole-process wall time, hyperfine median of 5 runs
after one warm-up. Every language printed identical output. Comparisons: GCC
14.2 `-O2`, rustc 1.99 `-C opt-level=3`, OpenJDK 25, Node 24.22, CPython
3.13.5.

| Benchmark | Maylang | C | Rust | Java | Node | CPython |
| --- | --- | --- | --- | --- | --- | --- |
| fib(35), recursive `Int` function | 123 ms | 27 | 35 | 113 | 176 | 1467 |
| Collatz, seeds 1..300000, top level | 619 ms | 86 | 74 | 169 | 529 | 4022 |
| sieve, 10M `List<Bool>` | 1094 ms | 65 | 100 | 205 | 388 | 675 |
| map, 200k `Str` inserts + 400k lookups | 274 ms | 97 | 93 | 166 | 219 | 174 |
| strings, 300k `"item-" + str(i) + ";"` + `join` | 283 ms | 40 | 43 | 129 | 117 | 82 |
| Mandelbrot 600×600, 100 iterations | 803 ms | 70 | 71 | 117 | 117 | 2801 |
| n-body, 5 bodies × 200k steps (`struct`) | 6226 ms | 24 | 29 | 106 | 107 | 1510 |
| binary trees, depth 16 (`struct`) | 19965 ms | 321 | 400 | 205 | 317 | 4429 |

Peak RSS: sieve 420 MiB (CPython 84), strings 262 MiB (32), binary trees
290 MiB (20).

Further measurements behind the diagnosis:

- A `Map<Int, Int>` with 40 000 keys takes 91 s to build and query; time
  quadruples when the size doubles (#97).
- Reading a struct field costs about 50 ns, a `List<Float>` element about
  2 ns (#98).
- `join` of 300k five-character strings takes 161 ms and 144 MiB; 10M
  `push(flags, true)` take 499 ms and 420 MiB (#99).
- Collatz wrapped in `fun run(limit: Int) -> Int` takes 279 ms instead of
  915 ms in the same session: top-level `mut` bindings are globals and miss
  native-word lowering.
- Mandelbrot wrapped in a function only drops from 1064 ms to 791 ms:
  native-word lowering covers `Int`, `Ptr` and `Bool`, not `Float`.

## Where the time goes

1. **Algorithms in the runtime.** Maps hash only `Str` keys, and other keys
   are found by a linear scan. The key hash divides once per byte. `join`
   concatenates pairwise. List growth abandons every old buffer.
2. **Object layout.** Records are tagged maps, so `p.x` is a string-keyed
   lookup even when the checker knows `p: Point`. Every collection element
   is a 16-byte fat value, including `List<Bool>`.
3. **Fat code generation.** Every IR temporary lives in a 16-byte frame slot
   (#96). Static types are known but mostly unused: only all-`Int`/`Ptr`/`Bool`
   functions become native-word code, and operators other than `Int`
   arithmetic, comparisons and list indexing call the runtime.
4. **No IR optimizer.** The frontend folds constants (`sem_fold`) and drops
   unreachable functions (`ir_reachable`). The raw backend has register
   allocation, if-conversion, constant division, range and recurrence
   optimizations and DCE (reports in `compiler/mayc/tests/backend/`), but fat
   code gets none of them, and nothing inlines, hoists or removes checks.
5. **Allocation and collection.** Every allocation calls into the runtime,
   and the non-moving mark-sweep lets RSS grow toward its threshold.

## Principles

- **Measure first.** Each change ships with a reproducible report in
  `compiler/mayc/tests/backend/`: medians, sample counts, compiler identity
  and output equality, as `raw-call-gaps.md` does. Claims without a report
  are not merged.
- **Keep semantics.** Optimizations preserve evaluation order, effects,
  overflow and division faults, `may`/`otherwise` recovery and debug traces.
  Each pass gets oracle tests against unoptimized output.
- **Keep the toolchain green.** Bootstrap fixpoint (`make test-bootstrap`).
  Only Linux x86-64 is in scope while the other targets are frozen
  ([LINUX_X86_64_FOCUS.md](LINUX_X86_64_FOCUS.md)); there is no image size
  budget.
- **Fix algorithms before code generation.** An O(n) map lookup cannot be
  rescued by a better register allocator.

## Phase 0: measurement

- Track a cross-language suite under `compiler/mayc/tests/backend/` with a
  harness (`xlang.py`) that runs the eight workloads above in Maylang plus
  whichever of C, Rust, Java, Node and CPython are installed, checks that
  outputs are equal and records medians and peak RSS. Skip missing languages
  and say so.
- Record the baseline above as the first report. Rerun after every phase.
- GC statistics on request (collections, bytes allocated, live bytes, pause
  time), for example through an environment variable, and include them in
  `limits.py` reports.
- An optional CI job that publishes the report without gating, like the
  existing performance job.
- A `--no-opt` (or `-O0`) compiler flag that disables the optimizations
  below, so oracle tests can compare optimized and unoptimized behaviour.

## Phase 1: runtime algorithms

Low risk, large wins, no code generator changes.

- [#97](https://github.com/mirged/maylang/issues/97): hash every map key
  type, word-at-a-time key hash, masked probing.
- [#99](https://github.com/mirged/maylang/issues/99): one-allocation `join`
  and concatenation, reuse or release old list buffers, a constructor for n
  copies of a value, faster `str(Int)`.
- Audit the remaining runtime library (`native.may`, `prelude.may`,
  `runtime/fat.may`) for other quadratic or allocation-heavy paths: string
  slicing and searching, `len` on strings (code-point counting), list
  `insert`/`remove`, `keys`/`values`, sorting.

Goal: Maylang is not slower than CPython on any baseline benchmark except the
struct-bound ones, and no map operation is worse than amortized O(1).

## Phase 2: object layout

- [#98](https://github.com/mirged/maylang/issues/98): field access caches
  (done). Structs stay maps, but every `x.f` site caches the entry where it
  last found `f` and checks it inline against the program's shared key
  object, for typed and `Any` receivers alike; struct constructors allocate
  their entries at the final size
  ([report](../../compiler/mayc/tests/backend/struct-fields.md)). A struct
  as a header plus fixed fat slots would still cut each record's memory and
  allocations; it changes how records are observed and needs its own design.
- Enum variants and payloads with the same layout, so `match` reads payloads
  by offset.
- Specialized list storage for homogeneous element types (`List<Int>`,
  `List<Float>` as 8-byte words, `List<Bool>`/`List<Byte>` as bytes), with
  conversion when a value of another type is stored through an `Any`
  reference. Needs a design note (`design:discussion`): it touches the
  collector's allocation kinds and every list primitive.
- Closure environments as fixed slots.

Goal: n-body and binary trees faster than CPython. Sieve peak RSS below
CPython's.

## Phase 3: type-directed code generation

- [#96](https://github.com/mirged/maylang/issues/96): register-allocated
  temporaries and loop-carried locals in fat x86-64 code. Done: forwarded
  constants and variable reads, fused compare-and-branch, immediates,
  inline Float paths and two callee-saved register pairs for hot locals
  ([report](../../compiler/mayc/tests/backend/fat-registers.md)).
- Use static types: when both operands are known to be `Int` or `Float`,
  emit the operation without loading or testing type words, and keep such
  locals as single machine words, materializing a fat value only at `Any`
  boundaries, calls into dynamic code and handlers. Partly done: proven
  types skip checks and get single-register homes
  ([report](../../compiler/mayc/tests/backend/proven-types.md)). Because
  `Any` aliases can bypass annotations, types are proven from operations,
  not taken from the checker. Proven Floats stay in XMM registers, and
  functions get a body specialized for their annotated parameter types,
  entered only when the argument type words match
  ([report](../../compiler/mayc/tests/backend/float-registers.md)).
- **Native Float functions:** extend `words.may` so functions over `Int`,
  `Float`, `Ptr` and `Bool` compile to machine code with `Float` in XMM
  registers (same binary64 semantics as the runtime).
- **Native regions:** compile loops whose variables are all native-typed as
  native code inside otherwise fat functions, instead of requiring the whole
  function to qualify.
- **Top-level code:** compile top-level statements as a `main` function, so
  bindings that no function references become locals and qualify for the
  above.
- **Direct calls:** calls to known functions with matching arity skip the
  argument vector and count checks and pass arguments in registers.
- Inline fast paths for common runtime calls: `len` of lists, `push` with
  spare capacity, string equality on length mismatch, `??` on present map
  values.
- [#94](https://github.com/mirged/maylang/issues/94): restore or remove
  native-word extern calls.

Goal: Collatz and Mandelbrot within 2× of C. fib on a par with Java.

## Phase 4: IR optimizer

Passes on the shared IR (`src/ir.may`), so a revived ARM64 or RISC-V
backend would benefit too. Each one is skipped under `--no-opt`.

- Constant and copy propagation beyond `sem_fold`; dead code and dead store
  elimination for fat code (the raw backend's DCE as a model).
- Inlining of small, non-recursive functions and closures with known
  targets, with a size budget measured on the compiler's own image.
- Common subexpression elimination for pure operations, including repeated
  field reads and `len` calls in loop conditions.
- Loop-invariant code motion.
- Check elimination: bounds checks for `while (i < len(xs))` patterns, and
  overflow checks for induction variables whose range is proven (the raw
  backend's range analysis as a model).
- Escape analysis: stack-allocate or scalar-replace records and lists that
  do not escape their function (n-body's per-step temporaries).
- Monomorphization of generic functions at concrete instantiations, so
  `identity<Int>` and friends reach the native paths.
- Port raw-backend wins that apply to fat code: if-conversion, constant
  division and divisibility, addressing modes, code alignment.

Goal: suite median within 2× of Java and Node. No benchmark slower than
CPython.

## Phase 5: allocation and collection

- Inline bump-pointer allocation for small objects, falling back to the
  runtime when the current chunk is full.
- Size-class free lists so the sweep reuses memory instead of growing the
  heap. Return empty chunks to the operating system.
- Collection thresholds based on live bytes, so peak RSS tracks the live
  set rather than the 256 MiB default.
- Longer term (`design:discussion`): precise stack maps from the code
  generator, which would allow a generational or moving nursery. Today the
  collector scans stacks and registers conservatively
  ([GC.md](../internals/GC.md)).

Goal: binary trees within 3× of Java; peak RSS within 2× of CPython on every
benchmark.

## Phase 6: other targets and runtimes (deferred)

Frozen by [LINUX_X86_64_FOCUS.md](LINUX_X86_64_FOCUS.md). When ARM64,
RISC-V, the core runtime, NodeOS, macOS or Windows are revived, bring phases
2–4 to them as part of reviving them.

## Phase 7: compiler throughput

The compiler is a Maylang program, so phases 1–5 speed it up as well. Track
self-compile time and memory with `build_benchmark.py` after each phase, and
check that new passes keep compile time within budget (report `--time`
stage timings).

## Progress

| Phase | State |
| --- | --- |
| 0 Measurement | baseline measured locally; suite not tracked yet |
| 1 Runtime algorithms | #97, #99 done; runtime audit open |
| 2 Object layout | #98 done (field caches); slot layout open |
| 3 Type-directed code generation | #96, #94 done; proven types, XMM Floats and parameter versioning done |
| 4 IR optimizer | not started |
| 5 Allocation and collection | not started |
| 6 Other targets | deferred (frozen) |
| 7 Compiler throughput | not started |
