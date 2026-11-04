# Native Float loop bodies — issue #132

A Float function that contains a loop now compiles as native-word code instead
of staying tagged. Loop-carried Float locals keep XMM8-15 for the whole body and
are spilled to their frame slots around calls, Float literals and temporaries
run as SSE with the runtime's binary64 semantics, and a leaf loop body keeps the
raw backend's integer local registers and compare/branch fusions for the Int
bookkeeping around the Float arithmetic. This closes the `floats and loops`
guard that `native-floats.md` left open; the tag still happens under `--no-opt`
and for a Float function whose value escapes into dynamic code (see Limits).

## Changes

### `src/words.may`

- `word_candidate` no longer rejects a body that has both Floats and loops, and
  the now-unused `WordScan.loops` tracking is gone. A Float body with a loop is
  a native-word function like a straight-line one.
- The header comment records that loop bodies are supported; the Float-globals
  and `--no-opt` limits are unchanged.

### `src/ir.may`

`ir_node` recorded a value's checked type on the value returned by the inner
lowering. For a statement node that return value is the statement's operand (a
`let` returns its initializer), so the statement's own type — nil — overwrote
the expression type the inner lowering had just set. Consequently a `let` with
a Float initializer never looked like a Float value, and the backend's Float
local homes only ever covered parameters. The type is now recorded only for
expression nodes (`E_INT`..`E_PATTERN`), which is the value the type belongs to.
This is what makes declared Float locals (not just parameters and temporaries)
actually use XMM homes.

### `src/backend/x86_64.may`

- **Float locals are planned, not declared during emission.** `x86_float_plan`
  now reserves the XMM8-15 homes of every declared Float local in declaration
  order before emission, keyed by the (already mangled, unique) internal local
  name. `cg_let` reuses that home and adds the frame slot as the spill home.
  This lets a read of a local *alias* the local's register instead of copying
  through a temporary, and it is what makes loop-carried locals stay in XMM
  across iterations.
- **Coalescing.** A Float temporary whose left operand's own XMM register dies
  at that instruction now takes over that register, so the usual copy into the
  result's register disappears (`x OP x` computes in place). On the mandel
  inner loop this removes three `movapd` copies per iteration.
- **Register-copy stores.** `cg_let` and `cg_assign` copy a value that already
  lives in an XMM home register-to-register instead of round-tripping it
  through RAX.
- **Leaf Float bodies keep the raw path.** `ctx.leaf` is no longer forced false
  for a Float body; a body with no calls (the common case: Float loops that
  inline `to_float`, literals and arithmetic) now uses the raw
  instruction-selection path, so Int locals get callee-saved registers and Int
  comparisons fuse into `cmp`/`jcc`. `E_FLOAT` and `to_float` were added to the
  leaf instruction/call sets. A Float body that contains a call stays on the
  simple path, which is still correct (Float homes in XMM, word arguments in
  integer registers) and unchanged in performance from `native-floats.md`.
- **Type-aware guards for that path.** A Float local is never promoted to a
  word register; `x86_borrow_operand` and `x86_accumulator_only` refuse Float
  values (their word/frame home is a spill slot only, and a Float result with
  an XMM home is not computed into RAX); `x86_select_step` refuses a region
  that computes a Float; `x86_unsigned_ranges`/`x86_local_recurrences` already
  ignore Float literals; and the promoted-local registers stay in the
  callee-saved save list (the Float filter had dropped them, which corrupted a
  caller's RBX).
- **`>` and `>=` fuse.** A Float `a > b` / `a >= b` used as a branch condition
  now emits `ucomisd` plus one `ja`/`jae`, and the negated form one `jbe`/`jb`;
  `ja`/`jae` are false for NaN, which matches the runtime's unordered
  comparison. `<`, `<=`, `==` and `!=` need two flags and keep the value form.
- **Escaped Float functions are demoted.** A native Float entry checks every
  parameter's type word up front, while a tagged generic body coerces and
  checks lazily, so an ill-typed call through a function value would produce a
  different fault message than the tagged path. After lowering, the backend
  scans the IR for `E_VAR` reads that name a native Float function; any such
  function (value taken, e.g. `let f: Any = mixed;`) is demoted back to the
  tagged ABI and gets a word adapter. Directly called functions — every
  benchmark — are unaffected. This is deliberately conservative: a later
  native-entry lowering could match the tagged dynamic-call rules and remove
  the restriction.

### Tests

- `tests/native_float_loops.may` is a new fixture. Its expected output was
  produced by the compiler before the change (the tagged path), so it is an
  oracle for the runtime semantics; `oracle.py` also compiles it with
  `--no-opt`. It covers loop-carried locals, a `let` snapshot of a local that
  is written later, `for` ranges and `to_float` inside loops, `break` /
  `continue` / early `return`, nested loops, a mandelbrot body, calls to a
  tagged and to a native Float helper inside loops (spill/reload), recursion,
  ten Float locals (ninth and later stay words), NaN through all six
  comparisons and through the fused `>` branch, `-0.0`, infinities, Float
  division by `0.0` and `-0.0` inside a loop, and Int overflow inside a Float
  loop.
- `tests/backends.py` compiles a small loop function and asserts the optimized
  build's `module0::run` body contains `mulsd`/`addsd` and an XMM8+ home, does
  not contain the fat backend's `cmp r9,0x3` Float type checks, and that the
  image and body differ from `--no-opt`.
- `tests/native_floats.may` keeps its loop and its recorded output; its
  comments no longer say the loop stays tagged.
- `native_floats/run.py` gains `float_loop_math.may` and its docstring is
  updated for the three Float loop workloads.

## Measurements

[`native-float-loops-performance.json`](native-float-loops-performance.json)
holds the raw samples, taken with
[`native_floats/run.py`](native_floats/run.py) (`--rounds 15 --cpu 2
--self-compile`) on a 13th Gen Intel i5-13500H under Linux 6.12.

- "Before" is `2def37e` built before the change and preserved with its
  sidecars; "after" is this branch. The runtime sidecars are identical
  (`1a4c10aa…`); the compiler images are `c8aac1b9…` and `e9b4372f…`.
- Every measured child was pinned to CPU 2 with `taskset`, and interleaved
  rounds alternate the order. Another workload ran on the host during the run
  (load average 3.26/3.04/2.79), so the run-to-run spread is up to about 1.5%
  even for programs whose generated image is byte-identical.
- Values are median CPU times of 15 samples after one warm-up; every workload
  printed the same output on both sides.
- `mandelbrot` and `nbody` compile to byte-identical images with both compilers
  (their Float work is top-level code or reads Float struct fields, both tagged
  boundaries), so they measure the host's noise.

| Workload | Before, ms | After, ms | Change |
| --- | ---: | ---: | ---: |
| `float_loop_math`: 20M-iteration loop with conversions and Float locals | 169.88 | 29.48 | **−82.6%** |
| `mandel_wrapped`: the Mandelbrot loop in a function | 45.62 | 43.77 | **−4.1%** |
| `float_convert`: 10M `x * to_float(k)` helper calls | 24.41 | 22.72 | **−6.9%** |
| `float_helper`: 20M one-argument helper calls | 38.48 | 37.65 | −2.2% |
| `float_loop`: a 50M-iteration Float loop in a function | 80.17 | 81.26 | +1.4% |
| `float_chain`: 10M two-argument helper calls | 27.25 | 27.54 | +1.1% |
| `float_ops`: 5M six-operation helper calls | 21.77 | 21.91 | +0.6% |
| mandelbrot, cross-language suite | 46.96 | 47.65 | +1.5% |
| n-body, cross-language suite | 87.12 | 87.30 | +0.2% |
| self-compile (compiler/mayc/main.may) | 2942.34 | 2935.10 | −0.2% |

`float_loop_math` is the shape the item targets: the tagged loop pays a type
check per operation and a runtime call for `to_float`; the native loop keeps
the accumulator and both `let` temporaries in XMM registers and runs
`cvtsi2sd`/`mulsd`/`subsd`/`divsd` inline. The gain is 5.8x, not a few percent.

`mandel_wrapped` is a smaller win because the tagged versioned fast path is
already good there: it keeps the Float locals in XMM and the counters in
callee-saved registers too. The native body replaces the fat type-word checks
with the raw fusions (`ucomisd`+`ja` for the escape test, fused loop
condition), but the loop also has two Float divisions and two literal
rematerializations per iteration, which dominate. The 4.1% is consistent across
three independent runs (−3.0%, −3.2%, −4.1%) and is the right size for the
difference in instruction count.

`float_loop` is neutral: its iteration is bound by the `mulsd → addsd`
dependency chain (about 7 cycles), so neither backend can go faster than the
latency chain. `float_convert`/`float_helper` now take the leaf raw path as
well because `ctx.leaf` is no longer forced false for every Float body, which
explains their small improvement; `float_chain`/`float_ops` are inside the
noise. The two named benchmarks do not move — their Float work is a tagged
boundary — and are the run's controls.

**Code size.** The compiler image grows from 3 106 648 to 3 135 472 bytes
(+0.9%), from the extra backend paths and the compiler's own new Float loops.
**Compiler cost.** Self-compile CPU is flat (−0.2%) and peak RSS is −2.0%
(498.3 → 488.3 MiB): the removed fat type checks and the smaller loop bodies
pay for the extra backend code.

## Tests

- `sh compiler/rust/build.sh` (stage 1 → 2 native build);
- `python3 compiler/mayc/tests/verify.py --compiler "$PWD/compiler/mayc/mayc_new"`:
  **145 passed, 0 failed**, including `oracle.py` and the new fixture;
- `python3 compiler/rust/test.py`: source-only bootstrap fixpoint, stage 2
  equals stage 3;
- `python3 scripts/check_repository.py`;
- `python3 compiler/mayc/tests/backends.py --compiler …`: pass, including the
  new native-Float-loop objdump assertions;
- `python3 compiler/mayc/tests/raw_codegen.py --compiler …`: pass.

## Limits and follow-ups

- A Float function whose value escapes into dynamic code keeps the tagged ABI.
  The native entry checks Float parameter types strictly, while a tagged
  generic body coerces an `Any` argument (an Int passed for a Float parameter
  works there) and faults later on the first mismatched operation. Making the
  native entry reproduce that rule would let the restriction go; until then
  the value-taken case stays tagged, which is why `direct_calls.may` and
  `float_registers.may` still produce their recorded output.
- The leaf raw path is only taken by call-free Float bodies. A Float function
  with calls keeps the simple path (no promoted Int locals, no fusions), as
  before. Extending type-aware selection to a call-containing body needs the
  heap-pointer/GC argument behind the leaf rule to be revisited.
- Still not native: `%`, `int(Float)`, `sqrt`, `abs`, `floor`, `ceil`, `round`,
  `min`, `max` and the other math builtins (a body that uses one stays tagged),
  Float globals (tagged type-3 values would need boxing/unboxing), and extern
  Float signatures (the FFI word bridge is Int/UInt/Ptr/Bool only). All are
  listed in `native-floats.md` and remain open.
- `float_loop`'s dependency chain and `mandel_wrapped`'s two divisions mean the
  next wins there are loop-level (hoisting literal constants into registers,
  common subexpression elimination for `zr*zr`), not more instruction
  selection.
