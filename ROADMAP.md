# Maylang roadmap

Maylang aims to become a dependable language and toolchain that contributors can build from source, use in real projects, and improve together. This roadmap connects that direction to concrete outcomes and the [GitHub issue tracker](https://github.com/mirged/maylang/issues).

This is a living plan. Community needs, reproducible failures, contributor availability and implementation discoveries can change the order, scope or design of any milestone. Milestones have completion criteria rather than fixed dates or promised release versions. Inclusion here means planned work, not a guarantee of delivery.

## Starting point

The current project has a self-hosted compiler running on Linux x86-64, several native output targets, a Maylang language server, a package manager, a standard library and example projects. A minimal Rust → C bootstrap builds the compiler entirely from source. The documented gaps include full-runtime GC corruption under sustained allocation and native macOS/Windows execution that still needs verification. The linked issues capture the starting assumptions; verify them against current code before implementation.

## Milestones at a glance

| Milestone | Outcome | Initial issues | Readiness signal |
| --- | --- | --- | --- |
| 1. Reliable foundations | Build entirely from source and catch compiler/runtime regressions | #1, #2, #3, #9 | Rust bootstrap and self-hosting checks pass; the GC reproducer is fixed and covered |
| 2. Installable, verified toolchain | Install complete bundles and understand target support | #4, #5, #6, #7, #15 | Extracted releases work outside the checkout; native target tests and editor installation pass |
| 3. Dependable project workflows | Build and run projects with accurate incremental state | #16, #17, #18 | Compiler selection, invalidation and isolated package-manager tests pass |
| 4. Clear diagnostics and responsive editing | Understand failures and keep large workspaces usable | #10, #11, #12, #13, #14 | Diagnostic contracts and editor protocol/responsiveness checks pass |
| 5. Sustainable runtime and library contracts | Support longer-running programs and trustworthy references | #8, #19, #20 | Memory strategy, library boundaries and documentation builds are tested |

Work can proceed across milestones when dependencies allow. The source-only bootstrap is a prerequisite for removing the tracked compiler binary. Release installation and server naming should be agreed together. Structured diagnostics provide a useful foundation for error recovery and workspace diagnostics. Native target verification should use the compatibility matrix as its contract. Contributor interest may bring an independent later item forward.

## How the community can change the plan

Start by commenting on a linked issue with your use case, affected platform, reproduction or proposed contribution. For a new direction, [open an issue](https://github.com/mirged/maylang/issues/new) explaining the problem, who benefits, alternatives, likely dependencies and a testable success criterion. Small fixes can go straight to a focused pull request; substantial language, runtime or compatibility changes should first have an issue where contributors can discuss the design.

Reactions help show interest, while concrete examples and contributor commitments help assess impact and feasibility. Prioritization considers correctness, user impact, source-build accessibility, maintenance cost, compatibility, dependencies and available reviewers. Popularity is one input; reliability problems still need attention even when they attract fewer reactions.

Maintainers review proposals with contributors and record the decision and rationale in the issue. An accepted roadmap change should update this file in the same pull request, including milestone placement, dependencies and completion criteria. Items may be added, reordered, split, deferred or replaced. Record deferred or superseded work with its reason and a link to the replacement so community input remains visible. Roadmap changes can be proposed by anyone through a pull request.

Review the roadmap when preparing a release, completing a milestone or receiving evidence that changes a priority. No scheduled review or formal voting system is assumed. The issue tracker is the source of current discussion and implementation status; this file describes direction and readiness. Do not infer completion from issue numbering or milestone order.

## Tracking progress

The initial initiatives now include completed and partial implementations. [PR #21](https://github.com/mirged/maylang/pull/21) delivers initiatives 7, 9, 10, 11, 15, 16 and 17, and advances 2, 4, 8, 18 and 19. Remaining checkboxes retain their original scope; successful emulation, a heap cap or CI artifacts do not complete native-host, reclamation or tagged-release work. Use these states when updating an initiative: **planned**, **in progress**, **blocked**, **completed**, **deferred** or **superseded**. Link the implementation PR when work starts and identify a concrete dependency when marking work blocked. Keep checkboxes aligned with verified results.

A milestone is ready when its agreed acceptance criteria pass and the relevant documentation reflects the delivered behavior. If its scope changes, record the decision before declaring it complete. Each implementation should include regression coverage appropriate to the change, validation commands and results, and any remaining limitations. Keep source-only builds and supported-target behavior covered as the compiler evolves.

## Detailed initiatives

The initial priorities are P0 for foundational reliability and bootstrapping, P1 for practical adoption work, and P2 for planned capability improvements. They are revisable planning signals. Paths and checklists below are starting points for implementation and community review.

## Milestone 1. Reliable foundations

Make source builds and runtime correctness trustworthy before broadening adoption.

### Initiative 1. Bootstrap Maylang entirely from source

**Status:** completed
**Initial priority:** P0  
**GitHub:** [Issue #1](https://github.com/mirged/maylang/issues/1)  
**Relevant paths:** `toolchain/rust/`, `toolchain/rust/crates/`, `.github/workflows/bootstrap.yml`, `toolchain/mayc/main.may`, `README.md`

The supported stage-zero compiler reuses Rust frontend components and emits GNU C. It intentionally replaces the originally proposed `may_cli`/Rust native backend route with a smaller bootstrap. Native stages 2 and 3 converge to identical executables; fresh clones require Rust and GCC or Clang rather than a tracked compiler binary.

- [x] Document the bootstrap language/runtime subset and intentional differences (annotations are ignored; generated mayc performs strict checking).
- [x] Support current compiler syntax in the shared Rust frontend and minimal C emitter/runtime.
- [x] Document `cargo build --offline --locked --release -p may_bootstrap`, successive stages and the source-building launcher.
- [x] Add clean-checkout CI for source-only stage convergence and hello/strict cases.
- [x] Remove the tracked bootstrap binary and ignore all generated build directories. Optional downloadable binaries belong to release packaging (initiative 4).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 2. Fix full-runtime GC corruption under sustained allocation

**Status:** in progress
**Initial priority:** P0  
**GitHub:** [Issue #2](https://github.com/mirged/maylang/issues/2)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/runtime.may`, `toolchain/mayc/tests/stress.may`

The compiler guide documents collector corruption under sustained workloads.

- [ ] Reduce the failure to a deterministic reproducer.
- [ ] Audit root scanning, block reuse, coalescing and closure/map/string lifetimes.
- [ ] Fix corruption and exercise repeated forced collections.
- [ ] Add regression coverage and update the limitation after the stress case passes.

PR #21 fixes a proven interior-allocation-header bug and tests 100 forced collections, but the original sustained-workload corruption is not conclusively reproduced or resolved. Its limitation and worker workaround remain.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 3. Add CI for compiler, compliance and self-hosting verification

**Status:** in progress

**Initial priority:** P0  
**GitHub:** [Issue #3](https://github.com/mirged/maylang/issues/3)  
**Relevant paths:** `toolchain/mayc/tests/run.sh`, `tests/compliance/run.py`, `.github/workflows/`

The Linux workflow verifies source-only bootstrap convergence, the Rust workspace,
direct LLVM lowering, native compiler entrypoints and language compliance. It
uploads reports and failure logs. Optional emulator/performance jobs remain to
be separated and automated; the complete initiative stays open.

- [x] Add Linux x86-64 CI with explicit Python/binutils requirements.
- [x] Run compiler stage convergence and compliance checks on pull requests.
- [x] Upload reports and failure logs and fail on verification errors.
- [ ] Separate required checks from optional emulator/performance jobs.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 9. Add parser and import-expansion fuzzing with minimized regressions

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #9](https://github.com/mirged/maylang/issues/9)  
**Relevant paths:** `toolchain/mayc/src/lexer.may`, `toolchain/mayc/src/parser.may`, `tests/compliance/`

Malformed input coverage can be expanded systematically beyond handwritten cases.

- [x] Add seeded mutation of tokens, Unicode, nesting and import graphs.
- [x] Bound compile time/resources and distinguish rejection from crashes.
- [x] Minimize failures and save reproducible seeds.
- [x] Add reduced regressions and a bounded CI fuzz smoke run.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 2. Installable, verified toolchain

Deliver complete installations and validate the platforms advertised to users. Cross-emission support and native compiler-host support remain separate capabilities; expanding compiler hosts needs its own proposal and acceptance criteria.

### Initiative 4. Package reproducible releases with runtime sidecars

**Status:** in progress
**Initial priority:** P1  
**GitHub:** [Issue #4](https://github.com/mirged/maylang/issues/4)  
**Relevant paths:** `toolchain/mayc/mayc_new`, `toolchain/mayc/README.md`, `toolchain/maylsp/Makefile`

The compiler requires runtime sidecars, so copying its executable alone is insufficient.

- [x] Define a bundle layout for compiler, launcher, runtime, stdlib and LSP.
- [ ] Build from tagged source and record version/bootstrap provenance.
- [x] Publish checksums and verify an extracted bundle outside the checkout.
- [ ] Document installation, PATH and upgrades with binaries distributed as release assets.

PR #21 defines complete deterministic archives, records commit/version/bootstrap provenance, publishes checksummed CI artifacts and verifies extracted installations. Tagged-source releases and published release assets remain pending.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 5. Verify Mach-O output on native macOS runners

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #5](https://github.com/mirged/maylang/issues/5)  
**Relevant paths:** `toolchain/mayc/src/formats/macho.may`, `toolchain/mayc/tests/core_runtime.py`

The compiler guide says native macOS launches and signing are not yet verified.

- [ ] Cross-emit ARM64 Mach-O fixtures on the supported compiler host.
- [ ] Sign and execute fixtures on Apple Silicon.
- [ ] Check output, allocation, calls and exit behavior.
- [ ] Record tested macOS versions and automate native checks when runner access is available.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 6. Verify PE output on native Windows runners

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #6](https://github.com/mirged/maylang/issues/6)  
**Relevant paths:** `toolchain/mayc/src/formats/pe.may`, `toolchain/mayc/tests/core_runtime.py`

Windows execution is emulated; native loader behavior still needs validation.

- [ ] Cross-emit x86-64 PE fixtures for a Windows runner.
- [ ] Exercise kernel32 imports, allocation, output and exit status.
- [ ] Check loading and calling convention behavior with useful logs.
- [ ] Document tested Windows versions and automate the native checks.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 7. Publish and enforce a target/runtime feature compatibility matrix

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #7](https://github.com/mirged/maylang/issues/7)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/src/backend/`, `toolchain/mayc/tests/backends.py`

Supported features vary across targets and full/core/raw runtimes.

- [x] Inventory supported targets, runtime modes and features in one matrix.
- [x] Add pass/reject fixtures for documented capabilities.
- [x] Ensure unsupported features fail before executable output is written.
- [x] Keep CLI help, matrix and main README consistent.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 15. Align VS Code metadata and server discovery with maylsp

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #15](https://github.com/mirged/maylang/issues/15)  
**Relevant paths:** `editors/vscode/package.json`, `editors/vscode/README.md`, `toolchain/maylsp/README.md`

The extension uses example.invalid repository metadata and defaults to maylang-lsp, while the documented build produces maylsp.

- [x] Replace placeholder repository metadata with the real GitHub repository.
- [x] Choose one installed server name and align build/release/extension defaults.
- [x] Provide actionable missing-server errors and preserve serverPath overrides.
- [x] Compile/package the extension and smoke-test the installed bundle.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 3. Dependable project workflows

Make project discovery, builds and incremental development predictable for contributors and application authors.

### Initiative 16. Make maypkg compiler selection explicit and fix invocation documentation

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #16](https://github.com/mirged/maylang/issues/16)  
**Relevant paths:** `toolchain/maypkg/src/commands.may`, `toolchain/maypkg/README.md`

The README describes maylang build, while implementation invokes mayc and the repository documents mayc_new.

- [x] Add a compiler setting or MAYC override with a documented default.
- [x] Use it consistently for native and generated-script build/run/dev.
- [x] Align README and help text with actual commands.
- [x] Test spaces in paths, missing compilers and failed compilations.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 17. Include compiler, target and configuration in maypkg build fingerprints

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #17](https://github.com/mirged/maylang/issues/17)  
**Relevant paths:** `toolchain/maypkg/src/project.may`, `toolchain/maypkg/src/checksum.may`, `toolchain/maypkg/src/commands.may`

Source digests support incremental builds; audit freshness so toolchain/configuration changes cannot reuse stale outputs.

- [x] Include compiler identity, target, runtime, options and manifest settings.
- [x] Include resolved dependencies/stdlib and detect missing executables.
- [x] Write successful build state atomically only after compilation succeeds.
- [x] Test toolchain changes, target changes, failed builds and dependency edits.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 18. Add isolated end-to-end tests for maypkg commands

**Status:** in progress
**Initial priority:** P1  
**GitHub:** [Issue #18](https://github.com/mirged/maylang/issues/18)  
**Relevant paths:** `toolchain/maypkg/main.may`, `toolchain/maypkg/src/`, `toolchain/maypkg/README.md`

Discovery, shell generation, watching and cleanup need a focused reproducible integration suite.

- [ ] Create temporary fixture projects for new/init/sync/tree/lock/verify/build/run.
- [ ] Cover imports, cycles, orphans, ancestor discovery and paths with spaces.
- [ ] Test watcher rebuilds and shutdown with bounded subprocess timeouts.
- [ ] Verify clean/dry-run only affect generated artifacts and document one test command.

PR #21 adds isolated compiler/configuration selection, quoted paths, dependency/sidecar invalidation, failed-build recovery, new-project and atomic-state tests. Full command coverage, watcher lifecycle and clean/dry-run tests remain pending.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 4. Clear diagnostics and responsive editing

Improve how the compiler explains failures and how the editor behaves under real workspace load.

### Initiative 10. Add structured compiler diagnostics with original imported source locations

**Status:** completed
**Initial priority:** P1  
**GitHub:** [Issue #10](https://github.com/mirged/maylang/issues/10)  
**Relevant paths:** `toolchain/mayc/main.may`, `toolchain/mayc/src/`, `toolchain/maylsp/src/diagnostics.may`

Automation and editors benefit from a stable diagnostic interface that preserves locations after import expansion.

- [x] Specify diagnostic codes, severity, file and source ranges.
- [x] Add a machine-readable CLI output mode.
- [x] Test nested/selective imports and Unicode positions.
- [x] Share or consume the representation in the LSP and document schema stability.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 11. Recover from frontend errors and report multiple diagnostics

**Status:** completed
**Initial priority:** P2  
**GitHub:** [Issue #11](https://github.com/mirged/maylang/issues/11)  
**Relevant paths:** `toolchain/mayc/src/parser.may`, `toolchain/mayc/src/strict.may`, `toolchain/maylsp/README.md`

The LSP guide says checking stops at the first syntax or semantic error in an import closure.

- [x] Define parser synchronization and prevent misleading cascading errors.
- [x] Collect independent semantic errors without generating failed programs.
- [x] Return multiple stable diagnostics in the language server.
- [x] Test multiple errors/files and recovery after edits.

**Implementation:** [PR #21](https://github.com/mirged/maylang/pull/21). Verified compiler/stdlib/LSP/project checks and GitHub CI are recorded in [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 12. Implement workspace-wide pull diagnostics in maylsp

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #12](https://github.com/mirged/maylang/issues/12)  
**Relevant paths:** `toolchain/maylsp/main.may`, `toolchain/maylsp/src/scheduler.may`

Workspace-wide pull diagnostics are explicitly not advertised by the current server.

- [ ] Implement workspace/diagnostic negotiation and result identifiers.
- [ ] Cover unopened files with bounded scheduling and progress.
- [ ] Handle cancellation, deletion and unsaved imports without stale results.
- [ ] Add protocol tests for full, unchanged and cancelled reports.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 13. Implement semantic token delta responses in maylsp

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #13](https://github.com/mirged/maylang/issues/13)  
**Relevant paths:** `toolchain/maylsp/src/features.may`, `toolchain/maylsp/main.may`

The server caches full tokens but does not advertise token deltas.

- [ ] Negotiate full/delta support and maintain per-document result IDs.
- [ ] Compute token edits against the client's prior result.
- [ ] Fall back to full responses for unknown or invalidated IDs.
- [ ] Test insertions, deletions, Unicode and close/reopen behavior.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 14. Make expensive LSP navigation cancellable and responsive

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #14](https://github.com/mirged/maylang/issues/14)  
**Relevant paths:** `toolchain/maylsp/src/index.may`, `toolchain/maylsp/src/features.may`, `toolchain/maylsp/src/scheduler.may`

Navigation runs serially, and cancellation does not affect already-running navigation requests.

- [ ] Benchmark references, rename and symbols near indexing limits.
- [ ] Introduce bounded scheduling or workers for expensive navigation.
- [ ] Honor cancellation and discard results invalidated by edits.
- [ ] Test edits and hover interleaved with large navigation requests.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 5. Sustainable runtime and library contracts

Define portable memory behavior, document public APIs and keep learning material reproducible.

### Initiative 8. Define bounded memory management for the core runtime

**Status:** in progress
**Initial priority:** P2  
**GitHub:** [Issue #8](https://github.com/mirged/maylang/issues/8)  
**Relevant paths:** `toolchain/mayc/runtime/core.may`, `toolchain/mayc/runtime/corelib.may`

Core allocation retains chunks until process exit and has no individual free operation.

- [ ] Measure allocation growth in a long-running core workload.
- [ ] Specify an arena/reset or collector design with clear lifetime rules.
- [ ] Implement the selected API across core targets.
- [ ] Test repeated reclamation and document ownership and restrictions.

PR #21 caps process-lifetime core allocation at 256 MiB and verifies exhaustion on every emitted target. Reclamation, arena/reset APIs and their lifetime rules remain pending.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 19. Document stdlib API contracts and add runtime-mode conformance tests

**Status:** in progress
**Initial priority:** P2  
**GitHub:** [Issue #19](https://github.com/mirged/maylang/issues/19)  
**Relevant paths:** `stdlib/README.md`, `stdlib/`, `toolchain/mayc/tests/`

Standard-library edge cases and runtime/platform requirements need an explicit tested contract.

- [ ] Inventory public APIs and mark core/full/platform restrictions.
- [ ] Document types, errors, mutation and Unicode/numeric semantics.
- [ ] Test boundaries for collections, strings, paths and numeric operations.
- [ ] Distinguish experimental ML APIs and link examples to runnable tests.

PR #21 gives Result and I/O helpers concrete generic contracts and checks numeric, array, binary-file and process boundaries on native/LLVM output. A complete public API inventory and cross-runtime library contract suite remain pending.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 20. Make the interactive guide reproducible and validate documentation examples

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #20](https://github.com/mirged/maylang/issues/20)  
**Relevant paths:** `guide/package.json`, `guide/package-lock.json`, `docs/STRICT.md`, `docs/GRAMMAR.md`, `toolchain/maylsp/docs/generate.py`

The guide declares latest dependency versions and language examples are distributed across several references.

- [ ] Replace latest declarations with an intentional version policy and updated lockfile.
- [ ] Run npm ci and production guide build in CI.
- [ ] Check runnable strict-language examples and mark historical syntax explicitly.
- [ ] Run reference generation with --check and document synchronized reference updates.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Future proposals

The roadmap is open to directions beyond these twenty issues. Proposals might address additional compiler hosts, language ergonomics, tooling interoperability or application needs, but become planned commitments only after discussion establishes scope, ownership and validation. Link accepted proposals here and place their initiatives in the appropriate milestone, or propose a new milestone with a clear outcome.

## Roadmap history

- 2026-10-10: Audited issue acceptance against PR #21; recorded completed compiler diagnostics, fuzzing, compatibility and project/editor work, with explicit remaining GC, release, memory and workflow scope.

- 2026-10-02: Converted the initial twenty-issue TODO into five outcome-based milestones, retained implementation checklists, and added a community process for revising priorities and scope.
