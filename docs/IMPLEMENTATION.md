# Dependable Maylang implementation

This work follows the language assessment: make runtime behavior dependable,
complete typed results and enum matching, clarify numeric contracts, unify
installation and project builds, and improve compiler feedback. Changes are
delivered in focused commits with regressions and source-bootstrap verification.

## Acceptance criteria

- Reject stale/interior GC pointer candidates, preserve live graphs across
  repeated collections, and exercise a sustained real application workload.
- Infer typed result constructors and check `?` propagation against the
  enclosing function; support typed enum payload patterns and exhaustiveness.
- Give ordinary I/O and result helpers useful static contracts; explicitly
  document the representation and remaining fixed-width restrictions.
- Produce an installable toolchain bundle and verify it outside the checkout.
- Make package-manager compiler selection explicit, apply target/runtime
  configuration, and invalidate builds when inputs or configuration change.
- Offer structured diagnostics and useful error recovery with regression tests.
- Keep one maintained CLI application in installation/workflow checks.

## Validation

Run focused tests for each change, then the source-only bootstrap, successive
self-hosting generations, compiler verification, compliance and LSP suites.
Record actual results and remaining limits here as the work progresses.

Existing uncommitted guide/reference changes belong to the user and are excluded
from this implementation's commits.

## Delivered

- Allocation-start identity checks, runtime metadata roots and deterministic
  mark-stack exhaustion, with a regression that failed on the old collector.
- Typed Result inference, checked propagation, enum payload bindings and
  exhaustive matches; generic result helpers and concrete I/O signatures.
- Integer bounds, binary32 rounding and fixed-array lengths while preserving
  the tagged ABI; explicit 61-bit limits for Int64/UInt64.
- Complete growing binary file reads and partial-write handling; inherited
  environments and checked process exits.
- Consistent compiler/configuration selection and content-based successful-build
  state in maypkg, including runtime/library sidecars and malformed manifests.
- Versioned JSON diagnostics, bounded independent-error recovery, LSP diagnostic
  publication and opt-in source traces with handler/fiber isolation.
- Complete reproducible toolchain archives, installed-tool verification,
  a packaged VS Code extension and a fully typed maintained textstats CLI.
- Bounded seeded parser mutations with minimized failure artifacts; CI gates
  the compiler, libraries, native core, project manager, LSP and release bundle.
  Cross-target emulation runs in a separate optional job.

## Verified locally

On Linux x86-64, 2026-10-10:

- Rust workspace tests pass offline with the lockfile (two pre-existing
  native-runtime integration tests remain explicitly ignored).
- Rust -> C -> native source bootstrap passes; native stages 2 and 3 are
  byte-identical. The native four-generation verification also converged.
- Current compiler verification: **93 passed, 0 failed**. Language compliance:
  **69 passed, 0 failed, 0 observations**.
- Numeric, library, binary I/O and debug-trace regressions pass on native and
  experimental LLVM output. The complete LSP and project-workflow suites pass.
- Core programs execute through Unicorn 2.1.4 on Linux x86-64/ARM64/RISC-V64,
  macOS ARM64 and Windows x86-64, including overflow, partial writes and bounded
  retained-heap exhaustion. Linux x86-64 also executes natively.
- An extracted archive passes checksums, version, standalone library compilation,
  incremental builds and LSP startup; its compiler builds and runs typed textstats.
  The VS Code extension compiles and packages as a VSIX.
- Seed 731 passes 48 frontend mutations plus cyclic/alternate import paths.
  A real ecosystem workload runs 5000 generations successfully.

## Codegen reachability follow-up

On Linux x86-64, 2026-10-11, emission starts with main and follows actual code
references through a deduplicated worklist. Native label relocations include
implicit runtime calls and closure addresses; LLVM records calls, function
values, closure labels and its uncaught-error helper. Unused functions, literals,
ELF symbols and native fiber-switch code are omitted. Foreign declarations are
checked normally, but only reachable bindings allocate loader slots or introduce
library/symbol dependencies. Imported and top-level initialization remain roots.
Runtime IR is still prepared before emission; this change strips generated code
rather than claiming to eliminate all frontend work.

The reachability suite passes native and LLVM execution for direct/indirect
calls, captures, mutual recursion, initialization, handlers, numeric operations
and unused externs. It also checks live foreign calls/function values, pruned
loader entries, stripped core/raw output and diagnostics in unused declarations.
Portable core tests execute all five targets through Unicorn, including numeric
errors and bounded retained-heap exhaustion.

[Recorded codegen measurements](../toolchain/mayc/tests/backend/reachability-performance.json)
reduce hello from 252,864 to 133,088 bytes (47.4%) and features from 314,072 to
207,216 bytes (34.0%), with identical sidecars and matching output. Example
compilation uses three samples and no timing gate. The comparison explicitly
skips compiler rebuilds because the older compiler exhausted its fixed heap on
the updated source; the updated compiler passes the default benchmark's rebuild
and version execution. No comparative rebuild speedup is claimed.

## Project workflow follow-up

[PR #22](https://github.com/mirged/maylang/pull/22) completes issues #3 and #18.
On Linux x86-64, 2026-10-11, the combined maypkg suite passes isolated command,
import/cycle/orphan, ancestor-discovery, quoted-path, native/generated watcher,
failed-build recovery, process-group shutdown and cleanup-preservation checks.
The watcher records inputs before its first run; output paths cannot replace
sources/metadata or escape the project, and `new` refuses nonempty directories.

The benchmark passes current-only and baseline-comparison modes, checking
program output and executing rebuilt compilers. CI keeps cross-target emulation
optional and runs performance measurements only on manual workflow dispatch;
both consume checksummed artifacts from the required bootstrap job. Performance
reports include samples, compiler/sidecar hashes and image sizes, without a
timing threshold. Branch protection settings remain the repository owner's
choice; optional jobs use `continue-on-error` independently of required checks.

## Language server follow-up

[PR #23](https://github.com/mirged/maylang/pull/23) completes issues #13 and #14.
On Linux x86-64, 2026-10-11, the full LSP protocol suite passes semantic delta
negotiation/replay, Unicode, ID eviction and document lifecycle tests, plus
1,024-file navigation interleaved with hover, cancellation, edits and unsaved
imports. It verifies bounded queues, late rename failures, worker fatal-output
isolation, recovery and shutdown reaping. Generated references pass `--check`.

Navigation uses one worker, 32 queued requests, a 30-second deadline and a
16 MiB result limit. Disk indexes are processed in batches of 32; encoded
results stream to the parent with a final status, preventing incomplete rename
responses. A 10,016-file benchmark returns exactly 10,000 references/rename
targets and one matching workspace symbol. One run measured navigation at
4.72/7.37/2.20 seconds and interleaved hover at 0.89/3.67/9.21 milliseconds.
The optional performance job repeats this benchmark on the installed bundle
and publishes a report without timing gates.

Document indexing remains synchronous. Workspace pull support is recorded
below. Large individual files, dependency graphs and result sets still face
runtime heap/worker limits; bounded request failure is handled without leaking
worker output into the LSP transport. These changes do not resolve the original
sustained-runtime GC corruption report.

## Workspace diagnostics follow-up

[PR #24](https://github.com/mirged/maylang/pull/24) implements issue #12.
On Linux x86-64, 2026-10-11, the complete LSP suite passes unopened-file
reports, full/unchanged IDs, progress, dirty imports, deleted files, removed
roots, concurrent hover/document pulls, cancellation and stale snapshots.
It checks queue bounds, fatal-output isolation, recovery and worker reaping.
Mixed lexer/name failures across more files than the recovery cap preserve
independent errors, and unrelated modules cannot expose unimported names.
Restart tests verify that old IDs cannot conceal subsequent disk changes.
The source rebuild passes; compiler verification passes **93/0** and language
compliance passes **69/0**.

Workspace pulls use one worker and eight queued requests. A worker checks at
most 32 entries before replacement; clean entries share a compiler check,
while any error causes individual checks. Reports stream to clients that
provide partial-result tokens; other clients receive a buffered full response.
Request bounds are 10,000 selected files, 16 MiB of worker output, 30 seconds
without a report and five minutes total. Result IDs include session/epoch/URI.
Encoded full reports use a 16 MiB mapping capped at 10,000 entries and cleared
on snapshot changes. Compiler symbol tables own zeroed mappings with
explicit release, and AST/strict-checker roots are released between checks.
Unchanged reports avoid indexes and compiler state, changed files run first,
and buffered responses emit one frame without a second large joined string.
Byte scans avoid materialized integer ranges and URI encoding copies spans.
A near-limit 15 MiB frame is accepted without breaking subsequent pulls.

The diagnostic benchmark exercises cold streamed and unchanged buffered pulls
with interleaved hover on 10,016 files. It checks open/unopened versions, stable
IDs, the 10,000-file cap and preservation of reports for existing omitted files.
The manual CI performance job repeats it on the extracted bundle and publishes
`diagnostic-benchmark.json` alongside compiler and navigation measurements.
Exact validation runs and measurements are recorded in the linked PR.

## Open-issue follow-up (2026-10-12)

Native core/raw loader validation now passes on Apple Silicon macOS 14.8.9 and
15.7.9 and Windows Server 2022/2025. The suite exposed actual PE/Mach-O defects
that emulation missed; fixes include omitting an empty PE section, Mach-O
signature storage, 4 GiB page zero, platform/build metadata, dyld/libSystem
loading, empty binding/rebase streams, LC_MAIN and ASLR-safe ADRP/ADD references.
[Native host evidence](NATIVE_TARGETS.md) links the successful Actions run.

Core has explicit, owned raw scratch arenas. A reset invalidates its spans and
reclaims usable capacity without returning pages to the OS. Tests request 1 GiB
cumulatively while retaining only 1,052,672 bytes, across all five emulated
targets and native Windows/macOS. Ordinary strings/lists retain their existing
process lifetime and 256 MiB cap. See [lifetime rules](CORE_MEMORY.md).

The GC audit found a separate deterministic encoded-cstr root defect. Its
regression fails with exit 6 before the change: the only copied-buffer address
is encoded as `address * 8`, which the collector previously ignored. Decoded
candidates now pass the same allocation-start identity checks. The regression
preserves the copy and growing live graph through 100 forced collections.
The audit also reproduced a global-root registry overflow: registration 131,073
overwrote the next allocation header. The runtime now exits 70 before this
write; the regression fills all 131,072 entries and verifies the adjacent
header before exercising the guard.

A before/after comparison completed 100,000 ecosystem generations with both
runtimes, using the same compiler, workload and library sources. Both exited
zero with identical normalized simulation summaries and byte-identical genome
outputs. This workload still does not reproduce the original sustained
corruption report, so that issue remains open.

Library regressions cover empty stacks/queues, queue compaction and reference
release, invalid chunk/window sizes, empty padding, ASCII whitespace, Unicode
strings, lexical roots/relative paths, numeric boundaries and fixed ML inference
on native and LLVM. The user-selected guide migration is preserved as a
dependency-free Markdown reference: 447 declarations include exact signatures,
visibility, runtime/platform and experimental status. Both reference generators
pass `--check`, and 24 actual documentation examples compile and execute.

Tagged releases now require a clean checkout, version-matched tag and exact
source commit; provenance records compiler and bootstrap tools. The workflow
compares two archives, tests an extracted installation, packages a checksummed
VSIX and attaches all assets to a draft before publication. The source-contract
regressions and deterministic/extracted archive tests pass locally. The first [nightly prerelease](https://github.com/mirged/maylang/releases/tag/v0.9.0-2026-10-10-nightly)
is now published by the successful tagged-release workflow, with a complete
Linux bundle and VSIX plus adjacent checksums.

Local final validation also passes compiler verification **94/0**, compliance
**69/0**, offline Rust workspace tests, source bootstrap with byte-identical
native stages 2/3, the full LLVM suite, runtime-map/GC regressions and all-target
core emulation. The pinned VSIX packager produces an installable extension.

## GitHub issues #32, #34 and #35 (2026-10-13)

Both JSON stringifiers escape every control character U+0000–U+001F. The
regression uses Python's JSON parser to check strings, nested values and map
keys, plus native JSON roundtrips on x86-64 and LLVM and the raw quoting helper.
Unicode/NUL string tests no longer repair malformed output before parsing it.

Strict assignability rejects implicit `Any` narrowing, including nested
collections, typed writes, function arguments/returns and callback signatures.
`Some` preserves its payload type, native helper results retain known types,
and dynamic reductions cannot feed an unchecked value back into a typed
accumulator. Dynamic operations and explicitly dynamic native APIs keep their
runtime dispatch. See [conversion semantics and limitations](STRICT.md).
The workspace runner, browser, UI library and shipped applications retain
known state in typed records and convert values explicitly at their JSON,
layout and native boundaries.

ELF function and global symbols use module IDs assigned in deterministic
import-expansion order, such as `module0::main`. Canonical source paths continue
to serve resolution and diagnostics. Modules with identical filenames receive
distinct IDs; copying the same import graph to another directory produces the
same symbol names. The module regression checks both execution and `nm` output
in strict and legacy modes, including functions and globals.

Validation passes 102 compiler verification checks, 69 compliance cases,
source bootstrap with identical native stages 2/3, LLVM behavior tests, offline
Rust tests, LSP, formatter, maypkg and workspace workflows, Rivet storage and
ecosystem regressions. Browser HTTP and headless UI/widget/application checks
also pass; live X11 interaction and optional ISA emulation were not exercised.

## Remaining limits

The issue acceptance audit additionally covers atomic successful-build state
publication under concurrent readers and failed rename cleanup, actionable LSP
startup errors, nested/selective import and Unicode diagnostic locations, and
bounded CPU/address-space use with seeded import-graph mutations. The roadmap
records the exact completed and remaining issue scope against PR #21.

The original sustained ecosystem corruption report is not conclusively resolved:
the 100,000-generation comparison also passed with the old runtime. Proven
allocation-identity, encoded-pointer and root-table bugs are fixed, but the
existing worker workaround and warning
remain until the original failing workload can be reproduced and verified.
The collector remains conservative, nonmoving and limited to a fixed heap.

Core chunks are retained until process exit and capped at 256 MiB; explicit
scratch arenas reclaim reusable capacity. Full runtime and toolchain hosting
remain Linux x86-64; native Windows/macOS core/raw loaders now have separate
successful host checks. LLVM still excludes fibers and typed
externs. Int64/UInt64 do not provide full-width payloads, and mutable dynamic
aliases can bypass collection invariants until a typed boundary is checked.
Recovery is bounded to independent parser/type errors; some frontend stages
still stop at their first error. Source traces do not supply a debugger format.
