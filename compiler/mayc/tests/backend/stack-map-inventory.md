# Allocating-safepoint inventory — issue #135 (precise stack-map groundwork)

Status: implemented as a pure compiler analysis with a report mode, a
machine-checkable harness and a byte-identical default path. No IR rewrite, no
descriptor emission and no collector change: this is step 2 of the migration
order in [STACK_MAPS.md](../../../../docs/design/STACK_MAPS.md#5-migration-order),
which says the inventory is committable on its own.

## Mechanism

`docs/design/STACK_MAPS.md` §2.1: a safepoint is a call site where a collection
can start while the caller's frames are live, and a collection starts only
inside `rt_alloc_kind`. The inventory therefore computes the set of functions
that can reach `rt_alloc_kind` and marks every IR call site whose callee is in
that set.

- `src/ir.may: ir_stack_map_inventory(ctx)` reads the emission snapshot after
  `ir_opt`: the function index comes from `ctx.functions` (name, IR block,
  raw/fat mode, native flag) plus the top-level main block.
- Edges are the statically known calls: `E_CALL` (fat and raw runtime
  functions, which are ordinary functions in the same IR) and `IR_RUNTIME`
  (lowered runtime helpers such as `rt_push`, `rt_map_set`, `rt_struct_new`).
  `E_ICALL` is treated as allocating, as the design requires, and an
  `IR_RUNTIME` name that does not resolve to a function in the image is treated
  the same way and reported separately (none occur today).
- The fixpoint is seeded at `rt_alloc_kind` and propagated to callers;
  fault constructors (`rt_mkerr`, `rt_fail*`) allocate and are reached
  transitively, so with-blocks are covered without a special case.
- A site is a safepoint when its callee is in that set or it is an indirect
  call. Sites are split by call kind (runtime, direct, indirect) and by frame
  shape: only call sites inside fat-value frames need a descriptor; raw and
  native-word frames between two fat frames remain the conservative gap
  described in §2.3.
- `main.may` adds `--stack-map-inventory`, which runs the analysis after IR
  optimization, prints one JSON object and exits. The normal compile path never
  calls it.

JSON keys: `functions`, `raw_functions`, `fat_functions`,
`allocating_functions`, `fat_allocating_functions`, `main_body_safepoints`,
`safepoints`, `fat_safepoints`, `runtime_safepoints`,
`direct_call_safepoints`, `indirect_call_safepoints`,
`unresolved_runtime_names`.

## Inventory of the compiler and the eight benchmarks

`mayc --stack-map-inventory` on each source; `code_bytes` and
`slots_median` from `stack_retention.py --inventory` on the same image, used for
the map-size estimate (2 bits per 16-byte frame slot per site, i.e.
`ceil(slots/4) + 1` bytes per site at the image's median slot count — the
STACK_MAPS §2.1 encoding upper bound, applied only to allocating sites instead
of every call).

| Image | functions | fat functions | allocating | fat allocating | safepoints | fat safepoints | main sites | est. map bytes (2-bit) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compiler (`main.may`) | 1,057 | 868 | 730 | 606 | 8,450 | 8,086 | 387 | 40,430 B (1.35% of code) |
| fib | 232 | 42 | 143 | 19 | 444 | 80 | 0 | 240 B (0.25%) |
| collatz | 231 | 42 | 143 | 19 | 444 | 80 | 0 | 240 B (0.25%) |
| sieve | 231 | 42 | 143 | 19 | 445 | 81 | 1 | 243 B (0.26%) |
| hashmap | 231 | 42 | 143 | 19 | 447 | 83 | 3 | 249 B (0.26%) |
| strings | 231 | 42 | 143 | 19 | 447 | 83 | 3 | 249 B (0.26%) |
| mandelbrot | 231 | 42 | 143 | 19 | 444 | 80 | 0 | 240 B (0.25%) |
| n-body | 234 | 45 | 145 | 21 | 466 | 102 | 13 | 306 B (0.24%) |
| binary trees | 235 | 45 | 145 | 21 | 453 | 89 | 2 | 267 B (0.27%) |
| compiler image size for reference | | | | | | | | code 2,990,080 B, 983 prologues, median 16 slots |

The compiler image is the interesting case. STACK_MAPS §2.1 sized the naive
budget from *every* call site in the image (37,983 calls, 1.14 MiB, 38% of
code) and concluded that encoding is the design risk. Restricting the maps to
the sites that actually reach the allocator cuts the required descriptors to
8,086 fat-frame safepoints, i.e. **~40 KiB, 1.35% of the compiler's code** at
the same 2-bit-per-slot upper bound. The benchmark images need 240-306 bytes
each (0.24-0.27%). The map-size budget that STACK_MAPS called unacceptable is
therefore not the binding constraint once only allocating sites are mapped;
the remaining work is the descriptor encoding and, more importantly, the
live-value precision (§2.2), not the site count.

Today's images emit no `E_ICALL` sites at all: dynamic calls lower through the
`rt_call*` runtime helpers, which reach `rt_alloc_kind` and are already counted
as runtime safepoints. The conservative indirect rule is therefore a safeguard
for future lowering, not a current cost.

## Default path is unaffected

The analysis runs only under `--stack-map-inventory`, which prints and exits
before backend emission. Verified for this change by building one compiler
before and one after the analysis (only `main.may` and `src/ir.may` differ) and
comparing emitted images byte-for-byte:

| Test image | result |
| --- | --- |
| `compiler/mayc/tests/backend/context.may` (raw runtime) | identical |
| xlang `fib`, `hashmap`, `trees` | identical |
| xlang `trees` with `--no-opt` | identical |

The new harness `compiler/mayc/tests/stack_maps.py` (registered in
`verify.py`, which now reports 145 checks) pins the report contract on a small
fixture: required keys, the call-kind sum equals the safepoint total, the
allocating counts are non-zero, the top-level main body has its own sites,
`--no-opt` produces a well-formed inventory too, and two default compiles of
the fixture are byte-identical and run with the expected output.

## What this deliberately does not do

- No descriptors are emitted, no liveness is computed, no shadow stack exists.
  Per-site live-value bitsets come from the backend's existing interval
  liveness (§2.2); that is the next step, not this one.
- No backend assertion was added: the fixpoint lives in the analysis, and
  threading the allocating set into the backend's emit context would touch the
  code generator on the normal path for no verified benefit yet. The report
  mode is the machine-checkable form this step needs.
- Raw and native-word frames are not covered; the design keeps them as the
  conservative gap.

## Reproduction

```sh
sh compiler/rust/build.sh

# One image.
compiler/mayc/mayc_new --stack-map-inventory compiler/mayc/tests/backend/xlang/may/trees.may

# The compiler image (built binary, not the launcher script).
compiler/mayc/mayc_new --stack-map-inventory compiler/mayc/main.may

# Frame sizes for the map-byte estimate.
python3 compiler/mayc/tests/stack_retention.py --inventory compiler/mayc/build/bin/mayc_new

# Contract test.
python3 compiler/mayc/tests/stack_maps.py --compiler "$PWD/compiler/mayc/mayc_new"
```

Raw inventory data and image measurements: [stack-map-inventory.json](stack-map-inventory.json).
