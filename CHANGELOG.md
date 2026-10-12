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
