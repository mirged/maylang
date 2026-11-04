# Native Float main — issue #132b

Main's top-level statements are lowered by the fat path and kept as a tagged
`main` unless every value they touch is a machine word (#132). That scan
accepted only Int, Bool and Ptr words, so the roadmap's top-level Mandelbrot —
a Float loop with XMM-sized values — could not take the native path. It does
now: a top-level body whose values are all Int, Bool or Float machine words is
emitted as native-word code, with Float main locals and temporaries in XMM
registers and `print` boxing a Float as fat type 3 with its raw bits. Anything
the scan cannot prove (a string, list, map, struct, closure, handler, a Float
global, or a builtin outside the narrow set) keeps the tagged main exactly as
before, and `--no-opt` still keeps it tagged.

## Changes

### `src/backend/x86_64.may`

- **Scanner (`x86_main_native`).** `E_FLOAT` literals are `Float` values;
  `+ - * /` on two Floats and unary minus keep `Float`; the six comparisons on
  two Floats produce `Bool`; the `to_float` builtin converts an Int (or passes a
  Float through) and produces `Float`; `print` accepts Float arguments; a call
  to a word-compatible user function may take and return Float words. A new
  `X86_MAIN_FLOATS` flag is published only when the whole body is accepted, and
  `main_native_floats`-style fallback is unchanged: any unhandled instruction
  returns false and `cg_program` emits the tagged main.
- **Emitter (`x86_native_main`).** `X86_FLOAT` is turned on for the main block
  when the scan recorded a Float, with the Float home tables reset, so
  `x86_float_plan` reserves XMM8-15 for the declared Float main locals,
  `cg_bin`/`cg_un` lower Float arithmetic and comparisons to SSE, and the
  type-aware raw-path guards from the Float-loop work apply unchanged. `print`
  boxes a Float argument with fat type word 3 (Int/Bool keep 2/1) and the raw
  bit pattern in RDX/RAX. The flag is cleared again before the function bodies
  are emitted.
- The native main keeps its existing `ctx.leaf = true` treatment: its calls are
  to `print`/runtime helpers, which are raw functions and do not touch
  XMM8-15, so Float main locals need no spill there; a call to a user function
  still goes through `x86_call_direct`, which spills the homes around it.
- `X86_MAIN_KINDS` now carries `"Float"` as well; nothing else in the native
  main path changed.

### Tests

- `tests/main_native_floats.may` is a new fixture: a top-level Mandelbrot
  loop, a top-level Float accumulation loop, Float main locals and mutation,
  `print` of Float values (signed zero, infinities, NaN), the six NaN
  comparisons, a native Float function called from the native main, and an Int
  comparison. Its expected output was produced by the compiler before the
  change (the tagged main) and equals the `--no-opt` output; `oracle.py` covers
  it automatically.
- `tests/backends.py` compiles a small top-level Float loop and asserts the
  optimized main region boxes a Float with `push 0x3`, contains `mulsd`/
  `addsd`, has no fat `cmp r9,0x3` type checks, and that the image and body
  differ from `--no-opt`, which keeps the tagged main.
- `tests/main_native_words.may` and `tests/main_native.may` keep their recorded
  outputs; their headers now point at the Float companion.
- `tests/backend/native_float_main/` holds the new `float_main.may`
  microbenchmark and `run.py`, the paired CPU-time harness for this increment.

## Measurements

[`native-float-main-performance.json`](native-float-main-performance.json) holds
the raw samples, taken with [`native_float_main/run.py`](native_float_main/run.py)
(`--rounds 15 --cpu 2 --self-compile`) on a 13th Gen Intel i5-13500H under
Linux 6.12.

- "Before" is `c8aac1b9…`, the compiler preserved before the Float work; "after"
  is `6a96a507…`. For `mandelbrot`, `nbody` and `float_main` the two images were
  byte-identical before this change (the earlier task only touched Float
  *function* codegen), so the deltas below are the native Float main alone. The
  runtime sidecars are identical (`1a4c10aa…`).
- Every measured child was pinned to CPU 2 with `taskset`, interleaved ABAB
  rounds alternate the order, and every workload printed the same output on
  both sides. The host load average was 2.37/2.14/2.41.
- Values are median CPU times of 15 samples after one warm-up.

| Workload | Before, ms | After, ms | Change |
| --- | ---: | ---: | ---: |
| `float_main`: 20M-iteration top-level Float loop | 164.03 | 28.97 | **−82.3%** |
| mandelbrot, top-level 600×600 | 45.02 | 42.12 | **−6.4%** |
| n-body, control (tagged functions) | 81.61 | 81.65 | +0.1% |
| self-compile | 2479.34 | 2443.35 | −1.5% (within the run's spread) |

The `float_main` result is the shape the item targets: the tagged main checks
every operation and calls the runtime for `to_float`; the native main keeps the
accumulator and both `let` temporaries in XMM8-15 and runs
`cvtsi2sd`/`mulsd`/`subsd`/`divsd` inline. 5.7x faster, not a few percent.

The top-level Mandelbrot gains 6.4% because its tagged main was already a
versioned fat body with Float locals in XMM and Int counters in callee-saved
registers; what the native main removes is the per-operation type-word checks
(each Float op in the tagged loop starts with two `cmp`/`jne` guards) and the
division helper calls. The measured 42.12 ms CPU leaves it at 1.2x the C build
in the cross-language suite:

| benchmark | maylang | C | Rust | Java | Node | may/C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mandelbrot (whole-process wall, 7 runs) | 42 | 34 | 37 | 67 | 63 | 1.2x |

That is down from 1.4x C in `native-floats.md`'s recorded run. `nbody` does not
move: its Float work reads struct fields on a `List<Body>` and stays in tagged
functions, so its (byte-identical) image and time are the control.

**Code size.** The compiler image grows by 4 152 bytes over the previous
increment (3 135 472 → 3 139 624, +0.1%); over the whole Float series it is
+1.1%. **Compiler cost.** Self-compile is inside the run's spread (the same
program, so the difference is layout/noise).

## Tests

- `sh compiler/rust/build.sh`;
- `python3 compiler/mayc/tests/verify.py --compiler "$PWD/compiler/mayc/mayc_new"`:
  **146 passed, 0 failed**, including `oracle.py` and the new fixture;
- `python3 compiler/rust/test.py`: source-only bootstrap fixpoint, stage 2
  equals stage 3;
- `python3 scripts/check_repository.py`;
- `python3 compiler/mayc/tests/backends.py --compiler …`: pass, including the
  new native-Float-main objdump assertions;
- `python3 compiler/mayc/tests/backend/xlang.py --bench mandelbrot --runs 7`:
  every language's output agrees, maylang 42 ms.

## Limits and follow-ups

- The scan is deliberately narrow. Anything dynamic (a string, list, map,
  struct, closure, handler or exception, a Float global, or a builtin outside
  `print`/`to_float`/`exit`/`syscall`/loads/stores) still keeps the tagged
  main, and the Float builtins from the remaining #132 list (`%`, `int(Float)`,
  `sqrt`/`abs`/`floor`/`ceil`/`round`/`min`/`max`) are not native in main
  either — using one falls back to the tagged main.
- Escaped-Float-function demotion does not apply to main: the scan rejects any
  function value in main's body.
- The remaining gain on top-level Mandelbrot is loop-level (hoisting the two
  Float literal constants out of the inner loop and common subexpression
  elimination for `zr*zr`), not instruction selection; the native main now has
  the same inner-loop shape as the native Float loop function measured in
  `native-float-loops.md`.
