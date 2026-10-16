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
including x86-64 WSL 2. See [behavior support](docs/BEHAVIOR.md) and the
[design conformance ledger](docs/BEHAVIOR_PROGRESS.md) for exact limits.

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
  [the performance report](toolchain/may/PERFORMANCE.md) for raw samples and
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
[release convention](docs/RELEASING.md).

The earlier `v0.9.0-2026-10-10-nightly` prerelease was published on 2026-10-12
with a stale date in its tag. It is retained as historical provenance and is
superseded by Aster; published tags are never reused or moved.
