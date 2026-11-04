# Native Float builtins — issue #132c

This increment was meant to land the remaining named Float gaps (`int(Float)`,
native `sqrt`/`abs`/`floor`/`ceil`/`round`/`min`/`max`, `%`, extern Float
signatures and Float globals). The timebox went to a **pre-merge correctness
bug in the previously landed native Float main** instead: the native main's
`print` lowering could read an argument temporary out of a caller-saved
register after an earlier argument's print helper had clobbered it. That bug is
fixed and covered by a fixture in this increment; the builtin gaps are recorded
below as not landed.

## Fixed: native-main print arguments must be reified before the helpers run

### Symptom

A top-level program whose `main` is native (all values Int/Bool/Float words)
and that prints several computed values could print a corrupted later value:

```may
fun k1() -> Float { return 1.5; }
print(k1(), k1());
```

On the branch tip before this commit this printed `1.5 5e-324` (the second
argument read as raw bits `1`), while `main@2def37e` printed `1.5 1.5`. The
same corruption appeared with `print(2.5, k1())` and with three or more
arguments, for Float and for Int temporaries.

### Cause

`words`/IR model `print(a, b, c)` as a single `E_CALL`, but the native main
lowers it to a sequence of calls (`rt_space`, `rt_print1` per argument). The
raw register allocator therefore sees one call point and may keep an argument
temporary in a caller-saved register (`r10`/`r8`/`r9`) whose live range ends at
that point. The emitted helper calls run *between* the argument reads, so the
earlier helper clobbers the register holding a later argument. The bug did not
show on the pre-Float native main in the fixtures because their print
arguments happened to be assigned callee-saved homes; multi-argument Float
print made it easy to hit.

### Fix

`x86_word_main_print` now first evaluates every argument and stores the word in
its own frame slot (`0warg`, one slot per argument), and only then runs the
box-and-print sequence, reloading each argument from its slot. `print` is not
on any benchmark's hot path, so this costs a few stores per printed argument
and nothing in the measured workloads.

`tests/main_native_floats.may` now covers it: several native Float calls in one
`print`, and a Float local interleaved with calls (`print(base, poly(base),
base, poly(base) + base, base)`). Expected output remains the tagged compiler's
output and `--no-opt` still produces the same bytes, so the oracle covers it.

## Not landed: the named Float builtins

The remaining gaps were not committed. A prototype patch (reverted, not part
of this branch) lowered `sqrt`/`floor`/`ceil` via `sqrtsd`/`roundsd` and
`round`/`abs`/`min`/`max`/`int(Float)` through marked call sites, and matched
the tagged runtime byte-for-byte on a NaN/-0.0/infinity/rounding-mode fixture.
It was dropped because the correctness fix above consumed the timebox and a
second full gate run (verify + bootstrap) could not be completed within it; the
Lead's merge should not wait on it. Findings for whoever picks it up:

- `%` on Floats is **not defined** by the language: strict typing rejects
  `Float % Float` (the `%` operator is integer-only), so there is no gap to
  close there.
- `sqrt`/`floor`/`ceil`/`round` accept an Int or a Float argument and return
  Float (`st_number`); `abs` returns its argument's type; `min`/`max` return
  one of their two arguments. `rt_sqrt`/`rt_floor`/`rt_ceil` are exactly
  `__fbits(4/5/6)`, i.e. `sqrtsd`/`roundsd`, so the SSE lowering is
  runtime-identical.
- `round` is `floor(x)` plus a `>= 0.5` step toward positive infinity;
  `roundsd`'s nearest-even mode is *not* the runtime's rule.
- `abs` preserves `-0.0` and NaN bits (`if cmp(x, 0) < 0 then -x else x`), so
  `andpd` with the sign mask is *not* runtime-identical.
- `min`/`max` return the first argument on a tie **and on an unordered (NaN)
  pair**; `minsd`/`maxsd` return the second operand for NaN, so a
  `ucomisd` + `jbe` (min) / `jp`+`jae` (max) select is needed.
- `sqrt`/`floor`/`ceil` are compiler builtins with no library function, while
  `round`/`abs`/`min`/`max` are also defined in `native.may` and are normally
  reached as library calls; the scan must distinguish the library definition
  (module path empty) from a user redefinition, and the backend must intercept
  the marked call *before* `backend_find_func`.
- `int(Float)` (`trunc` toward zero) faults `Float outside Int range` for NaN,
  infinities and out-of-range values; the native fault kinds have no such
  message, so it needs a new `rt_native_fault` kind in `runtime/fat.may`
  (a sidecar change) rather than reusing the integer-overflow message.
- Extern Float signatures need the SysV XMM argument/result bridge in
  `x86_64_ffi.may`; Float globals are tagged type-3 values and need a payload
  read plus a type-word write, with the tagged path's type checks.

## Gates

Committed tree (native-main print fix + fixture):

- `sh compiler/rust/build.sh`: ok;
- `python3 compiler/mayc/tests/verify.py --compiler "$PWD/compiler/mayc/mayc_new"`:
  **146 passed, 0 failed**, including the updated `main_native_floats.may` and
  `oracle.py`;
- `python3 compiler/rust/test.py`: source-only bootstrap fixpoint, stage 2
  equals stage 3;
- `python3 scripts/check_repository.py`: pass.

No performance claim is made for this commit; the executable change only
touches `print` in a native main. A paired check
([`native-float-builtins-performance.json`](native-float-builtins-performance.json),
9 CPU-time samples per side, ABAB, CPU 2 pinned, identical output) confirms the
previously reported numbers are unchanged: `float_main` 166.46 -> 29.28 ms
(-82.4%), xlang mandelbrot 45.72 -> 42.98 ms (-6.0%), n-body control
76.86 -> 77.35 ms (+0.6%, spread).
