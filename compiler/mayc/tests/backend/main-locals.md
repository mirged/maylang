# Top-level bindings as main locals — issue #101

Top-level `let` and `mut` declarations were globals: every access loaded the
16-byte data word by absolute address, every one was a collector root, and
none could take a register home, because `fat_plan_homes` only chooses locals
declared once in the body it is compiling. The roadmap (Phase 3, "top-level
code compiled as main") lists this as the precondition for compiling main like
a function.

## Changes

`ir_main_locals` in `src/ir.may` runs after every function is lowered and
before the emission snapshot. A top-level declaration becomes a local of main
when no function reads or assigns its name. The main block then declares it
like a nested `let`, so it gets a frame slot, a register home when it is hot
(`fat_plan_homes`) and an XMM home when its type is proven `Float`; the data
word and its collector root are dropped from `ctx.globals`.

A binding keeps its global in five cases, each of which would otherwise change
what the program does:

- **A function uses the name.** A function reaches a top-level binding only as
  a global, so demoting it would make the reference unresolved. Reads,
  assignments and calls in any reachable function's IR count.
- **A call through the variable** (`let f = other; f(1)`). The callee's name
  lives in the call payload and is resolved while emitting, and `lsra_operands`
  counts no use for it, so liveness could drop the stored closure. The guard
  stays until that use is modelled.
- **`pub`.** An importer reads the binding as a global.
- **Main also declares a local of that name, or declares it twice.** Reads
  resolve by name, so a demoted binding would capture reads meant for the
  later one; `x86_codegen.may` redeclares `shadow` and `shared` at top level
  and caught exactly that.
- **Main reads it before the declaration.** That read sees an unset global
  (`nil`); a demoted binding would read an uninitialized slot.

The pass is skipped under `--no-opt`.

## Measurements

Same machine (Intel i5-13500H, Linux 6.12, full runtime), whole-process wall
time, hyperfine median of 5 runs after one warm-up, identical output. "before"
is the compiler without the pass; both binaries were built from the same
sources.

| Benchmark | before, ms | after, ms | change |
| --- | --- | --- | --- |
| fib | 60.6 | 60.5 | 0% |
| collatz | 90.8 | 88.4 | -2.6% |
| sieve | 312.0 | 314.9 | +0.9% |
| map | 108.0 | 109.0 | +0.9% |
| strings | 58.0 | 56.5 | -2.6% |
| mandelbrot | 45.4 | 44.9 | -1.1% |

n-body and binary trees were not timed this way: at ~100 ms/per-run for
n-body and ~1.7 s for trees, eight alternating samples per benchmark were not
worth the session time, and their hot code is inside functions rather than in
main.

The changes are inside the run-to-run spread (±3%), so the pass does not
measurably speed up the suite by itself. A micro-benchmark shows why, and
where the remaining time is:

| Variant of `while (i < 100000000) { x = x + i % 7; i += 1; }` | ms |
| --- | --- |
| top level, demoted to main locals (this change) | 219.3 |
| the same code inside a block, always locals | 219.3 |
| top level, before this change (globals, proven types) | 219-221 |
| top level with `--no-opt` | 362.8 |
| wrapped in an all-`Int` function (native words) | 92.7 |

Proven types already removed the per-operand type checks from these globals
(`proven-types.md`), so a register home only saves the load, and the loop is
dominated by the arithmetic. The 2.4× that is still available on this shape
comes from compiling main's body as native-word code, which is the next
Phase 3 item and needs either a word-eligible main or native regions inside fat
code.

## Tests

- `tests/main_locals.may` covers each case: a demoted counter in a loop, a
  global read and written by functions, a closure over a top-level `let`, a
  struct value, a list, a read before the declaration, a name declared twice
  and a shadowing block local. Its output is pinned in
  `tests/legacy_behavior.json`.
- `tests/oracle.py` compiles every behaviour fixture with and without
  `--no-opt` and requires the same exit status, stdout and stderr.
