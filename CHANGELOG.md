# Unreleased

## Documentation

- Stop describing the closed sustained-allocation report
  ([#2](https://github.com/mirged/maylang/issues/2)) as a known crash. It does
  not reproduce on the fat runtime: 20 `gc_stress.py` seeds × 400 steps, the
  GC and limits suites, and five repeated runs of the trees, hashmap, strings,
  n-body and sieve benchmarks and of mayc compiling itself all pass with
  identical output. The 0.15.0 remaining limits are corrected.

# Maylang 0.15.0 — Fern

Released 2026-11-01 UTC. Maylang narrows to one host and target, Linux
x86-64, and its values become fat: 16 bytes with a separate type word, so
`Int` is a full signed 64-bit integer and Floats are unboxed. Generated code
is much faster. Maps hash every key type, struct fields are cached per site,
hot locals and temporaries stay in registers (Floats in XMM registers), and
type proofs remove checks. Field caching alone makes n-body 11× faster,
and mayc compiles itself in under half the time it took in 0.14 (median
6.3 s instead of 15.4 s over five runs on the same machine). Bitwise
operators arrive, and the UI adapter and the VS Code extension get
sanitizer and extension-host tests.

## Behavior changes

- Only `--target x86_64-linux` is supported. The other targets, the core
  runtime, NodeOS, MayOS, the browser and `stdlib/ml` are frozen in
  `frozen/`, and selecting them fails with an explanation. The `clang-llvm`
  target and `--emit-llvm` are removed.
- `Int` reaches ±2^63; overflow faults only beyond that. `addr` of a Float
  is a `type` fault, a `List<Any>` uses 16 bytes per element, and `--values`
  fails with an explanation.
- `&`, `|`, `^`, `~`, `<<` and `>>` work on 64-bit integers; a shift result
  that does not fit raises `integer overflow` instead of wrapping.
- A function defined twice across the runtime and library sidecars is a
  compile error. The prelude's `repeat` and `substring` are removed;
  `native.may` provides them, as before.
- The VS Code extension restarts the language server when
  `maylang.serverPath` or `maylang.strict` changes.

## Remaining limits

- The compiler host and the only target are Linux x86-64; release bundles are
  Linux x86-64 only.
- The collector is conservative: it scans stacks, registers and Int payloads
  in heap values as possible pointers, so unrelated integers can keep memory
  alive. (The old sustained-allocation crash report,
  [#2](https://github.com/mirged/maylang/issues/2), does not reproduce; the
  0.15.0 notes originally listed it here by mistake.)
- Dynamic code is still well behind compiled languages; records are maps
  with per-site caches, and the remaining work is tracked in
  [#101](https://github.com/mirged/maylang/issues/101).
- The compiler frontend uses mutable global state and is not re-entrant
  ([#49](https://github.com/mirged/maylang/issues/49)).

## Scope

- **Breaking:** freeze the platform experiments and the experimental ML
  library while Maylang focuses on Linux x86-64
  ([plan](docs/design/LINUX_X86_64_FOCUS.md),
  [#102](https://github.com/mirged/maylang/issues/102)). `platform/maybrowser`,
  `platform/mayos`, `stdlib/ml` (`import "ml/..."` no longer resolves), its
  reference pages, `examples/ml_xor.may` and the artificial ecosystem
  simulation, which used `stdlib/ml`, move to `frozen/`, where they are kept
  but not built, tested or maintained. `make test-browser`, the doctor's
  `browser` profile and the `maybrowser.yml` workflow are removed.
- **Breaking:** mayc targets only `x86_64-linux`, with the full runtime and
  `--raw` (`--runtime none`). `--target x86_64-nodeos`, `arm64-linux`,
  `riscv64-linux`, `arm64-macos` and `x86_64-windows` and `--runtime core`
  fail with `target ... is frozen` / `runtime core is frozen`. The ARM64 and
  RISC-V backends and their RAW lowering (`raw.may`, `raw_fat.may`,
  `raw_float.may`), the Mach-O, PE and NXF formats, the NodeOS syscall gate
  and personality (`runtime/nodeos.may`), the core runtime
  (`runtime/fat_core.may`, `runtime/fat_corelib.may`, the `core` API page),
  their harnesses (`core_runtime.py`, `portable_values.py`,
  `native_targets.py`, `nodeos.py`) and target documentation move to
  `frozen/`. The remaining harnesses test x86-64 Linux only. Release bundles
  no longer contain `runtime/fat_core.may`. The compiler is 2.67 MB instead
  of 3.19 MB, and its x86-64 Linux output is byte-identical
  ([#102](https://github.com/mirged/maylang/issues/102)).
- Stop running cross-target emulation (`core-emulation`) and the Windows and
  macOS real-loader workflow (`native-targets.yml`) in CI, and freeze the
  WSL launcher `dist/install.ps1`; releases no longer publish it. Release
  bundles describe themselves as Linux x86-64 only
  ([#102](https://github.com/mirged/maylang/issues/102)).

## Compiler

- Reject a second definition of a function in the runtime and library
  sidecars (`runtime/fat.may`, `runtime/fat_linux.may`, `prelude.may`,
  `native.may`, `runtime/math.may`) with an error naming both locations.
  The later definition used to replace the earlier one silently for every
  caller. User code may still shadow library functions. The prelude's
  `repeat` and `substring`, which `native.may` had always replaced, are
  removed ([#114](https://github.com/mirged/maylang/issues/114)).
- Native-word functions call `extern` functions with `Int`, `UInt`, `Ptr`
  and `Bool` signatures directly again, passing machine words to C instead
  of going through the extern's fat entry, as `docs/guide/STRICT.md`
  describes. UInt range faults keep the fat entry's messages
  ([#94](https://github.com/mirged/maylang/issues/94)).
- **Breaking:** remove the experimental `clang-llvm` target and
  `--emit-llvm`. mayc is its own toolchain and writes every executable
  itself; both now fail with an explanation. `make test-llvm`, the doctor's
  `llvm` profile, the harnesses' `--llvm` options and the runtimes' LLVM
  accommodations (a libc-supplied environment pointer and 256-byte handler
  slots) are gone, and the compiler's code is 290 KB smaller.
- **Breaking:** compile every program with a runtime using fat values, 16
  bytes with a separate type word, instead of 3-bit tagged words, on every
  target (design: [docs/design/FAT_VALUES.md](docs/design/FAT_VALUES.md)).
  `Int` is signed 64-bit: literals and arithmetic reach ±2^63 and
  overflow faults only beyond that, values between 2^60 and 2^63 no longer
  raise `integer overflow`, native-word results and C results cross into
  dynamic code unchanged, Floats are unboxed (`addr` of a Float is now a
  `type` fault) and a `List<Any>` uses 16 bytes per element. The compiler
  itself runs on fat values and reaches the bootstrap fixpoint. The tagged
  runtimes (`runtime.may`, `runtime/core.may`, `runtime/corelib.may`) and
  their code generation are gone, the compiler is 3.19 MB, and `--values`
  now fails with an explanation (`MAYC_VALUES` is ignored). A copied
  compiler needs `native.may`, `prelude.may` and `runtime/` beside it
  ([#92](https://github.com/mirged/maylang/issues/92)).
- **Breaking:** the core runtime (the default on arm64-linux, riscv64-linux,
  arm64-macos and x86_64-windows, and `--runtime core`) shares the full
  runtime's `runtime/fat.may`, `prelude.may` and `native.may`, so core
  programs print what full-runtime programs print: lists and maps compare
  by identity rather than structurally, uncaught faults print
  `kind: message`, and library functions such as `slice` follow
  `native.may`. ARM64 and RISC-V compile dynamic code with the new
  `backend/raw_fat.may`, and their emitters accept frames beyond 4 KiB
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Fix the fat collector freeing a block whose only reference was a `Ptr`
  (from `cstr` or `addr`) stored in a list, map or other heap value: Int
  payloads in heap values are now checked conservatively, as stack words
  are ([#92](https://github.com/mirged/maylang/issues/92)).
- Fix ELF symbols of fat functions, and of native-word functions called only
  from native code, which all pointed at `_start`
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Run Int `/` and `%`, closure calls and their type checks inline in fat
  code, and share one slow-path stub per operator: Int loops run 3.7x and
  closure calls 4.7x faster than before, closures now 2.2x faster than
  tagged values, and the compiler's code shrinks to 3.65 MB
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Run fat Float `+ - * /` and comparisons in shared SSE stubs instead of
  the runtime: a Float loop runs 5.5x faster (405 ms against 2.2 s; tagged
  values take 8.0 s) for 70 KB more compiler code
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Count `for` loops over an Int-bounded range `a..b` or `a..=b` instead of
  building the list first: a 20M-iteration loop no longer runs out of
  memory with fat values (169 ms) and runs 9.7x faster with tagged values
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Make `index_of`, `contains`, `replace`, `to_lower` and `to_upper` linear:
  they scanned or rebuilt strings one code point at a time from the start,
  so a 17 KB string took seconds. `stress.may` runs 10x faster.
- Use fat values with the full runtime on x86_64-nodeos as well; `exec` and
  `system` start programs through the personality's spawn extension there.
  Fat code is about 20% smaller and `stress.may` runs 1.6x faster: short-lived
  temporaries share frame slots reached with 8-bit displacements, and a value
  consumed by the next instruction is no longer stored and reloaded
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Add integer bitwise operators `&`, `|`, `^`, `~`, `<<` and `>>` with
  Rust-style precedence and signed 61-bit behavior. Replace the NodeOS NXF
  CRC-32 lookup tables with a portable bitwise implementation
  ([#91](https://github.com/mirged/maylang/issues/91)).
- Preserve native 64-bit values, including bit 63, in raw-mode bitwise
  operations as the first step toward the native-word ABI
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Compile functions whose parameters, result, locals and operations are all
  `Int` with untagged 64-bit machine words in the full and core runtimes on
  every target. Arithmetic faults on 64-bit overflow, division by zero and
  shift counts outside 0 through 63; results are retagged, with an overflow fault,
  when they return to tagged code. Calls between such functions pass machine
  words directly ([#92](https://github.com/mirged/maylang/issues/92)).
- Accept `Ptr` and `Bool` parameters, results and locals, `true`/`false`, and
  `load8`..`load64`/`store8`..`store64`, in native-word functions, so memory reads keep bit 63
  instead of wrapping to the tagged range
  ([#92](https://github.com/mirged/maylang/issues/92)).
- **Breaking:** evaluate `Int`/`Bool` expressions that contain a bitwise
  operator with 64-bit words in the full and core runtimes, by outlining them
  into native-word functions. `(1 << 63) & (1 << 63) != 0` is now `true`, shift
  counts up to 63 are accepted, and a result that does not fit the signed
  61-bit range raises `integer overflow` instead of wrapping (`6 << 59` and
  `1 << 60` used to wrap silently)
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Keep tagged evaluation for a bitwise expression that both calls a function
  and reads a global, so a global assigned by the call is read afterwards.
  Outlining previously read it first
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Raise an `arithmetic` fault (`integer overflow`) when tagged `load64` reads
  a word outside the signed 61-bit range, on every target. It previously
  dropped the top three bits silently. Raw code and native-word functions
  still return the full word ([#92](https://github.com/mirged/maylang/issues/92)).
- Allow `syscall` in native-word functions on the full runtime for Linux and
  NodeOS targets, passing and returning machine words without tagging
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Let native-word functions read and assign `Int`, `Ptr` and `Bool` globals,
  converting at each access; a value outside the 61-bit range faults on
  assignment and leaves the global unchanged
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Let native-word functions call any top-level function whose parameters
  and result are `Int`, `Ptr` or `Bool`, even one that stays tagged. The call
  goes through a word adapter that tags the arguments, raising
  `integer overflow` before the callee runs if one does not fit 61 bits, and
  untags the result. A single such call previously kept the whole caller
  tagged ([#92](https://github.com/mirged/maylang/issues/92)).
- Call `extern` functions whose parameters and result are `Int`, `UInt`,
  `Ptr` or `Bool` (or a `Void` result) from native-word functions with machine
  words on x86-64 Linux and `clang-llvm`, without the tagged FFI conversions.
  `Int` and `Ptr` results keep all 64 bits; UInt arguments and results are
  still range-checked ([#92](https://github.com/mirged/maylang/issues/92)).
- Lower `for` loops over `a..b` and `a..=b` in raw code and native-word
  functions as counted loops, with the bounds evaluated once and no range
  list. Raw programs previously rejected ranges
  ([#92](https://github.com/mirged/maylang/issues/92)).
- Reject `addr`, `cstr` and `len` on a non-literal string in x86-64 raw mode,
  as the other raw backends do; they previously compiled to a read of
  unrelated memory.
- Fault on tagged shift counts outside 0 through 60 on the ARM64 and RISC-V
  core targets, as x86-64 already did; they previously shifted silently
  ([#91](https://github.com/mirged/maylang/issues/91)).
- Support bitwise operators on the experimental `clang-llvm` target, which
  previously rejected them ([#91](https://github.com/mirged/maylang/issues/91)).
- Hash `Map` keys of every type, not only `Str`
  ([#97](https://github.com/mirged/maylang/issues/97)). `Int`, `Float`,
  `Bool`, `nil` and reference keys used a linear scan, so building a map
  was O(n²): 500 000 `Int` keys now take 0.34 s on a loaded machine
  instead of not finishing in 120 s. String hashing drops its per-byte division, and the
  index table uses CPython-style perturbed probing. Equality and insertion
  order are unchanged
  ([report](compiler/mayc/tests/backend/map-hashing.md)).
- Cache struct and record field access per site
  ([#98](https://github.com/mirged/maylang/issues/98)). Each `x.f` checks
  inline whether the entry where it last found `f` still holds the
  program's shared `"f"` key and loads it directly, for typed and `Any`
  receivers alike, instead of a string-keyed map lookup. Struct constructors
  and map literals allocate their entries at the final size. A field read
  drops from about 65 ns to 2 ns; n-body runs 11× faster, binary trees 5×,
  and mayc compiles itself in half the time. Records are still maps, so
  printing, `keys`, equality and dynamic access are unchanged
  ([report](compiler/mayc/tests/backend/struct-fields.md)).
- Speed up lists, strings and `join`
  ([#99](https://github.com/mirged/maylang/issues/99)). `join` measures the
  total length and copies each part once instead of concatenating pairwise;
  a list buffer at the top of the heap grows in place; `xs[i] = v` on a list
  is stored inline; and raw runtime functions that make no calls are
  compiled with the RAW optimizations in dynamic programs too. The issue's
  sieve falls from 1 085 ms and 420 MiB to 613 ms and 160 MiB, the strings
  workload from 277 ms and 262 MiB to 90 ms and 66 MiB, and mayc compiles
  itself 13% faster ([report](compiler/mayc/tests/backend/lists-strings.md)).
- Keep fat temporaries and hot locals in registers
  ([#96](https://github.com/mirged/maylang/issues/96)). Constants and
  unchanged variable reads load straight into the registers that use them,
  comparisons that steer a branch jump directly, Int constants become
  immediates (powers of two divide by shifting), Float operations on
  statically `Float` operands run inline, slow paths move out of line, and
  up to two loop-hot locals per function live in callee-saved register
  pairs, which the collector now marks. Int and Float loops run about 3×
  faster, n-body and list loops 2×, closure calls 1.5×, and the compiler
  binary shrinks from 3.02 MB to 2.42 MB
  ([report](compiler/mayc/tests/backend/fat-registers.md)).
- Prove value types in fat code and use them to drop type checks and halve
  register homes ([#101](https://github.com/mirged/maylang/issues/101)).
  A forward analysis proves a type only from operations whose result type
  the runtime guarantees (literals, comparisons, Int and Float arithmetic
  on proven operands, `len`, `str`, `to_float`) and from variables whose
  every binding is proven, never from annotations alone. Proven operands
  skip their type-word checks, and proven locals keep only their payload
  in one register, so up to five hot locals per function stay in RBX and
  R12–R15. Int loops run about 1.15× faster; other workloads are unchanged
  ([report](compiler/mayc/tests/backend/proven-types.md)).
- Keep proven Floats in XMM registers, and specialize functions for their
  annotated parameter types ([#101](https://github.com/mirged/maylang/issues/101)).
  Float locals live in XMM8–XMM15, spilled around calls, and Float
  temporaries in XMM2–XMM7, so Float arithmetic and comparisons no longer
  move every operand through general registers and frame slots. A function
  with `Int`, `Float` or `Bool` parameters and a loop can get a second body
  that assumes those types; its entry checks the argument type words and
  runs the generic body when any differs, so calls through `Any` behave as
  before. Mandelbrot in a function runs 2.45× faster; other workloads are
  unchanged, and the compiler grows by 1%
  ([report](compiler/mayc/tests/backend/float-registers.md)).

## UI

- A truncated or corrupt `MAYUI_FONT` no longer makes the native adapter read
  out of bounds: the font header and table directory are checked before
  stb_truetype sees them, and a bad file falls back to the default font.
  `ui` line and bitmap coordinates near the `Int` limits no longer overflow
  in C. `make test-sanitize` and a CI job run the adapter on malformed
  geometry, bitmaps, UTF-8 and fonts under ASan/UBSan
  ([#47](https://github.com/mirged/maylang/issues/47)).

## Editor

- The VS Code extension restarts the language server when
  `maylang.serverPath` or `maylang.strict` changes, instead of keeping the
  settings it read at activation. A `serverPath` that does not exist now shows
  only the warning, without also trying to start the server. Restarts are
  serialized, and deactivation shuts the server down cleanly. Extension-host
  tests on VS Code 1.82.0 (`make test-editor`, plus a separate CI job) cover
  discovery, missing and failing servers, restarts and deactivation
  ([#52](https://github.com/mirged/maylang/issues/52)).

## MayOS

- Pass native words through `__ccall6` without tag compensation, and always
  build the kernel raw with the checkout compiler. A `MAYC` in the environment
  previously produced a full-runtime kernel that halted with a boot fault
  ([#92](https://github.com/mirged/maylang/issues/92)).

## Browser

- Stop HTTP(S) responses above 16 MiB of decoded data, including chunked and
  compressed transfers. Reject images above 16 MiB encoded, 8192 pixels per
  axis, or 16,777,216 decoded pixels before decoding, and report resource
  limit errors while allowing later navigation
  ([#44](https://github.com/mirged/maylang/issues/44)).
- Guard empty reads in the bundled image decoder so malformed PNG data
  chunks do not pass a null destination to `memcpy`.
- Compile the native adapter against the official libcurl headers, link with
  `-lcurl`, and check for the development files in the browser prerequisite
  profile ([#46](https://github.com/mirged/maylang/issues/46)).

## Targets

- On NodeOS, programs read the environment their launcher passes and start in
  its `PWD`, so `cd /src; mayc main.may` at the NodeOS shell compiles
  `/src/main.may`, and `env("NAME")` sees exported shell variables. `exec`
  and `system` pass the environment on to the programs they start.

# Maylang 0.14.0 — Elm

Released 2026-10-20 UTC. Maylang targets NodeOS, a capability microkernel,
with every runtime, and the compiler runs there: it rebuilds itself on NodeOS
into a compiler byte-identical to the one cross-built on Linux. The full
runtime's heap can now outgrow 256 MiB, and Float rounding and conversion
are stricter.

## Behavior changes

- `floor`, `ceil` and `round` return Floats, and `int`/`trunc` fault on
  values outside the Int range (details under Runtime).
- The full runtime reserves 1 GiB of address space for its heap (committed on
  demand). Collection still starts at 256 MiB; a program whose live data
  exceeds that now keeps running instead of exiting with `out of memory`.

## Remaining limits

- On NodeOS there are no C externs (no dynamic loader), no sockets (no network
  service) and no wall clock; children do not inherit the working directory
  or environment, and created file names must fit 8.3.
- Compiler hosts are Linux x86-64 and NodeOS; release bundles are Linux
  x86-64 only.

## Targets

- Add `--target x86_64-nodeos` for [NodeOS](https://github.com/mirged/nodeos),
  with the full, core and raw runtimes. Images are NXF, written directly with
  the CRC-32 NodeOS's loader checks. Each `syscall` site calls a gate into
  `runtime/nodeos.may`, an in-process personality that answers the Linux calls
  Maylang uses with NodeOS syscalls and IPC: console and file I/O, directories,
  memory, time, `exec`/`system`/`wait` through a spawn extension, and
  `/proc/self` arguments. C externs and sockets are unsupported there.
  See [NodeOS target](frozen/docs/internals/NODEOS.md).
- The compiler runs on NodeOS. A `mayc` built for NodeOS compiles programs
  there and defaults to `x86_64-nodeos`; it rebuilds itself on NodeOS into a
  compiler byte-identical to the one cross-built on Linux. Without `-o`, NodeOS
  output is named `<source>.nxf`. `compiler/mayc/tests/nodeos.py` checks the
  images; NodeOS's `make test-maylang` runs them.

## Compiler

- Bound the compiler's source arena: a failed mapping or an exhausted arena is
  reported as an error instead of writing past the mapping (a program importing
  300 small modules crashed with a segmentation fault). `MAYC_ARENA_BYTES`
  selects the arena size ([#39](https://github.com/mirged/maylang/issues/39)).
- Reserve only the bytes actually read for each source file instead of 1 MiB
  per module, so programs with hundreds of imported modules compile in the
  default arena.
- Enforce the 4 MiB bound on the expanded import closure. Several modules that
  were each under the 1 MiB file limit could overflow the expansion buffer; the
  compiler now stops with the offending line and the chain of imports that
  reached it ([#38](https://github.com/mirged/maylang/issues/38)).

## Runtime

- Let the full runtime's heap outgrow 256 MiB instead of failing with `out of
  memory`: collection still starts at 256 MiB, and when a collection cannot
  satisfy an allocation the threshold grows within a 1 GiB on-demand
  reservation. The self-hosted compiler sat at the old limit while compiling
  itself. `exec` and `system` fall back to a spawn extension where `fork`
  returns `ENOSYS`.
- Fault with a catchable `arithmetic` error ("Float outside Int range") when
  `int` or `trunc` would produce an Int outside ±2^60 or is given NaN or an
  infinity. These conversions previously returned 0 or a wrapped value
  silently. Full, core and LLVM runtimes agree on every target
  ([#89](https://github.com/mirged/maylang/issues/89)).
- **Behavior change:** `floor`, `ceil` and `round` return Floats, as their
  strict types always declared (`floor(2.5)` prints `2.0`, `floor(1.0e300)` is
  `1e300`, and NaN, infinities and `-0.0` pass through). Use `int(floor(x))`
  where an Int is needed; `random_int`, `stats_quantile` and the ML train/test
  split do so. `round` no longer rounds `0.49999999999999994` or odd values
  above 2^52 incorrectly, and `format_bytes` keeps its decimal (`1.5 KiB`
  instead of `1 KiB`) ([#89](https://github.com/mirged/maylang/issues/89)).

## Behavior contracts

- Accept `for` loops over literal `Int` ranges (`a..b`, `a..=b`) in functions
  with behavior contracts. Range bounds are effect-checked, the loop variable is
  an immutable body-scoped `Int`, and `break`/`continue` work as in `while`.
  Loops over collections, strings or stored ranges remain unknown behavior.

## Tools

- maylsp no longer reports every error twice in editors that pull diagnostics
  (VS Code): a client that announces pull support now gets diagnostics only
  from `textDocument/diagnostic`, and others still get them pushed.
- `scripts/install_nightly.sh` builds the checkout and installs it as a
  nightly generation of `~/.maylang`.
- Pass all four `wait4` arguments in the installer and `may`, which could
  fail with `Cannot wait for compiler verification` when the unused
  `rusage` register held a stale value.
- `mayfmt --help` and `mayfmt -h` print usage and exit 0 without reading or
  writing files, and unknown options are rejected before any file is
  formatted ([#64](https://github.com/mirged/maylang/issues/64)).
- `scripts/doctor.py` compiles and links a test program with the selected
  `CC` instead of only finding it on `PATH`, so a broken compiler is reported
  before the bootstrap fails ([#66](https://github.com/mirged/maylang/issues/66)).
- `may` skips directories and non-executable files while searching `PATH` for
  native recipe and task commands, and reports explicit paths that are missing,
  not regular files or not executable separately from PATH exhaustion
  ([#41](https://github.com/mirged/maylang/issues/41)).
- `may dev` no longer hangs when replacing an application that ignores
  SIGTERM: the process group gets a two-second grace period, then SIGKILL
  ([#42](https://github.com/mirged/maylang/issues/42)).
- `may` targets accept an `env` list of environment variables whose values
  join the cache identity, so a native recipe that reads `CFLAGS` rebuilds when
  it changes. Values are hashed, never stored in artifact metadata
  ([#40](https://github.com/mirged/maylang/issues/40)).

## Distribution

- `dist/install.sh` rejects archives containing symbolic or hard links,
  special files, duplicate entries or more than one bundle root before
  extracting, so a supplied archive can no longer make the installer change
  permissions outside the bundle ([#43](https://github.com/mirged/maylang/issues/43)).

# Maylang 0.13.103 — Dahlia

Released 2026-10-19 UTC. The portable native runtime gains collections,
closures, recoverable faults, fibers and floating point on every direct target;
float display, parsing and trigonometry now agree bit for bit across runtimes;
and RAW x86-64 code is faster and placement-stable.

## Behavior changes

- Reject comparisons between values of different types. Strict checking now
  rejects `Int` vs `Float` comparisons; on dynamic values `==` across types is
  `false`, `!=` is `true` (so `1.0 != 1` is now `true`), and `<`, `<=`, `>`
  and `>=` raise a catchable `type` fault. `match` patterns of another type
  still simply fail to match. `Any`-typed stdlib numeric code now normalizes
  with `to_float`.
- Display floats with the shortest digits that round-trip (`0.1 + 0.2` prints
  `0.30000000000000004`, `-0.0` keeps its sign, nested values no longer
  truncate to six decimals) and parse `float(text)` and JSON numbers with
  correct rounding, on every runtime.
- Support `sin`, `cos`, `tan`, `ln`, `log2`, `log10`, `exp` and floating
  `pow`/`**` in the portable runtime on every native target. The binary64-only
  implementation is bit-identical across targets, within one ulp of the host
  libm, and reduces trigonometric arguments of any magnitude exactly. The `pow`
  builtin now returns a Float in the core runtime, as documented, and negative
  integer exponents of `**` produce a Float instead of a fault.

## Floating point

- Share exact `sin`, `cos` and `tan` between the full, LLVM and core runtimes;
  the full runtime's x87 versions were inaccurate near multiples of pi and
  returned arguments above 2^63 unchanged. The new `runtime/math.may` sidecar
  holds this shared code, and core releases the temporaries of pure math,
  parsing and formatting calls so long loops no longer exhaust its heap.
- Convert float literals with exact big-integer arithmetic so they are
  correctly rounded on every backend; decimal scaling misrounded most
  17-digit literals by one or two ulps.
- Follow C99 `pow` special cases (zeros, infinities, NaN, negative bases with
  integer exponents) and return `inf`/`0.0` from `exp(±inf)` in the full
  runtime. Accept Int arguments to `sqrt`, `floor`, `ceil`, `sin`, `exp`, `pow`
  and related builtins on x86-64 instead of crashing.
- Stop crashing when a Float is compared with `nil` or another non-number
  using `!=` or `<`, and when the full runtime displays the smallest
  subnormals.
- Support boxed Float/Float32 arithmetic, conversions, comparisons, square roots
  and rounding on every native target. Format nonfinite scalar floats as
  `nan`, `inf` or `-inf` in both runtimes. Cross-platform FFI remains
  unsupported in the portable runtime.

## Portable native targets

- Support cooperative fibers on every native target with isolated handlers and
  traces; return `nil` from `yield()` consistently with its declared type.
- Support recoverable faults and debug traces on every native target; preserve
  callee-saved registers during unwinding and check the 64-handler limit.
- Support closures, shared captures, callbacks, overloaded struct operators and
  stack arguments in the portable runtime; fix recursive local closure binding.
- Support maps, records, structs and enums in the core runtime on every native
  target; preserve exclusive range endpoints on ARM64 and RISC-V.
- Preserve each fiber's caught error and exception handlers across yields, and
  accept the C binding types `UInt` and `Void` under strict checking.

## LLVM backend

- Support typed extern calls and cooperative fibers in the LLVM backend,
  including C stack arguments, function values and isolated suspended handlers.

## RAW code generation

- Lower signed power-of-two division and remainder up to 2^59 with shifts
  instead of `idiv` (#84).
- Branch directly on RAW `and`/`or` conditions instead of materializing a
  Boolean, keeping short-circuit order, effects and faults (#85).
- Keep parameters and loop-weighted locals in dedicated registers, including
  bodies with direct user calls and syscalls (#86), and hold values that no call
  clobbers in volatile registers so fewer callee-saved registers are saved;
  drop unreachable and fallthrough jumps (#87). The extended suite is 33%
  faster than 0.13.102 and runs at 1.32× GCC's time
  ([report](compiler/mayc/tests/backend/raw-call-gaps.md)).
- Align RAW x86-64 function bodies and loop heads to 16 bytes with NOP
  padding, so unrelated code no longer moves hot loops (#83). Collatz's
  spread across 16 code placements falls from 5.5% to 2.3% of cycles. Suite
  medians are unchanged and code grows about 5%. `--no-code-align` restores
  the previous layout. Add `raw_layout.py` and a branch-predictability suite
  ([report](compiler/mayc/tests/backend/raw-code-alignment.md)).
- Add an eleven-workload extended RAW benchmark suite
  ([report](compiler/mayc/tests/backend/raw-extended-suite.md)).

## Remaining limits

- File, process and network libraries and typed FFI still need the full
  x86-64 Linux runtime; the portable runtime keeps allocations until exit
  (256 MiB cap). See the
  [backend parity handoff](frozen/docs/internals/BACKEND_PARITY_PROGRESS.md).
- Full and LLVM builds keep x87/libm logarithms, `exp` and `pow`, which can
  differ from the portable runtime in the last place; `nan == nan` is `true`
  on every backend.

# Maylang 0.13.102 — Dahlia

Released 2026-10-17 UTC. Branch-free RAW scalar diamonds, fused memory
addressing with register-resident memory loops, and a repository layout
organized by role.

## Compiler and RAW code generation

- Lower short scalar if/else diamonds over dedicated local registers with
  conditional moves instead of branches. Both arms are speculated only when
  they are pure, nontrapping and within a bounded cost; predicates over
  induction locals (written only as `v = literal` or `v = v ± literal`) keep
  their predictable branches
  ([report](compiler/mayc/tests/backend/raw-if-conversion.md), #78).
- Fuse `load8`–`load64`/`store8`–`store64` pointer arithmetic built from
  single-use additions, scales of 1, 2, 4 or 8, imm32 literals and local
  snapshots into one `[base + index*scale + displacement]` operand. Memory
  accesses keep their order, widths and faults
  ([report](compiler/mayc/tests/backend/raw-addressing.md), #79).
- Keep locals in dedicated registers in functions whose only non-scalar
  operations are unshadowed RAW loads and stores, and allocate their
  temporaries in volatile r8–r10. `__sp`, `syscall` and other calls still
  exclude promotion.

## Recorded performance

Committed 100-run interleaved measurements on an Intel i5-13500H, pinned
performance CPU 2, GCC 14.2, against the 0.13.101 compiler `c3d3ea8`. All six
checksums match in every sample; these are saved pre-release measurements.

| Measurement | 0.13.101 | 0.13.102 |
| --- | ---: | ---: |
| Six-kernel end-to-end median | 21.693 ms | 15.991 ms |
| GCC `-O3 -march=native`, same trial | 18.042 ms | 18.042 ms |

Median runtime falls **26.3%**; RAW output now runs at **0.89×** GCC's time
on this suite. Branch-free diamonds alone reach 16.742 ms; address fusion and
memory-loop registers cut the automaton kernel 38.6% and the histogram 19.9%.
Collatz loop timing still varies by up to 12% with code placement alone;
function and loop-head alignment is tracked in
[#83](https://github.com/mirged/maylang/issues/83). No machine-specific speed
threshold is added to CI.

## Repository layout

- Reorganize the repository by role: `compiler/` (mayc, Rust bootstrap),
  `tools/`, `platform/`, `dist/`, `tests/`, a single `examples/` tree and
  grouped `docs/` with the generated reference under `docs/reference/`.
  **Behavior change:** the `toolchain/` compatibility entry points are
  removed, and release bundles ship sample apps under `examples/apps/`. See
  the [path migration table](docs/REPOSITORY.md#path-migration).

## Verification

- Decode 4,698 addressing encodings with objdump as an independent oracle,
  check 120 generated memory loops against a byte-array model, and check 480
  calls of 160 generated diamond functions against an exact 64-bit Python
  oracle, including `INT64_MIN`/`INT64_MAX` inputs and untaken traps that must
  keep their branches. IR tests cover absorbed instructions, snapshots, CFG
  boundaries and shadowed intrinsics.
- The source passed **115 compiler verifier checks**, compliance cases, Rust
  workspace tests, source-bootstrap convergence, LLVM and native macOS/Windows
  loader checks in CI.
- Synchronize compiler, release metadata, README and editor extension
  versions to 0.13.102.

Maylang remains experimental; platform support and runtime limits are
unchanged from 0.13.101.

[Full Git changelog: v0.13.101...v0.13.102](https://github.com/mirged/maylang/compare/v0.13.101...v0.13.102).

---

# Maylang 0.13.101 — Dahlia

Released 2026-10-17 UTC. This release includes all changes since 0.13.0:
faster Linux x86-64 RAW code generation, native GPU UI rendering, the May NES
example application, and fixes for compiler-build heap fragmentation.

## Compiler and RAW code generation

- Use allocated registers and spill homes directly for binary operands and
  store values. Forward a single-use accumulator result into its adjacent
  consumer, and borrow adjacent local reads as memory or register operands
  when snapshots and evaluation order permit it.
- Fuse exclusive signed branch comparisons and zero/nonzero power-of-two
  remainder tests into direct conditional branches. Keep observable Boolean
  and remainder results, short-circuit effects, extra readers and CFG barriers.
- Select compact immediate moves with correct sign/zero extension and a
  full-width fallback. Rematerialize integer literals and string addresses,
  use checked compact ELF address relocations, and retain full-width paths for
  high layouts, including Windows PE addresses.
- Lower positive non-power-of-two literal division and remainder with verified
  signed reciprocal arithmetic. Preserve negative-dividend corrections,
  negative-divisor fallbacks, division by zero and `INT64_MIN / -1` traps.
  Proven nonnegative snapshots and bounded scalar recurrences permit shorter
  signed arithmetic; multiplication uses shifts or LEA where appropriate.
- Pass resolved user-call and syscall arguments directly in their ABI
  locations when safe, preserving order, stack arguments, alignment and
  clobbers. Keep an additional call-heavy benchmark alongside the six kernels.
- Remove unread nontrapping expression trees, address allocations and branch
  result copies, including copies with multiple definitions. Preserve calls,
  memory operations, faults, observable joins and private spill homes.
- Keep frequently used locals in up to five dedicated callee-saved registers
  in eligible freestanding scalar functions. Direct counter, affine-update,
  signed power-of-two arithmetic and comparison instructions operate on these
  homes across joins, nested loops, break and continue. Calls, memory accesses,
  captures, boxed values and unknown bindings exclude promotion; virtual
  temporary liveness and GC-root rules retain their existing guarantees.
- Store relocation kind/offset/target triples in bounded chunks of 1,024
  records instead of a doubling list of maps. This fixes compiler-build OOMs
  where a 512 KiB contiguous allocation could not fit despite about 162 MiB
  of fragmented free heap. x86-64, ARM64 and RISC-V patchers retain relocation
  ordering. Production heap sizing and collector policy are unchanged.

## Recorded performance

The committed 100-run interleaved experiment on an Intel i5-13500H, performance
CPU 2, GCC 14.2, compares the pre-optimization compiler `f551c97` with the
optimized RAW backend. These are saved pre-release measurements, not a new
release-build timing trial. All six checksums match in every sample.

| Measurement | Original RAW | Optimized RAW |
| --- | ---: | ---: |
| End-to-end median | 44.499 ms | 21.700 ms |
| Standard deviation | 0.772 ms | 0.322 ms |
| Dynamic instructions, five-run median | 778,075,220 | 181,598,885 |
| Cycles, five-run median | 202,904,018 | 96,883,675 |

Median runtime falls **51.2%**, a **2.05× speedup**; instructions fall **76.7%**
and cycles **52.3%**. The same trial records GCC at **18.057 ms** with
`-O3 -march=native`, or **17.593 ms** with tree vectorization disabled.
The host was pinned, not isolated. Samples, dispersion, source/compiler hashes,
checksums, disassembly notes and PMU coverage are retained in the
[design report](compiler/mayc/tests/backend/raw-local-registers.md) and
[complete measurement data](compiler/mayc/tests/backend/raw-local-register-performance.json).
No machine-specific speed threshold is added to CI.

Merged [PR #77](https://github.com/mirged/maylang/pull/77) completes
[issue #76](https://github.com/mirged/maylang/issues/76). Remaining branch
if-conversion and memory-address/loop-state opportunities are tracked in
[#78](https://github.com/mirged/maylang/issues/78) and
[#79](https://github.com/mirged/maylang/issues/79). This release does not claim
GCC parity on every workload.

## Native UI and rendering

- Render clipped widget geometry, rounded edges, concentric borders, soft
  shadows, lines and text through a Sokol/OpenGL GPU batch. A dedicated Linux
  graphics thread receives immutable geometry/atlas packets; widgets, layout,
  interaction and application state remain Maylang.
- Cache fractional-position Unicode glyphs in an oversampled atlas, reuse
  geometry and framebuffer storage, bound glyph/measurement caches, and upload
  atlas content only when it changes. Keep software rendering for headless
  surfaces, snapshots and pixel inspection.
- Add light/dark themes, primary controls, borders, elevation, cards and
  disabled controls, with hover/pressed states and keyboard-focus decoration.
  Reduce redundant cursor changes and repeated hit-region searches. Retain
  layout recalculation for mutable trees and resizing.
- Add `upload_rgba`, an aspect-fit framebuffer widget with optional integer
  scaling, held/pressed key queries and native focus reporting. Add
  `poll_for`, renderer identification and rendering/cache statistics.
- Update the UI scaffold, Mayboard workspace, showcase, package native build,
  dependency doctor and library reference for the new renderer. Vendor Sokol
  headers and preserve upstream license/provenance records; builds need no
  dependency download.

**UI build migration:** existing native targets compiling `window.c` must use
`sokol.c` and link X11, Xi, Xcursor, OpenGL, `dl`, pthread and `m`. Install
`libx11-dev libxi-dev libxcursor-dev libgl-dev` and a TrueType font on
Debian/Ubuntu. Native windows require X11/XWayland and OpenGL 4.3; Mesa software
rendering works. Public `Widget`/`Window` records gained fields; prefer the
documented constructors and helpers when updating applications. See the
[UI guide](stdlib/ui/README.md).

## May NES example application

- Add a Maylang desktop NES player using the vendored MIT-licensed binjnes core
  for CPU/PPU/APU/cartridge emulation. Include the original MIT-licensed Starfall
  homebrew ROM and its reproducible builder; no other games are bundled.
- Support uncompressed iNES 1.0 cartridge loading, recent paths/preferences,
  aspect-fit or integer scaling, simultaneous controller keys, pause/resume,
  frame stepping, reset, mute and NTSC/PAL frame scheduling.
- Add optional PulseAudio/PipeWire audio, a file-picker/path-entry workflow,
  background/text-entry pause, manual save/restore and periodic battery SRAM
  persistence. Validate state identity/size/checksums and write persistence
  through exclusive temporary files, synchronization and atomic rename.
- Add headless screenshots/reports, deterministic core/state/persistence
  checks, sanitizer coverage for cartridge switching and isolated desktop
  tests for actual GPU output and interaction. See the
  [May NES guide](examples/apps/maynes/README.md) for controls,
  dependencies, mapper coverage and format limits.

## Verification, CI and distribution

- Add RAW execution/IR/disassembly regressions for operand locations, snapshots,
  spills, nested loops, effects, full-width signed arithmetic, constant
  division, ABI/syscall clobbers and every benchmark checksum. Dedicated-local
  arithmetic coverage includes 720 full-width cases across RBX and r12-r15.
- Extend Windows emulation to verify RBX preservation. Keep forced-GC,
  portable-core and LLVM checks; move interactive UI execution into its
  dependency-aware native harness instead of the generic entrypoint runner.
- Add the 65,537-relocation ordering, context-isolation and replacement
  regression under an 8 MiB runtime heap. The former representation exhausts
  that heap. Repeated IR-inspection builds and byte-identical bootstrap
  generations verify the compiler-build fix.
- The merged source passed **115 compiler verifier checks**, **69 compliance
  cases**, Rust workspace tests, source-bootstrap convergence, LLVM,
  documentation/tooling/UI, extracted release/installer checks, portable-core
  emulation and native macOS/Windows loader checks. Tagged publication runs
  release checks, compares two generated bundles/installers, and publishes the
  Linux archive, editor extension, standalone installers and checksums.
- Synchronize compiler, release metadata, README and editor extension versions
  to 0.13.101. Install the new renderer's development dependencies explicitly
  in the tagged-release workflow.

Maylang remains experimental. Compiler hosts and full-runtime release bundles
remain Linux x86-64, including x86-64 WSL 2. The native UI currently supports
one active surface and the Linux OpenGL backend; accessibility integration,
IME composition, rich text and general image collections remain unfinished.
May NES does not implement NES 2.0, ZIP/FDS loading, gamepads or a second
controller; save states are local to the build/architecture. The supported
behavior-contract fragment and its security/resource-proof limits are unchanged
from 0.13.0; see [behavior support](docs/internals/BEHAVIOR.md) and the
[conformance ledger](docs/design/BEHAVIOR_PROGRESS.md).

[Full Git changelog: v0.13.0...v0.13.101](https://github.com/mirged/maylang/compare/v0.13.0...v0.13.101).

---

# Maylang 0.13.0 — Dahlia

Released 2026-10-16 UTC. Closed callable behavior contracts and a broader
checked scalar fragment, with runtime list boundary fixes.

- Write closed effect ceilings on callable types, such as
  `Fn(Int) -> Int ! pure` and `Fn(Int) -> Int ! {output}`. Check named source
  functions and callback calls against those ceilings, preserving rows through
  type identity, substitution, joins, generic inference and function variance.
  Reject erased `Any`, unchecked foreign declarations and shared-container
  storage that could bypass a finite callable contract.
- Check `Float` scalar operations and pure `pi`/`e` constants, private scalar
  mutation, and `while` loops with `break` and `continue` in behavior-checked
  bodies. Preserve normalized behavior summaries in compiler IR snapshots.
- Report shortest call paths for unsupported behavior, including recursive and
  competing helper paths. Unknown bodies remain unknown rather than receiving
  an inferred pure row. Document the scalar core and outstanding proof work.
- Guard list payload access, push/pop and indexed writes in full/core runtimes.
  Invalid dynamic list values now report a type failure instead of accessing
  unrelated memory. List and string reads reject non-integer indices.
  **Behavior change:** list assignment requires an existing index; use `push`
  to append. Negative and past-end reads still return `nil`, and arbitrary map
  keys retain their existing semantics.
- Add native, LLVM, portable-core and actual loader regressions, including
  recovery after rejected writes. Load GC probes through the runtime ABI while
  retaining allocation-identity and root-table boundary checks.

Validation includes 87 compiler verification checks, 90 native/core/LLVM list
boundary cases, compiler-generation convergence, LLVM checks, all five
portable-core ISA/format combinations, and macOS/Windows loader fixtures.
Tagged publication additionally verifies reproducible packages, extracted
installation, standalone installers and the editor extension.

Maylang remains experimental. Closed rows currently cover the documented
scalar/callable fragment and known `output`/`clock` effects. Effect polymorphism,
closures in checked bodies, capability containment, ownership, information-flow
security, termination and resource bounds are unfinished. Runtime guards do
not establish memory safety or permit finite callable contracts in mutable
containers. Compiler hosts and full-runtime bundles remain Linux x86-64,
including x86-64 WSL 2. See [behavior support](docs/internals/BEHAVIOR.md) and the
[design conformance ledger](docs/design/BEHAVIOR_PROGRESS.md) for exact limits.

---

# Maylang 0.12.3 — Clover

Released 2026-10-15 UTC. Improve explanations for scalar behavior contracts.

- Report the shortest call path to a contributing primitive when an inferred
  effect exceeds a declared ceiling. Update witnesses across fixed-point
  iterations, including recursive graphs; keep equal-length selection stable.
- Add regressions for competing paths, propagated improvements, recursion and
  equal-length witnesses. Unknown-operation diagnostics still use their
  discovery path; the supported behavior fragment is unchanged.
- Include the fixes since 0.12.2 for verified optional stable-release updates,
  hourly update scheduling and compiler-worker editor-index cleanup.

Maylang remains experimental. These scalar effect checks do not establish
capability containment, termination, failure freedom or resource bounds.

---

# Maylang 0.12.2 — Clover

Released 2026-10-15 UTC. A patch release for the interactive installer following
the terminal UI refactor.

- Allocate terminal state on demand and require both input and output terminals
  before enabling interactive rendering. Fall back to plain menus for missing
  or dumb terminal settings and small windows.
- Poll for escape-sequence input so Escape cancels promptly; restore terminal
  settings after selection, cancellation and errors. Preserve queued keys when
  moving between menus so fast selections are not discarded.
- Use compact menu rows, dedicated folder and shell-profile prompts, bounded
  labels and progress indicators, and normalized component selections. Keep
  typed answers in the prompt buffer and detect the terminal after reconnecting
  input for the one-line curl-to-shell installation.

The complete independent toolchain and one-line installer remain available for
Linux x86-64, including x86-64 WSL 2. The language and runtime limits described
for 0.12.1 are unchanged.

---

# Maylang 0.12.1 — Clover

Released 2026-10-14 UTC. The first published Clover release includes the
one-line installer, interactive setup, independent toolchains and compiler
improvements described below. Check terminal cleanup writes under the same
hardened C compilation flags used in Ubuntu CI; restore terminal state on
interruption. The unpublished `v0.12.0` source tag remains immutable.

---

# Maylang 0.12.0 — Clover

Source tagged 2026-10-14 UTC. Publication was held after Ubuntu hardened
compilation caught an unchecked terminal-cleanup write. The immutable tag is
retained; 0.12.1 is the first published Clover bundle.

Install Maylang from one command, then follow the
interactive setup. No checkout or compiler is required to install it.

- Publish a small HTTPS downloader and a prebuilt, self-contained native installer.
  The Maylang interface includes arrow-key menus, a recommended setup, custom
  tool checkboxes, live file-copy progress, compiler verification, shell setup
  and a clear first-project walkthrough. Plain menus and NO_COLOR are supported.
- Copy complete independent toolchains into `~/.maylang`, with managed shell
  integration and an uninstaller. Removing the checkout leaves installed tools
  working. Checksum failures and interrupted setup preserve the active install.
- Resolve runtime sidecars through PATH/symlinks. Release completed compiler
  frontend state so a 4,096-reachable/4,096-dead function graph compiles within
  the existing 256 MiB heap. Build ELF string tables without quadratic copying.
- Add checksum-verified GC/codegen limit workloads, retained disassembly and
  optimized LLVM IR, and measured signed power-of-two division improvements.

Compiler hosts remain Linux x86-64, including x86-64 WSL 2. The existing
sustained-GC investigation [#2](https://github.com/mirged/maylang/issues/2)
remains open. This release does not establish native compiler-host support for
macOS, Windows or ARM64.

---

# Maylang 0.11.2 — Bramble

Released 2026-10-13 UTC. A patch release for workspace runner performance.

- Remove repeated UTF-8 prefix scans from native `split`, `chars`, `substring`
  and environment lookup, and simplify shared path slicing. The same changes
  ship in the compiler, workspace runner, legacy project manager, formatter
  and language server's native prelude.
- In five local samples using the same compiler, environment and cached
  executable, median cached `may run` time fell from 6.10 seconds to 26.6 ms,
  and cached `may build` from 4.20 seconds to 23.8 ms. The original reported
  workspace ran in 22 ms after installing the optimized runner. Absolute
  timings depend on the host and environment; see
  [the performance report](tools/may/PERFORMANCE.md) for raw samples and
  reproduction instructions.
- Preserve content hashing, output verification and atomic publication.
  Regressions cover same-size/same-timestamp source, import, compiler and runtime
  changes, corrupted outputs, executable permissions, Unicode/NUL strings,
  large environments and source-only compiler-generation convergence.
- Keep the C bootstrap's string byte storage compatible with the optimized
  prelude, and add native/LLVM string checks and an optional CI runner benchmark.

Fixes [#31](https://github.com/mirged/maylang/issues/31) through
[PR #33](https://github.com/mirged/maylang/pull/33). The existing sustained-GC
report [#2](https://github.com/mirged/maylang/issues/2) and JSON/NUL serialization
bug [#32](https://github.com/mirged/maylang/issues/32) remain open. Tool hosts
remain Linux x86-64; other runtime and native UI limits are unchanged.

---

# Maylang 0.11.1 — Bramble

Released 2026-10-13 UTC. Includes the complete Bramble workspace, GC, formatter,
native UI and Mayboard features described below.

The language server now excludes `.may/` build caches from source indexing and
workspace/navigation scans. It distinguishes files from directories before
reading a `.may` suffix, so legitimate directories such as `sources.may/` still
get traversed and their programs get checked. Directory URIs are rejected as
documents instead of triggering a read error. Focused regressions cover cache
contents, directory creation notifications, nested source diagnostics and symbols.

The existing `v0.11.0` source tag is retained. Its publication was stopped before
assets were released when running the complete app exposed the cache-directory
interaction. Dates record actual publication separately from version numbers.

---

# Maylang 0.11.0 — Bramble

Source tagged 2026-10-12. Publication was held after the final real-workspace
check found the build-cache directory scan failure. The tag remains immutable;
0.11.1 is the first published Bramble bundle.

Everyday workspaces and the first native desktop UI toolkit.

## Everyday ergonomics

- One shared CLI/editor formatter, including Unicode strings and nested comments.
  Organize-imports actions sort only complete lexical directives, preserving
  attached statements and import-looking text inside comments/strings.
- Nested `/* ... */` source comments and comment/string-aware import scanning.
  Statements and additional imports after a same-line import are preserved,
  including their original diagnostic columns.
- `may` workspaces replace source guessing with an explicit `may.json` graph of
  applications, executable test groups, native build recipes and action tasks.
- Content-addressed artifact verification, atomic publication, source-change
  detection, build serialization, local dependency content pins and dev/release
  profiles. Commands receive literal argument arrays without shell expansion.
- `may dev` reloads after successful builds, preserves the running app after a
  failed edit, and reaps replaced processes. `may migrate` preserves legacy
  `mayproj.json`; `maypkg` remains available.

## Native UI and a complete application

- Typed Maylang widget trees, row/column flex layout, buttons, checkboxes,
  codepoint-safe single-line inputs, focus, clipboard, clipped scrolling and
  virtual lists. A small X11/CPU drawing adapter supplies the platform boundary.
- `may new DIRECTORY --ui` creates a runnable desktop project with a declared
  native adapter prerequisite. Headless rendering supports PNG snapshots.
- Mayboard provides task creation, editing, completion, deletion, search and
  filters. It validates task files, locks out competing writers, synchronizes
  private atomic saves, and preserves corrupt input. A demo mode stores changes
  in memory; native X11 tests cover input and persistent reopen behavior.

## Runtime and tooling confidence

- Seeded 4 MiB GC stress uses an independent graph model plus heap/free-bin
  invariants. Injected corruption verifies that the checkers detect failures;
  lists, maps, Unicode copied strings, closures and suspended fibers retain
  their values through collection pressure.
- Workspace diagnostics isolate imported graphs within a source budget. Worker
  stdout cannot contaminate JSON, and crashes report the actual exit/signal.
- Bundles include `may`, `mayfmt`, the complete Mayboard workspace, UI adapter
  sources, editor tools and
  checksums. Extracted installations build a UI scaffold and render a PNG.

## Current limits

Tool hosts and interactive UI require Linux x86-64. UI uses the direct native
backend; experimental LLVM currently has no C `extern` support. UI needs a C compiler,
X11 development headers, a trusted TrueType font, and X11/XWayland for windows.
The toolkit currently supports one window, plain single-line text and whole-input
selection; it has no accessibility bridge or GPU rendering. Dependencies are
local paths with content pins; there is no central registry or host-toolchain
lock. The original sustained-GC report (#2) remains unreproduced; bounded stress
coverage does not prove arbitrary programs correct. See the linked tool/library
READMEs for supported behavior.

---

# Maylang 0.10.0 — Aster

Released 2026-10-12. A fresh starting point after the 0.9.0 line, with verified
native targets, clearer library contracts and a small compiler convenience.

## New feature

`mayc --list-targets` lists the six supported targets, their output formats and
default runtimes. It works without a source file or runtime sidecars. The
listing distinguishes full/core defaults and labels the experimental LLVM
backend; the compiler itself still runs on Linux x86-64.

## Included improvements

- Real Apple Silicon macOS and Windows loader tests, with PE/Mach-O fixes.
- Explicit core scratch arenas with reset lifetime rules.
- Encoded-pointer GC roots and a checked global-root table capacity.
- Collection, string and path boundary fixes with native/LLVM regressions.
- A dependency-free generated language/library reference and runnable examples.
- Source-tagged, reproducible toolchain bundles and checksummed editor assets.

The original sustained GC corruption report (#2) remains open: both sides of a
100,000-generation comparison passed. Existing runtime limits and the worker
workaround remain documented.

## Version identity

The version is `0.10.0`, the source tag is `v0.10.0`, and the codename is **Aster**.
Codenames name each minor series and stay the same for its patch releases.
Dates record publication; they are separate from version numbers. See the
[release convention](docs/guide/RELEASING.md).

The earlier `v0.9.0-2026-10-10-nightly` prerelease was published on 2026-10-12
with a stale date in its tag. It is retained as historical provenance and is
superseded by Aster; published tags are never reused or moved.
