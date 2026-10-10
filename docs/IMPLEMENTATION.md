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
  the compiler, libraries, core targets, project manager, LSP and release bundle.

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

## Remaining limits

The issue acceptance audit additionally covers atomic successful-build state
publication under concurrent readers and failed rename cleanup, actionable LSP
startup errors, nested/selective import and Unicode diagnostic locations, and
bounded CPU/address-space use with seeded import-graph mutations. The roadmap
records the exact completed and remaining issue scope against PR #21.

The original sustained ecosystem corruption report is not conclusively resolved:
the 5000-generation workload also passed with the old runtime. The proven
interior-header bug is fixed, but the existing worker workaround and warning
remain until the original failing workload can be reproduced and verified.
The collector remains conservative, nonmoving and limited to a fixed heap.

Core memory is retained until process exit and capped at 256 MiB. Full runtime
and toolchain hosting remain Linux x86-64; emulation does not verify real macOS
signing or Windows/macOS loader behavior. LLVM still excludes fibers and typed
externs. Int64/UInt64 do not provide full-width payloads, and mutable dynamic
aliases can bypass collection invariants until a typed boundary is checked.
Recovery is bounded to independent parser/type errors; some frontend stages
still stop at their first error. Source traces do not supply a debugger format.
