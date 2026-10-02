# Maylang roadmap

Maylang aims to become a dependable language and toolchain that contributors can build from source, use in real projects, and improve together. This roadmap connects that direction to concrete outcomes and the [GitHub issue tracker](https://github.com/mirged/maylang/issues).

This is a living plan. Community needs, reproducible failures, contributor availability and implementation discoveries can change the order, scope or design of any milestone. Milestones have completion criteria rather than fixed dates or promised release versions. Inclusion here means planned work, not a guarantee of delivery.

## Starting point

The current project has a self-hosted compiler running on Linux x86-64, several native output targets, a Maylang language server, a package manager, a standard library and example projects. The documented gaps include reliance on a checked-in bootstrap compiler, full-runtime GC corruption under sustained allocation, and native macOS/Windows execution that still needs verification. The linked issues capture the starting assumptions; verify them against current code before implementation.

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

All twenty initial initiatives are planned at the time this roadmap was created; no implementation is claimed here. Use these states when updating an initiative: **planned**, **in progress**, **blocked**, **completed**, **deferred** or **superseded**. Link the implementation PR when work starts and identify a concrete dependency when marking work blocked. Keep checkboxes aligned with verified results.

A milestone is ready when its agreed acceptance criteria pass and the relevant documentation reflects the delivered behavior. If its scope changes, record the decision before declaring it complete. Each implementation should include regression coverage appropriate to the change, validation commands and results, and any remaining limitations. Keep source-only builds and supported-target behavior covered as the compiler evolves.

## Detailed initiatives

The initial priorities are P0 for foundational reliability and bootstrapping, P1 for practical adoption work, and P2 for planned capability improvements. They are revisable planning signals. Paths and checklists below are starting points for implementation and community review.

## Milestone 1. Reliable foundations

Make source builds and runtime correctness trustworthy before broadening adoption.

### Initiative 1. Keep legacy-rust up to date and bootstrap Maylang entirely from Rust source

**Status:** planned  
**Initial priority:** P0  
**GitHub:** [Issue #1](https://github.com/mirged/maylang/issues/1)  
**Relevant paths:** `Cargo.toml`, `toolchain/legacy-rust/crates/`, `toolchain/mayc/main.may`, `README.md`

Rust is currently archived, while fresh clones depend on a tracked bootstrap binary. Maintain Rust as a supported source-only bootstrap path.

- [ ] Define the bootstrap language/runtime subset required by the current Maylang compiler.
- [ ] Maintain Rust lexer/parser/checker/backend compatibility with that subset and document intentional differences.
- [ ] Document cargo build --locked --release -p may_cli followed by compilation of successive self-hosted compiler stages.
- [ ] Add clean-clone CI that excludes all precompiled compiler binaries, builds Rust from source and verifies stage convergence and hello/strict cases.
- [ ] After the source-only path is reliable, remove the tracked bootstrap binary and provide optional release downloads.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 2. Fix full-runtime GC corruption under sustained allocation

**Status:** planned  
**Initial priority:** P0  
**GitHub:** [Issue #2](https://github.com/mirged/maylang/issues/2)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/runtime.may`, `toolchain/mayc/tests/stress.may`

The compiler guide documents collector corruption under sustained workloads.

- [ ] Reduce the failure to a deterministic reproducer.
- [ ] Audit root scanning, block reuse, coalescing and closure/map/string lifetimes.
- [ ] Fix corruption and exercise repeated forced collections.
- [ ] Add regression coverage and update the limitation after the stress case passes.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 3. Add CI for compiler, compliance and self-hosting verification

**Status:** planned  
**Initial priority:** P0  
**GitHub:** [Issue #3](https://github.com/mirged/maylang/issues/3)  
**Relevant paths:** `toolchain/mayc/tests/run.sh`, `tests/compliance/run.py`, `.github/workflows/`

Verification scripts exist, but this checkout has no GitHub workflow directory.

- [ ] Add Linux x86-64 CI with explicit Python/binutils requirements.
- [ ] Run compiler stage convergence and compliance checks on pull requests.
- [ ] Upload reports and failure logs and fail on verification errors.
- [ ] Separate required checks from optional emulator/performance jobs.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 9. Add parser and import-expansion fuzzing with minimized regressions

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #9](https://github.com/mirged/maylang/issues/9)  
**Relevant paths:** `toolchain/mayc/src/lexer.may`, `toolchain/mayc/src/parser.may`, `tests/compliance/`

Malformed input coverage can be expanded systematically beyond handwritten cases.

- [ ] Add seeded mutation of tokens, Unicode, nesting and import graphs.
- [ ] Bound compile time/resources and distinguish rejection from crashes.
- [ ] Minimize failures and save reproducible seeds.
- [ ] Add reduced regressions and a bounded CI fuzz smoke run.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 2. Installable, verified toolchain

Deliver complete installations and validate the platforms advertised to users. Cross-emission support and native compiler-host support remain separate capabilities; expanding compiler hosts needs its own proposal and acceptance criteria.

### Initiative 4. Package reproducible releases with runtime sidecars

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #4](https://github.com/mirged/maylang/issues/4)  
**Relevant paths:** `toolchain/mayc/mayc_new`, `toolchain/mayc/README.md`, `toolchain/maylsp/Makefile`

The compiler requires runtime sidecars, so copying its executable alone is insufficient.

- [ ] Define a bundle layout for compiler, launcher, runtime, stdlib and LSP.
- [ ] Build from tagged source and record version/bootstrap provenance.
- [ ] Publish checksums and verify an extracted bundle outside the checkout.
- [ ] Document installation, PATH and upgrades with binaries distributed as release assets.

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

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #7](https://github.com/mirged/maylang/issues/7)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/src/backend/`, `toolchain/mayc/tests/backends.py`

Supported features vary across targets and full/core/raw runtimes.

- [ ] Inventory supported targets, runtime modes and features in one matrix.
- [ ] Add pass/reject fixtures for documented capabilities.
- [ ] Ensure unsupported features fail before executable output is written.
- [ ] Keep CLI help, matrix and main README consistent.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 15. Align VS Code metadata and server discovery with maylsp

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #15](https://github.com/mirged/maylang/issues/15)  
**Relevant paths:** `editors/vscode/package.json`, `editors/vscode/README.md`, `toolchain/maylsp/README.md`

The extension uses example.invalid repository metadata and defaults to maylang-lsp, while the documented build produces maylsp.

- [ ] Replace placeholder repository metadata with the real GitHub repository.
- [ ] Choose one installed server name and align build/release/extension defaults.
- [ ] Provide actionable missing-server errors and preserve serverPath overrides.
- [ ] Compile/package the extension and smoke-test the installed bundle.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 3. Dependable project workflows

Make project discovery, builds and incremental development predictable for contributors and application authors.

### Initiative 16. Make maypkg compiler selection explicit and fix invocation documentation

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #16](https://github.com/mirged/maylang/issues/16)  
**Relevant paths:** `toolchain/maypkg/src/commands.may`, `toolchain/maypkg/README.md`

The README describes maylang build, while implementation invokes mayc and the repository documents mayc_new.

- [ ] Add a compiler setting or MAYC override with a documented default.
- [ ] Use it consistently for native and generated-script build/run/dev.
- [ ] Align README and help text with actual commands.
- [ ] Test spaces in paths, missing compilers and failed compilations.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 17. Include compiler, target and configuration in maypkg build fingerprints

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #17](https://github.com/mirged/maylang/issues/17)  
**Relevant paths:** `toolchain/maypkg/src/project.may`, `toolchain/maypkg/src/checksum.may`, `toolchain/maypkg/src/commands.may`

Source digests support incremental builds; audit freshness so toolchain/configuration changes cannot reuse stale outputs.

- [ ] Include compiler identity, target, runtime, options and manifest settings.
- [ ] Include resolved dependencies/stdlib and detect missing executables.
- [ ] Write successful build state atomically only after compilation succeeds.
- [ ] Test toolchain changes, target changes, failed builds and dependency edits.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 18. Add isolated end-to-end tests for maypkg commands

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #18](https://github.com/mirged/maylang/issues/18)  
**Relevant paths:** `toolchain/maypkg/main.may`, `toolchain/maypkg/src/`, `toolchain/maypkg/README.md`

Discovery, shell generation, watching and cleanup need a focused reproducible integration suite.

- [ ] Create temporary fixture projects for new/init/sync/tree/lock/verify/build/run.
- [ ] Cover imports, cycles, orphans, ancestor discovery and paths with spaces.
- [ ] Test watcher rebuilds and shutdown with bounded subprocess timeouts.
- [ ] Verify clean/dry-run only affect generated artifacts and document one test command.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## Milestone 4. Clear diagnostics and responsive editing

Improve how the compiler explains failures and how the editor behaves under real workspace load.

### Initiative 10. Add structured compiler diagnostics with original imported source locations

**Status:** planned  
**Initial priority:** P1  
**GitHub:** [Issue #10](https://github.com/mirged/maylang/issues/10)  
**Relevant paths:** `toolchain/mayc/main.may`, `toolchain/mayc/src/`, `toolchain/maylsp/src/diagnostics.may`

Automation and editors benefit from a stable diagnostic interface that preserves locations after import expansion.

- [ ] Specify diagnostic codes, severity, file and source ranges.
- [ ] Add a machine-readable CLI output mode.
- [ ] Test nested/selective imports and Unicode positions.
- [ ] Share or consume the representation in the LSP and document schema stability.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 11. Recover from frontend errors and report multiple diagnostics

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #11](https://github.com/mirged/maylang/issues/11)  
**Relevant paths:** `toolchain/mayc/src/parser.may`, `toolchain/mayc/src/strict.may`, `toolchain/maylsp/README.md`

The LSP guide says checking stops at the first syntax or semantic error in an import closure.

- [ ] Define parser synchronization and prevent misleading cascading errors.
- [ ] Collect independent semantic errors without generating failed programs.
- [ ] Return multiple stable diagnostics in the language server.
- [ ] Test multiple errors/files and recovery after edits.

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

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #8](https://github.com/mirged/maylang/issues/8)  
**Relevant paths:** `toolchain/mayc/runtime/core.may`, `toolchain/mayc/runtime/corelib.may`

Core allocation retains chunks until process exit and has no individual free operation.

- [ ] Measure allocation growth in a long-running core workload.
- [ ] Specify an arena/reset or collector design with clear lifetime rules.
- [ ] Implement the selected API across core targets.
- [ ] Test repeated reclamation and document ownership and restrictions.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

### Initiative 19. Document stdlib API contracts and add runtime-mode conformance tests

**Status:** planned  
**Initial priority:** P2  
**GitHub:** [Issue #19](https://github.com/mirged/maylang/issues/19)  
**Relevant paths:** `stdlib/README.md`, `stdlib/`, `toolchain/mayc/tests/`

Standard-library edge cases and runtime/platform requirements need an explicit tested contract.

- [ ] Inventory public APIs and mark core/full/platform restrictions.
- [ ] Document types, errors, mutation and Unicode/numeric semantics.
- [ ] Test boundaries for collections, strings, paths and numeric operations.
- [ ] Distinguish experimental ML APIs and link examples to runnable tests.

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

- 2026-10-02: Converted the initial twenty-issue TODO into five outcome-based milestones, retained implementation checklists, and added a community process for revising priorities and scope.
