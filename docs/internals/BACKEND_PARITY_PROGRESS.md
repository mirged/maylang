# Backend parity progress and handoff

> The experimental `clang-llvm` backend described below has since been
> removed: mayc is its own toolchain and emits every executable directly.
> The LLVM notes remain as a record of that work.

This branch advances backend support; **full language and standard-library
parity is not complete**. The requested scope includes both language features
and all standard-library OS APIs, including files, processes and networking.

Branch: `feat/backend-parity-progress`.
Starting revision: `beb593cdcffb2ff4c30db060686c3eb312807d62`.
Latest implementation milestone: portable numeric support (see
[Numeric support](#numeric-support)).

The three x86 code-alignment changes from `origin/main` (`a2a3d35`, `5373bed`,
`3bdbe0e`) were merged into this branch in `cb48c83`; the only conflict was the
`--help` text, which keeps both the new `--no-code-align` flag and this
branch's runtime-neutral `--debug` description. No version bump or performance
claim is part of this work.

## What changed

### Shared frontend and runtime correctness

- Strict extern signatures now accept `UInt` as an integer and `Void` as a
  `Nil` return type.
- `yield()` and `run()` have `Nil` result types. `yield()` returns `nil` both
  inside and outside a running fiber; integer bindings of scheduler results
  are rejected.
- Recursive local closures allocate their shared capture cell before the
  closure captures itself. This fixes recursive local function calls in native
  and LLVM builds as well as the portable targets.
- Fibers preserve their own exception-handler stacks, caught errors and source
  traces. A suspended worker cannot borrow another fiber's handlers.
- Exception unwinding preserves the integer registers used for allocation.
  Exhausting the 64 active-handler limit raises a catchable fault.
- Scalar float formatting recognizes nonfinite values as `nan`, `inf` and
  `-inf` in both runtimes.

### LLVM on Linux x86-64

- Typed scalar extern calls support integer, unsigned, floating, pointer,
  string, Boolean and void bindings, mixed register/stack arguments and
  first-class extern function values.
- Reachable bindings resolve through `dlopen`/`dlsym` before user statements;
  unused bindings and libraries are pruned. Missing libraries or symbols
  produce runtime diagnostics.
- Cooperative fibers use an aligned entry trampoline and context switch.
  Exception handlers use the active fiber's handler storage.
- Regression tests compare LLVM and direct native behavior for extern calls,
  library constructors, fibers, caught errors and debug traces.

### Portable native runtime

The portable implementation covers `x86_64-linux --runtime core`,
`arm64-linux`, `riscv64-linux`, `arm64-macos` and `x86_64-windows`.

- Insertion-ordered maps, records, structs and enums support property/index
  access, mutation, spread, pattern matching and cycle-safe display. String
  keys use a hash index.
- Closures, first-class functions, nested/shared captures, recursive local
  functions and overloaded struct operators use the common tagged ABI.
  Higher-order helpers include `map`, `filter`, `reduce`, `any`, `all`,
  `count`, `each` and `times`.
- ARM64 and RISC-V calls support arguments beyond the first eight registers,
  including indirect calls and nil padding. Code-address relocations support
  callable values; ARM64 references also work after a Mach-O image slide.
- ARM64/RISC-V exclusive ranges no longer accidentally include the endpoint.
- `may`/`otherwise` handles explicit, type and arithmetic faults, with caught
  error records and optional `--debug` traces. Return, break, continue and
  rethrow behavior have regression coverage.
- Cooperative fibers preserve captures, caught errors, handlers and traces.
  The scheduler permits 128 fibers per process, each with a 256 KiB stack.
- Binary64 literals, arithmetic, comparisons and conversions work across all
  targets. Float32 annotations round at typed boundaries. Square roots,
  absolute values, floor/ceil/trunc/round, `pi` and `e` are available.
  Tests compare literal/arithmetic bits, signed zero, binary32 rounding and
  conversion limits against the full runtime.
- Scalar decimal/scientific formatting is available. Scientific normalization
  uses decimal scaling in core and platform math in full builds, so the last
  displayed digits can differ. Nested float display retains the existing
  full runtime's `str_of` behavior, including its rounding limitations.

The [compiler capability matrix](../../compiler/mayc/README.md) and generated
reference documents have been updated. The optional emulation workflow and
native-loader fixtures include the new portable cases.

### Numeric support

The second session completed most of remaining item 2 (numeric support).

- **Portable transcendentals.** `runtime/corelib.may` implements `sin`, `cos`,
  `tan`, `ln`, `log2`, `log10`, `exp` and floating powers using only binary64
  arithmetic and bit inspection, so every core target produces identical bits.
  The kernels follow fdlibm/musl: Cody-Waite reduction below 2^20·π/2 and a
  Payne-Hanek reduction with a 1440-bit 2/π table above it, musl's `__tan`,
  fdlibm `e_pow.c` (extended-precision log2 split) and an exp kernel whose
  Taylor tail is added with compensation. Measured against glibc on 784 seeded
  inputs, including trigonometric arguments up to 1.8e308, every result is
  within one ulp and most are identical.
- **One `pow` contract.** `pow` always returns a Float on every backend (the
  core runtime returned an Int for Int operands, the full runtime crashed).
  `**` keeps exact integer powers; negative integer exponents now produce a
  Float in core as they already did in the full runtime. All three runtimes
  follow C99 special cases for zeros, infinities, NaN and negative bases with
  integer exponents. The full runtime implements them in `rt_fpow` around the
  x87 sequence; LLVM uses libm.
- **Correctly rounded literals.** The compiler converted float literals by
  accumulating digits and scaling by powers of ten in binary64, which
  misrounded 349 of 475 sampled literals by one or two ulps (including most
  17-digit `repr` values). `src/literals.may` now converts with exact big
  integers and round-half-even, covering subnormals, overflow and halfway
  cases, for the direct, portable and LLVM backends.
- **Crash fixes found on the way.**
  - Direct x86-64 code passed Int arguments to `sqrt`, `floor`, `ceil`,
    `round`, `trunc`, `sin`…`exp` unconverted, which segfaulted in both full
    and core builds. User code now converts tagged Ints first.
  - The full runtime's `exp(±inf)` returned NaN; `rt_exp` handles infinities
    before the x87 sequence (through a new internal `__fexp` intrinsic).
  - `Float != nil` (and `<` against non-numbers) dereferenced `nil` as a float
    box on every backend; only numbers convert now.
  - The full runtime raised "division by zero" when displaying values below
    about 1e-323; `float_norm` scales subnormals before dividing.

### Numeric follow-up

- **Shared math sidecar.** `runtime/math.may` is loaded by the full, LLVM and
  core runtimes. `native.may` routes `sin`/`cos`/`tan` to it, fixing the x87
  results (wrong near multiples of π, unchanged above 2^63); `corelib.may`
  routes all transcendentals to it.
- **Core heap release.** Core never frees, so a loop of 200,000 `sin`/`exp`/`ln`
  calls used to stop with "core heap limit exceeded". Pure math, parsing and
  formatting calls now record the bump pointer and release their temporaries
  before re-boxing the result (strings travel in four Ints across the release).
- **Display and parsing.** Every runtime prints the shortest digits that parse
  back to the same value (Steele-White/Burger-Dybvig digit generation), in the
  existing layout, including nested values (previously six decimals) and `-0.0`.
  `float(text)` and JSON numbers use an exact fast path for ≤ 15 digits and
  |exponent| ≤ 22 and exact big-integer conversion otherwise. 2,198 random
  values print exactly as Python's `repr` digits and parse back bit for bit.
- **Comparisons.** Values of different types cannot be compared. Strict mode
  rejects `Int` vs `Float`; dynamic `==` across types is `false` and `!=` is
  `true`; ordering raises a `type` fault. Operators call `rt_op_*`, while
  library equality and `match` keep the total `rt_eq`. Making `==` fault as
  well was rejected because the compiler, tools and stdlib use `0` as an object
  sentinel (`while (item != 0)`) at hundreds of sites. Numeric `Any` code in
  `stdlib/` normalizes with `to_float`.

Measured on this machine (single runs, wall time):

| Workload | Full | Core | LLVM |
| --- | --- | --- | --- |
| 600k `sin`+`exp`+`ln` calls, before | 0.05 s | heap exhausted | 0.28 s |
| same, after (portable trig) | 0.36 s | 0.60 s | 2.7 s |
| 100k `str(x)` + `float(text)` round trips, before | 7.1 s | heap exhausted | not run |
| same, after | 5.6–6.3 s | 5.1 s | 108 s |
| 50k `str(x)` | 1.47 s | 1.39 s | not run |
| 50k `float(text)`, 3 of 5 inputs with 16–17 digits | 1.00 s | 0.76 s | not run |

Display costs about 30 µs per value and long-input parsing about 20 µs on
x86-64; one conversion is about two million emulated RISC-V instructions,
which is why `float_text.py` emulates small batches. Faster paths (inline
two-limb Dragon4 for ordinary magnitudes, Clinger-style correction instead of
long division for 16–19 digits) remain possible.

## Current boundaries

| Area | Direct full Linux x86-64 | LLVM Linux x86-64 | Portable native runtime |
| --- | --- | --- | --- |
| Collections, closures and pattern matching | Supported | Supported | Supported |
| Recoverable faults, traces and cooperative fibers | Supported | Supported | Supported |
| Basic Float/Float32 operations | Supported | Supported | Supported |
| Transcendental functions and floating powers | Supported (x87) | Supported (libm) | Supported (≤ 1 ulp) |
| Typed scalar extern calls | Supported | Supported | Still missing |
| File/process/network standard-library APIs | Existing Linux APIs | Existing Linux APIs | Still missing |
| Heap reclamation | Conservative GC | Conservative GC | Process lifetime; 256 MiB cap |

LLVM remains a Linux x86-64 full-runtime backend. This work does not make LLVM
a cross-platform backend or enable `--runtime full` on other native targets.

## What remains

1. **Platform FFI and loader support.** Implement typed C argument/result
   marshaling for AArch64, RISC-V and Windows x64. Add target-specific ELF,
   Mach-O and PE imports, startup initialization and library handling. Test
   register/stack mixtures, Float32, function values, constructors, errors and
   pruning with actual platform libraries. LLVM resolves explicit libraries
   individually while native ELF uses loader symbol lookup; this distinction
   also needs a deliberate parity decision.
2. **Numeric follow-ups.** The numeric gaps recorded after the first numeric
   session are resolved (see [Numeric follow-up](#numeric-follow-up)). Still
   open:
   - Full builds keep x87 `ln`/`log2`/`log10`/`exp`/`pow` and LLVM keeps libm
     for speed, so those can differ from core in the last place (all within
     one ulp). Trigonometry, display and parsing are identical everywhere.
   - Floats are boxed, so portable math costs about 1–2 µs per call on the
     full runtime and more under LLVM, and exact display/parsing costs
     20–30 µs per value; measurements are below.
   - NaN compares equal to itself (`nan == nan` is `true`) on every backend,
     following the old COMISD flag mapping rather than IEEE 754.
   - `contains`/`index_of` accept only strings but strict mode does not check
     their arguments; passing a list crashes.
3. **All standard-library OS APIs.** Port file and directory operations,
   binary/Unicode I/O, stdin/input, arguments/environment, clocks/sleep,
   process execution/waiting/status/inheritance and networking. Linux syscall
   numbers and layouts cannot simply be reused on Darwin or Windows.
   Platform constants, error translation, resource ownership, short I/O and
   cleanup need observable integration tests. Console output, allocation and
   process exit are the portable OS primitives implemented so far.
4. **Remaining library surface and semantic differences.** Audit every
   documented builtin/module against the capability matrix, including pure
   helpers and JSON. Core still has structural list equality while the full
   runtime uses list identity; scalar formatting differences are described
   above. These are existing or documented boundaries, not completed parity.
5. **Memory and compiler capacity.** Core retains allocations until exit and
   has a 256 MiB cap. ARM64/RISC-V emission limits individual stack frames to
   2000 bytes. Remove or deliberately specify these limits for larger programs
   and compiler self-hosting on those targets. The full runtime's existing
   sustained-allocation GC issue [#2](https://github.com/mirged/maylang/issues/2)
   is not fixed by this series.
6. **Actual target execution.** Run the expanded fixture suite on real Windows
   and Apple Silicon macOS hosts, including signing/loader checks. Add real
   AArch64/RISC-V Linux execution, especially when FFI and OS support arrive.
   Emulation validates generated instructions and simulated OS contracts;
   it does not establish real loader or library compatibility.

## Validation completed

### Numeric follow-up and comparison rule

Run with `MAYLANG_STDLIB` unset so the checkout's stdlib is tested (a shell
that points it at an installed toolchain silently tests that copy instead).
Unicorn came from temporary dependencies outside the repository.

| Command | Result |
| --- | --- |
| `sh compiler/rust/build.sh`, `make check` | Passed |
| `make test-compiler MAYC=compiler/mayc/mayc_new` | 121 passed, 0 failed (adds `float_text.py`) |
| `make test-compliance`, `make test-docs`, `make test-llvm` | Passed (69 compliance cases, 25 strict doc examples) |
| `make test-rust`, `make test-bootstrap` | Passed; stages 2/3 byte-identical |
| `make test-tools`, `make test-ui`, `make test-browser` | Passed |
| `make test-distribution`, `make test-installer` | Passed |
| `raw_codegen.py`; `backends.py`, `core_runtime.py`, `portable_values.py`, `float_math.py`, `float_text.py` with `--require-emulation` | Passed on all five targets |

The first commit's tree was also checked on its own in a separate worktree
(`make check`, 121 compiler checks, emulated `portable_values.py`). Real
Windows/macOS hosts and the four-generation `run.sh` were not run.

### Numeric support session (after merging `origin/main`)

The compiler was rebuilt from source after the last compiler edit. `MAYC` was
set explicitly. Unicorn was supplied from temporary dependencies outside the
repository through `PYTHONPATH`/`LD_LIBRARY_PATH`; nothing from them is
committed.

| Command | Result |
| --- | --- |
| `sh compiler/rust/build.sh` | Passed |
| `make check` | Passed |
| `make test-rust MAYC=compiler/mayc/mayc_new` | 60 passed; the four pre-existing historical-parser tests remain ignored |
| `make test-compiler MAYC=compiler/mayc/mayc_new` | 120 passed, 0 failed (adds `float_literals.py` and `float_math.py`) |
| `make test-compliance MAYC=compiler/mayc/mayc_new` | 69 passed, 0 failed, 0 observations |
| `make test-docs MAYC=compiler/mayc/mayc_new` | 25 runnable strict examples passed |
| `make test-llvm MAYC=compiler/mayc/mayc_new` | Passed |
| `make test-bootstrap MAYC=compiler/mayc/mayc_new` | Passed: source-only chain and byte-identical stages 2/3 |
| `make test-tools MAYC=compiler/mayc/mayc_new` | Passed |
| `python3 compiler/mayc/tests/raw_codegen.py --compiler compiler/mayc/mayc_new` | Passed |
| `backends.py`, `core_runtime.py`, `portable_values.py`, `float_math.py` with `--require-emulation` | Passed on all five targets |

`float_math.py` checks IEEE special cases, Int arguments and signed zeros on the
full, LLVM and core runtimes, holds 784 seeded portable results within one ulp
of glibc, and requires bit-identical results on every core target.
`float_literals.py` compares 500 literals with Python's correctly rounded
parser on the full, core and LLVM backends. Real Windows/macOS hosts and the
four-generation `compiler/mayc/tests/run.sh` were not run.

### First session

The compiler was rebuilt from source after compiler edits. Final implementation
checks ran in an isolated worktree containing this series. Set `MAYC` explicitly
because a shell may otherwise select an older installed compiler.

| Command | Result |
| --- | --- |
| `sh compiler/rust/build.sh` | Passed: Rust/C bootstrap and native compiler build |
| `make check` | Passed: links, syntax, native mirror and generated references |
| `make test-rust MAYC=compiler/mayc/mayc_new` | Passed; four pre-existing historical-parser integration tests remain ignored |
| `make test-compiler MAYC=compiler/mayc/mayc_new` | 118 passed, 0 failed |
| `make test-compliance MAYC=compiler/mayc/mayc_new` | 69 passed, 0 failed, 0 observations |
| `make test-docs MAYC=compiler/mayc/mayc_new` | 25 runnable strict examples passed |
| `make test-llvm MAYC=compiler/mayc/mayc_new` | Passed: behavior, externs, fibers, traces and reachability |
| `make test-bootstrap MAYC=compiler/mayc/mayc_new` | Passed: source-only chain and byte-identical stages 2/3 |
| `python3 compiler/mayc/tests/raw_codegen.py --compiler compiler/mayc/mayc_new` | Passed |
| `python3 compiler/mayc/tests/backends.py --compiler compiler/mayc/mayc_new --require-emulation` | Passed |
| `python3 compiler/mayc/tests/core_runtime.py --compiler compiler/mayc/mayc_new --require-emulation` | Passed |
| `python3 compiler/mayc/tests/portable_values.py --compiler compiler/mayc/mayc_new --require-emulation` | Passed on all five targets, including relocated Mach-O cases and float bit comparisons |
| `python3 compiler/mayc/tests/native_targets.py --emit --compiler compiler/mayc/mayc_new --directory /tmp/maylang-float-native-targets` | Emitted 52 fixtures |
| `python3 compiler/mayc/tests/native_targets.py --run x86_64-linux --directory /tmp/maylang-float-native-targets` | All 17 Linux control fixtures passed with the real loader |

Unicorn was supplied from temporary dependencies outside the repository; no
binaries, dependency packages or generated test reports are committed. Actual
Windows/macOS execution was not run locally because those hosts were unavailable.
The four-generation `compiler/mayc/tests/run.sh` was not run; the source-only
bootstrap convergence check above was run instead. The language-server suite
passed at `b0d7f41`, before the final portable-float milestone.

## Implementation commits

- `c3ae925` — isolate suspended fiber handlers and caught errors.
- `7c46124` — accept unsigned/void strict extern signatures.
- `4ceaa57` — implement LLVM typed externs and cooperative fibers.
- `3083d21` — document LLVM support.
- `af35008` — implement portable maps, records and enum matching.
- `7ab0f81` — implement portable closures, callbacks and stack arguments.
- `8da0fd4` — implement portable fault recovery and source traces.
- `5c93cac` — implement portable cooperative fibers.
- `b0d7f41` — correct scheduler result types.
- `12f31fe` — implement portable floating-point values and regression coverage.
