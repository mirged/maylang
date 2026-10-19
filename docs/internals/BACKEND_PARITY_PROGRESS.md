# Backend parity progress and handoff

This branch advances backend support; **full language and standard-library
parity is not complete**. The requested scope includes both language features
and all standard-library OS APIs, including files, processes and networking.

Branch: `feat/backend-parity-progress`.
Starting revision: `beb593cdcffb2ff4c30db060686c3eb312807d62`.
Latest implementation milestone: `12f31fe`.

The branch preserves the original checkout's base. Three subsequent changes on
`origin/main` concerning x86 code alignment and its measurements have not been
merged into this series. Integrate current main and rerun checks before merging.
No version bump or performance claim is part of this work.

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

## Current boundaries

| Area | Direct full Linux x86-64 | LLVM Linux x86-64 | Portable native runtime |
| --- | --- | --- | --- |
| Collections, closures and pattern matching | Supported | Supported | Supported |
| Recoverable faults, traces and cooperative fibers | Supported | Supported | Supported |
| Basic Float/Float32 operations | Supported | Supported | Supported |
| Transcendental functions and floating powers | Supported | Supported | Still missing |
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
2. **Complete numeric support.** Implement `sin`, `cos`, `tan`, `ln`, `log2`,
   `log10`, `exp` and floating-point powers on portable targets. Core floating
   powers currently raise a catchable type fault; unsupported transcendental
   builtins are diagnosed during compilation. Resolve scientific formatting
   differences and test extreme/subnormal/nonfinite values across backends.
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
