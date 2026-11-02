# Native Float functions — issue #132

A straight-line function whose parameters, result, locals and operations are
all `Int`, `Ptr`, `Bool` or `Float` now compiles to native-word machine code.
A Float is its binary64 bit pattern in a machine word, so the word calling
convention, the fat entry and every word adapter keep working; inside the
function XMM8-15 hold the Float locals and XMM2-7 the straight-line Float
temporaries, and `+ - * /` and the six comparisons run as SSE with the
runtime's semantics. Float bodies that contain a loop stay tagged for now: a
native loop would keep its Float locals in frame slots and lose to the fat
backend's XMM homes.

## Changes

### `src/words.may`

- `word_kind` returns `"Float"`, so a Float parameter, result and local is a
  native-word kind. `--no-opt` still rejects it, which keeps the oracle test's
  unoptimized path on the tagged backend.
- `word_value` accepts a Float literal, Float locals (but not Float globals,
  which stay tagged and would need conversion), `+ - * /` on two Floats with a
  Float result, the six ordering operators on two Floats with a Bool result,
  unary minus, `to_float(Int)` (and `to_float(Float)` as the identity), and a
  call whose result kind matches. Calls now also check each argument against
  the callee's recorded parameter kinds.
- `WordScan` records whether a Float appeared (`floats`) and whether the body
  has a loop (`loops`). `word_candidate` rejects `floats and loops`, so a
  Float loop body stays tagged. `words_mark` records `nativeFloats` on the
  function for the backend.

### `src/backend/x86_64.may`

- **Float temporaries in XMM2-7.** `x86_float_plan` gives a register to each
  Float temporary defined once, read at least once and not live across a call,
  in definition order, reusing it after the last reader. A temporary that is a
  direct read of a Float local is *aliased* to the local's register instead
  (`X86_FLOAT_ALIAS`), so it gets no home and emits no code.
- **Float locals in XMM8-15.** Parameters get one in the prologue and a `let`
  declared with a Float initializer gets one at its declaration. Every call
  spills the declared local registers to their frame slots and reloads them
  (SSE registers are caller-saved); a tail call stores new arguments in the
  parameter registers. A ninth Float local stays a word.
- **Operations.** `cg_float_bin` computes in the result's register when it has
  one, else in the left operand's own temporary register, and leaves the bits
  in RAX for a word home. `/` tests the divisor bits with
  `lea r10,[rcx+rcx]; test r10,r10` and raises the arithmetic fault on ±0.0;
  a NaN divisor does not fault. Comparisons use `ucomisd` (operands swapped
  for `<` and `<=`) with `sete/setnp/and` for `==`, `setne/setp/or` for `!=`
  and `seta`/`setae` for the orderings, so NaN is unordered. Unary minus flips
  the sign bit. `to_float(Int)` is `cvtsi2sd`. A Float literal is `movabs`.
  Float local reads and stores move between the local's XMM register and the
  temporary's.
- **Simple path.** A Float function is emitted with `ctx.leaf = false`, i.e.
  the simple instruction-selection path without the raw fusions, local
  registers and compare-and-branch selection, because those assume word
  values. `x86_branch_comparison_at` also bails out for a Float body.
- **Frame** slots of Float locals and parameters are only used as their spill
  slots; the frame sizing is unchanged.

### `src/backend/x86_64_fat.may`

`fat_native_type` maps a native kind to its fat type word: 1 for Bool, 3 for
Float and 2 otherwise. The fat entry checks and tags Float parameters and
results with it, and the word adapters box a Float argument as type 3 with its
raw bits (no Int tagging, no overflow check) and untag a Float result without
shifting. A direct call from fat code to a native-word function uses the same
mapping for its argument type checks.

### `src/ir.may`

The emission snapshot records `nativeFloats` so the backend can pick the Float
path without rescanning the body.

## Measurements

[`native-floats-performance.json`](native-floats-performance.json) holds the
raw samples, taken with
[`native_floats/run.py`](native_floats/run.py) (`--rounds 15 --cpu 2`) on a
13th Gen Intel i5-13500H under Linux 6.12.

- "Before" is `62c3c45` built in a separate worktree and preserved with its
  sidecars; "after" is this change. The runtime sidecars are identical
  (`1a4c10aa…`); the compiler images are `5468034f…` and `536ed0eb…`.
- Every measured child was pinned to CPU 2 with `taskset`, and interleaved
  rounds alternate the order, so load drift hits both sides alike. Another
  workload ran on the host during the run, at a load average of 4.6.
- Values are median CPU times of 15 samples after one warm-up; every workload
  printed the same output on both sides.

| Workload | Before, ms | After, ms | Change |
| --- | ---: | ---: | ---: |
| `float_helper`: 20M one-argument helper calls | 39.16 | 37.99 | −3.0% |
| `float_chain`: 10M two-argument `a * c + b` helper calls | 35.29 | 26.18 | **−25.8%** |
| `float_convert`: 10M `x * to_float(k)` helper calls | 51.92 | 24.57 | **−52.7%** |
| `float_ops`: 5M six-operation helper calls | 38.08 | 21.43 | **−43.7%** |
| `float_loop`: a 50M-iteration Float loop in a function (still tagged) | 79.98 | 80.20 | +0.3% |
| `mandel_wrapped`: the Mandelbrot loop in a function (still tagged) | 45.76 | 45.78 | 0.0% |
| mandelbrot, cross-language suite (top-level) | 47.71 | 47.85 | +0.3% |
| n-body, cross-language suite | 80.96 | 81.73 | +1.0% |

The helpers show the win: a tagged Float helper pays a fat call, a 16-byte
value pair per argument and a type check per operation, and `to_float` is a
runtime call; the native helper is a prologue, the SSE operations and a `ret`.
The one-argument multiply helper gains least (−3%) because its call and latency
chain dominate; the wider expressions and the conversion gain 26–53%.

**The named benchmarks do not move.** The cross-language Mandelbrot is top-level
code, which is a tagged `main` (the "main as native" item, not this one), and
n-body's Float arithmetic reads `struct` fields on a `List<Body>` and runs in
loops, both tagged boundaries; its functions therefore do not become
native-word functions. The two controls in the table confirm that a Float body
that stays tagged is unchanged, since its code is untouched.

**Code size.** The compiler image grows from 2 964 768 to 3 035 664 bytes
(+2.4%), from the Float paths in the backend and the Float helpers in the
compiler's own code.

## Tests

- `tests/native_floats.may` is a new feature fixture whose output was produced
  by the compiler before Float became a native-word kind (recorded in
  `tests/legacy_behavior.json`). It covers:
  - straight-line arithmetic, including a six-operation expression and unary
    minus (with `-0.0`);
  - mixed `Int`/`Float` parameters and results, and `to_float` conversions;
  - all six comparisons, comparisons in `if` conditions and Bool-returning
    helpers, NaN comparisons (unordered), infinities and negative zero;
  - a native function calling a tagged word-compatible function, so the word
    adapter boxes and unboxes Float values;
  - Float recursion with a tail call and a Float accumulator;
  - Float division by ±0.0 raising the arithmetic fault, a NaN divisor
    returning NaN, and Int overflow inside a Float function;
  - a function value calling a native Float function's tagged entry;
  - a Float loop body, which stays tagged and still produces the same output.
- `tests/oracle.py` compiles the fixture with and without `--no-opt` and
  requires identical output, as it does for every fixture; the native and
  tagged paths agree.
- With the rebuilt compiler:
  - `make check`;
  - `make test-compiler`: 138 passed, including `raw_codegen.py`,
    `backends.py` and `oracle.py`;
  - `make test-bootstrap`: source-only stage 2 equals stage 3;
  - `raw_codegen.py` and `backends.py` run directly: pass.

## Limits and follow-ups

- **Float loop bodies** are the main remaining piece. They need XMM homes for
  Float locals and temporaries in a loop body of a native function, which is
  the same scheme the fat backend already uses; the raw backend's loop
  register allocation assumes machine words, so this was left out of this
  increment and the loop stays on the tagged versioned path, which is already
  fast.
- **Float globals** are tagged and keep a function from being native; a Float
  global would need a boxing conversion at its reads and writes.
- **More operations:** `%`, bitwise operators, `int(Float)`, `sqrt`, `floor`,
  `ceil`, `trunc` and the other math builtins are not inline; a function that
  uses one stays tagged. `int(Float)` needs the runtime's truncation and
  overflow rules; the math builtins could use SSE (`sqrtsd`, `roundsd`).
- **Extern `Float` arguments and results** are not passed natively yet; the
  FFI word bridge only covers Int/UInt/Ptr/Bool.
- The Float path forces the simple instruction-selection path, so an Int
  operation inside a Float function also loses the raw fusions. A type-aware
  instruction selection would recover that.
