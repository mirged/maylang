# GC and codegen limits

Run from the repository root on Linux x86-64 with Python 3.10+, Rust/C source
bootstrap tools, and binutils (`objdump`, `readelf`). Build changed compiler sources first; the launcher caches its binary.

```sh
sh compiler/rust/build.sh
make test-limits
```

The runner prints its artifact directory. Open `REPORT.md` for a table and
`report.json` for commands, configuration, compiler/sidecar hashes, raw samples,
per-child CPU time and kernel peak RSS. Outputs stay under ignored
`compiler/mayc/build/limits/`. An explicit output directory must be empty.

## Inspect actual codegen

```sh
python3 compiler/mayc/tests/limits.py --mode codegen \
  --backend native --iterations 2000000 --samples 7 \
  --pressure 64 --functions 512 --output /tmp/maylang-codegen
less /tmp/maylang-codegen/codegen/arithmetic/current-native/hot-functions.asm
objdump -d -Mintel /tmp/maylang-codegen/codegen/arithmetic/current-native/program
```

Every variant retains the executable, normalized complete disassembly, focused
`hot-functions.asm`, symbol/section tables, and `functions.json`.

The workloads exercise:

| Case | What it exposes |
| --- | --- |
| `arithmetic` | Tagged integer operations, signed constant division/remainder and loop dependencies |
| `branches` | Nested branches, signed/unsigned-looking inputs, repeated tests and loop back edges |
| `calls` | Eight arguments, stack overflow arguments and weighted checksums |
| `pressure` | Generated live call arguments beyond the allocator's four registers; tune `--pressure` (up to 256) |
| `collections` | Short-lived lists, maps, captured closures and optional map lookup |
| `contracts` | Narrow integer collection contracts in a loop |
| `graph` | Deep reachable calls plus equally many unreachable functions/literals; tune `--functions` (up to 4096) |

`--case NAME` can be repeated. Graph execution is capped at 1,000 iterations,
collection timing at 30,000; reports record the actual counts. Parameters come
from runtime arguments. Every warmup/sample must match an independent Python
checksum; dead marker literals must be absent from the executable.

Native calls with 256 arguments and a 4,096-function graph (plus 4,096 dead
functions) pass. The graph previously exhausted the compiler heap during IR
lowering because completed frontend phases retained tokens and lookup tables.
The compiler now releases those roots, and ELF string-table construction uses
a bounded byte sink instead of quadratic string concatenation. Normal CI
regresses the exact graph with the unchanged 256 MiB default runtime heap.
Use 512 functions for routine larger backend comparisons; generator ceilings
are workload bounds rather than a general compiler capacity guarantee.

Compilation is timed separately. Whole-process execution includes startup,
fork/exec and root setup; short timings can be dominated by that overhead.
Versions/backends run in interleaved, alternating order after one warmup each.
Use more iterations/samples for measurements and avoid simultaneous stress jobs.
`--cpu N` pins children to an allowed CPU; allowed CPUs are recorded in JSON.
Instruction/call/division/stack-reference counts are descriptive, with no timing
thresholds. Current native ELF function sizes are zero, so symbol-interval counts
can include the next function's unlabeled trampoline; `.text` bytes include the
runtime and alignment padding. These counts are not exact source-function sizes.

## Compare before and after a compiler change

Preserve a baseline with matching sidecars before editing/rebuilding:

```sh
sh compiler/rust/build.sh
mkdir -p /tmp/maylang-before/runtime
cp compiler/mayc/build/bin/mayc_new /tmp/maylang-before/mayc
cp compiler/mayc/runtime.may compiler/mayc/native.may /tmp/maylang-before/
cp stdlib/prelude.may /tmp/maylang-before/
cp -R compiler/mayc/runtime/. /tmp/maylang-before/runtime/
# Edit the compiler, then rebuild.
sh compiler/rust/build.sh
python3 compiler/mayc/tests/limits.py --mode codegen \
  --baseline /tmp/maylang-before/mayc --case arithmetic --case branches \
  --iterations 20000000 --samples 9 --output /tmp/maylang-comparison
```

The runner snapshots each compiler and its own sidecars rather than silently
using current runtime files for a historical compiler. Generated sources and
binary hashes remain available for replay.

## Push the collector

```sh
python3 compiler/mayc/tests/limits.py --mode gc --heap-mib 4 16 64 256 \
  --rounds 512 --seeds 1 42 2026 --self-test --timeout 120 \
  --output /tmp/maylang-gc-pressure
```

This uses a test-only instrumented copy of the checked-out runtime. The normal
runtime/installed tools are unchanged. Heap sizes are 4–1024 MiB; the default
process address-space limit is 2048 MiB and must be at least twice the largest
heap. Scratch mappings, allocation-start tables, roots and mark storage are in
addition to the selected heap. Larger sweeps intentionally touch substantial RAM.

| Case | Success contract |
| --- | --- |
| `gc_churn` | Allocation pressure plus forced collection; retain parent-only chains, validate payloads/links against deterministic identities and an independent checksum, and check physical heap/free-bin invariants |
| `gc_fragmentation` | Alternating retained/dead blocks, size-bin boundaries and large allocations; retained payloads and allocator invariants survive |
| `gc_objects` | Lists/maps, captured closures, UTF-8 strings, encoded `cstr` pointers and roots on suspended fiber stacks survive automatic collection |
| `gc_capacity` | A fully retained graph reaches the selected heap capacity and exits 70 with exactly `out of memory` |
| `gc_mark_capacity` | A wide retained graph fills the selected mark frontier and exits 70 with exactly `GC mark stack exhausted` |
| `gc_root_capacity` | Fill the real 131,072-slot registry; a further registration exits 70 with exactly `GC global root table exhausted` |
| `injected_corruption` | Deliberately alter a payload; its validator must exit with the expected detector code |

Select cases with repeated `--gc-case NAME`. Root/mark capacity and the detector
self-test run once at the first selected heap. Automatic object pressure scales
with heap size; fragmentation uses `max(2, rounds / 8)` rounds. `gc_churn` scales
allocation pressure with heap capacity and periodically resets its retained chain.
The existing [graph-oracle suite](../gc_stress.py) remains complementary: it has
a separate Python graph model and seeded arbitrary edge mutations.

To exercise the **production** mark-stack capacity rather than the default
64-slot calibration case:

```sh
python3 compiler/mayc/tests/limits.py --mode gc --gc-case gc_mark_capacity \
  --heap-mib 256 --mark-slots 1048576 --timeout 120 \
  --output /tmp/maylang-gc-mark-limit
```

GC telemetry reports allocation attempts/requested bytes, heap high-water/extent,
free/largest-free bytes, completed collection count/time, peak mark slots and
registered roots. Counters include failed allocation attempts. Capacity diagnostics
report using an independent scratch mapping without allocating from the collected heap.
Time spent in a collection aborted by capacity exhaustion is represented by the
child's total timing, not the completed-collection time counter.

Each child has wall/CPU/address-space/output/core-dump limits. Timeouts kill
the process group and reap the direct child. A crash or arbitrary exit 70 is a failure: expected
capacity cases require the matching diagnostic and telemetry. Failure reports
retain the source, seed, executable, commands, compiler, runtime, stdout/stderr,
usage and traceback. Reports stay incomplete on failure; an empty report is not
evidence that a collector passed. Conservative retention and fragmentation can
affect the precise number of successful allocations.

## CI and measured changes

Normal bootstrap CI runs a small correctness/detector profile and uploads the
`gc-codegen-limits` artifact. Its dispatch-only performance job runs a larger
native sweep and retains reports/disassembly with the other benchmarks.
Neither profile imposes a machine-dependent speed threshold.

`--backend` selects codegen variants. GC mode executes native full-runtime
fixtures, including fibers, and instruments the checked-out runtime.

See [measured signed-division optimization](../../PERFORMANCE_LIMITS.md) for raw
samples and the first assembly-driven change. Run
`python3 compiler/mayc/tests/strength_reduction.py` for signed boundaries,
fallbacks and actual native `idiv` checks.
