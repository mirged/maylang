# Main as native — issue #132

Main's top-level statements now compile to native-word code when every binding
they use was demoted to a main local (#101) and every value and operation is a
machine word. On the cross-language suite that is collatz (a top-level `Int`
loop) and fib (a single call into a native-word function); the other six keep
the tagged main. The collatz loop drops from 87.70 to 43.73 ms, the 2.4× that
the same loop still lost at the top level on the phase-3 reference.

**Coverage correction.** The first version of this change shipped
`tests/main_native.may`, but its string-literal prints are a dynamic boundary:
the fixture exercised the tagged fallback, not the native path, and its image
was byte-identical to the parent compiler's. This version adds
`tests/main_native_words.may`, a word-only fixture that does take the native
path, pins its tagged output in `legacy_behavior.json`, and asserts the path
in `backends.py`; `tests/main_native.may` stays as the tagged-fallback
fixture. The collatz measurement was native all along (it prints one computed
`Int` and nothing else).

## Changes

### Deciding

`x86_main_native` scans the lowered main IR after the main-local demotion,
before any body is emitted. The tagged main stays the general fallback: the
scan requires strict typing, the dynamic runtime, no boxed main binding, and
every value to be an `Int`, `Bool` or `Ptr` word. It rejects:

- a `Float` value, which keeps mandelbrot on the tagged versioned path (that
  path already keeps its Float locals in XMM homes; a native top-level loop
  would keep them in frame slots and lose);
- a binding that stayed global, a function value, and a call through a local;
- `nil` with a reader, strings, lists, maps, structs, indexes, fields,
  closures, handlers, range lists and every runtime instruction;
- a call whose callee is not word-compatible, or whose argument or result
  kind is not a word kind. A word-compatible but still tagged callee (one
  whose body cannot be native, say because it prints) is reached through its
  word adapter; the scan records it so the adapter is emitted.

The allowed builtins are `print`, `exit`, `syscall`, `load8`..`load64` and
`store8`..`store64`. Unused `nil` results (a loop or an if used as a
statement) are fine; reader counts decide that.

### Emitting

`x86_native_main` emits label 1 with the raw native codegen: prologue, `rt_init`,
a `rt_gc_root` for each remaining global through the raw trampolines, the body
via `cg_ir`, the epilogue and the out-of-line native-fault stubs. The root loop
is load-bearing, not defensive: the scan rejects global *references from main*,
but `ctx.globals` still holds the runtime's own state and any user binding a
function reads or writes, and dynamic mode has to register all of them. It uses the
optimized raw path (`ctx.leaf`) rather than the simple one, which is where the
win is: loop-hot locals are promoted to callee-saved registers and arithmetic
fuses. Values in registers across a call are still rooted by the existing
per-call root stores and by `rt_gc`'s callee-saved marking, and `print` is
declared a preserving call for this planner because the runtime helpers it
calls preserve the callee-saved registers.

`print` is the one dynamic boundary: `x86_word_main_print` boxes each word as a
fat value (`Int`/`Ptr` type word 2, `Bool` type word 1) and calls `rt_print1`,
`rt_space` between arguments and `rt_newline`, through the runtime's raw
trampolines. Boxing is identity: a fat `Int`/`Bool` payload is the machine
word, so no conversion and no range check is needed.

`cg_program` runs the direct-call prepass (so the functions' own call sites
keep their register convention) and then picks the native main when the scan
passes, the tagged `fat_main` otherwise. `--no-opt` and `--raw` never take the
native path, and a main with a string, list, map, struct, closure, Float,
handler or remaining global keeps the tagged path unchanged.

`src/ir.may` records `wordCallable` in the emission snapshot, so the scan can
tell a word-compatible tagged callee from any other function.

## Measurements

[`main-native-performance.json`](main-native-performance.json) holds the raw
samples, taken with [`main_native/run.py`](main_native/run.py) (`--rounds 15
--cpu 2`) on a 13th Gen Intel i5-13500H under Linux 6.12.

- "Before" is `40ae868` built in a separate worktree and preserved with its
  sidecars; "after" is this change. The runtime sidecars are identical
  (`1a4c10aa…`); the compiler images are `9eba1600…` and `c68e8de3…`.
- Every measured child was pinned to CPU 2 with `taskset` and interleaved
  rounds alternate the order. Other workloads ran on the host at a load
  average of 6.1, so the absolute times are higher than on an idle machine
  and the tagged collatz build is the most cache-sensitive workload here.
- Values are median CPU times of 15 samples after one warm-up; the change
  column is the median of the per-round after/before ratios, which cancels
  slow rounds. Every workload printed the same output on both sides.

| Workload | Before, ms | After, ms | Change |
| --- | ---: | ---: | ---: |
| collatz, seeds 1..300000, top-level loop (native main) | 87.70 | 43.73 | **−50.4%** |
| fib(35) (native main, one call into native fib) | 57.56 | 57.27 | +0.3% |
| sieve (tagged main) | 193.54 | 201.35 | +0.8% |
| hashmap (tagged main) | 93.12 | 90.65 | −1.9% |
| strings (tagged main) | 48.74 | 50.28 | +0.1% |
| mandelbrot (tagged main, Float) | 45.54 | 45.88 | −0.2% |
| n-body (tagged main, structs) | 76.14 | 76.07 | +0.0% |
| binary trees (tagged main, structs) | 842.94 | 993.56 | +2.4% |

collatz is the target: the top-level loop is the same machine code a native
`Int` function would get, so the 2.4× overhead of 16-byte frame slots, type
words and runtime calls is gone. fib's main is native too, but its work is one
call into the native `fib` function, so the difference is inside the spread.
The other six keep the tagged main by design (`mandelbrot` because its values
are Float, `nbody`/`trees` because they read struct fields and lists, `sieve`,
`strings` and `hashmap` because they build lists, maps and strings); their
differences are run-to-run spread, and the two builds produce the same output.

**Code size.** The compiler image grows from 3 056 520 to 3 102 320 bytes
(+1.5%), from the scanner, the native-main emitter and the `print` lowering.

**Compiler self-compile cost.** Independent measurement of the first version
of this change recorded a +7.5–8.6% cost to compiling the compiler with the
new binary. That version ran the direct-call prepass twice — once in
`cg_program` for the new dispatch and once inside `fat_main` — and the fix
commit removes the duplicate. On this host, a pinned 15-round interleaved A/B
of `compiler/mayc/main.may` compiled by `40ae868` and by the fixed compiler
measured +0.36% on the medians and +0.03% on the paired median; the earlier
commit measured +0.2% here before the prepass was removed, so the magnitude
of the independent figure was not reproduced on this machine and the fix
removes the only duplication the commit introduced.

## Proof the native path is taken

- `tests/main_native_words.may` compiled by the parent compiler (`40ae868`,
  before main had a native path) and by this compiler produces different
  images (110 240 bytes against 114 376) and identical output. The old
  `tests/main_native.may` was byte-identical to the parent compiler's image
  (114 584 bytes) in both builds, which is how the missing coverage was
  found.
- The native main boxes a printed argument by pushing the fat type word as an
  immediate: `push 0x2; push rax` for an `Int`, `push 0x1; push rax` for a
  `Bool`, followed by the trampoline call. Those two sequences occur 19 and
  10 times in the word-only fixture's optimized image and zero times in the
  parent compiler's image and in the `--no-opt` image.
- `backends.py` asserts this: it compiles a small word-only main both ways,
  requires the images to differ, requires both boxing sequences in the
  optimized disassembly, requires neither in `--no-opt`, and requires
  identical stdout (`135` and `true`).

## Tests

- `tests/main_native_words.may` is the word-only fixture that takes the native
  path. Its output was produced by `40ae868` (recorded in
  `tests/legacy_behavior.json`) and equals the `--no-opt` tagged main. It
  covers:
  - a collatz-style nested `Int` loop with a call in the body;
  - `for` over `a..b` and `a..=b`, `break`, `continue` and an accumulating
    `while`;
  - `Bool` locals, comparisons and `and`/`or`/`!`, printed as `Bool`;
  - division, modulo, shifts, bitwise operators and unary minus, including
    negative operands (the demotion pass now ignores a synthetic `__wordN`
    function's parameter names, so a bitwise expression on a main local no
    longer keeps that binding global);
  - calls to native-word functions and nested calls in argument position;
  - no string literal and no other dynamic value, so the scan accepts it.
- `tests/main_native.may` is the tagged-fallback companion: its string-literal
  prints disqualify it by design, and it pins the tagged main's behavior,
  including a word-compatible tagged callee reached through its word adapter
  and a final uncaught division fault (exit 70).
- `tests/oracle.py` compiles every fixture with and without `--no-opt` and
  requires identical behavior, so every fixture whose main qualifies is a
  native-versus-tagged oracle as well. `--debug` was also compared by hand for
  a fault inside a function called from a native main: identical output and
  exit status.
- With the rebuilt compiler:
  - `make check`;
  - `make test-compiler`: 143 passed, including `raw_codegen.py`,
    `backends.py` and `oracle.py`;
  - `make test-bootstrap` run twice: source-only stage 2 equals stage 3 both
    times;
  - `raw_codegen.py` and `backends.py` run directly: pass.
  - a collatz-style nested `Int` loop with a call in the body;
  - `for` over `a..b` and `a..=b`, `break`, `continue` and an accumulating
    `while`;
  - `Bool` locals, comparisons and `and`/`or`/`!`, printed with the other
    arguments (Bool boxing);
  - division, modulo, shifts, bitwise operators and unary minus, including
    negative operands;
  - calls to a native-word function, to a word-compatible tagged function
    (whose body prints, so the word adapter boxes the argument), and nested
    calls in argument position;
  - an empty `print()` and a final division by zero: the uncaught arithmetic
    fault exits 70 with the same output on the tagged main.

## Limits and follow-ups

- Only `Int`, `Bool` and `Ptr` words are native. `Float` keeps the tagged
  main, which is what mandelbrot wants for now; making Float top-level loops
  native needs the same XMM-home scheme the fat backend already uses (native
  regions).
- Strings, lists, maps, structs, closures, handlers and any remaining global
  keep the tagged main. That is the general fallback, not a gap in this
  increment: collatz needed none of them, fib only needs a call and `print`.
- `print` is the only dynamic builtin the native main understands; other
  builtins (`str`, `len`, `push`, ...) fall back. A native main calling a
  tagged function that returns a heap value would also fall back, because the
  scan rejects non-word results.
- The scan works on main's fat-lowered IR and relies on the demotion pass
  having removed every global main names; a future change to demotion or to
  the IR shapes must keep the scan's assumptions. The reader-count pass is
  deliberately independent of the allocation passes. The fix also taught
  demotion to ignore the parameters of synthetic `__wordN` bitwise helpers,
  which is what lets a word-only expression over a main local stay a local.
- The native main uses the optimized raw path with calls, which no other
  dynamic-mode body does. It is safe here because every value is a word and
  the per-call root stores plus `rt_gc`'s callee-saved marking cover register
  values; a `Ptr` that somehow named a heap object would still be covered only
  if it lives in a callee-saved register or a rooted temporary, which is the
  same guarantee raw programs rely on.
