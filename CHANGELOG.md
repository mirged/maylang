# Unreleased

- Support maps, records, structs and enums in the core runtime on every native
  target; preserve exclusive range endpoints on ARM64 and RISC-V.
- Support typed extern calls and cooperative fibers in the LLVM backend,
  including C stack arguments, function values and isolated suspended handlers.
- Preserve each fiber's caught error and exception handlers across yields, and
  accept the C binding types `UInt` and `Void` under strict checking.
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
- Add an eleven-workload extended RAW benchmark suite
  ([report](compiler/mayc/tests/backend/raw-extended-suite.md)).

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
