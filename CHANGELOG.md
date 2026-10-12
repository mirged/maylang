# Maylang 0.11.0 — Bramble

Released 2026-10-12. Everyday workspaces and the first native desktop UI toolkit.

## Everyday ergonomics

- One shared CLI/editor formatter, including Unicode strings and nested comments.
- Nested `/* ... */` source comments and comment/string-aware import scanning.
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
- Bundles include `may`, `mayfmt`, the UI adapter sources, editor tools and
  checksums. Extracted installations build a UI scaffold and render a PNG.

## Current limits

Tool hosts and interactive UI require Linux x86-64. Native UI needs a C compiler,
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
