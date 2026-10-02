# Maylang project TODO

Twenty actionable issues based on the current checkout and documented limitations. All tasks begin open. P0 is foundational reliability/bootstrap work; P1 is the next practical milestone; P2 is a planned capability improvement. Priorities suggest ordering, not release commitments.

## Suggested delivery order

1. Maintain the Rust source-only bootstrap, repair GC reliability, and enforce compiler verification in CI.
2. Ship complete releases, verify native targets and improve frontend robustness and diagnostics.
3. Align editor installation and make package-manager builds dependable.
4. Expand portable memory management, LSP capabilities, stdlib contracts and documentation checks.

## Completion policy

- [ ] Keep this backlog and its GitHub issues synchronized.
- [ ] Attach a reproducer or measurement before treating an unconfirmed defect as established.
- [ ] Record relevant validation commands and results in the implementing PR.
- [ ] Update documentation when supported behavior changes.
- [ ] Close issues after acceptance criteria pass; explicitly track deferred work.

## 1. Keep legacy-rust up to date and bootstrap Maylang entirely from Rust source

**Priority:** P0  
**GitHub:** [Issue #1](https://github.com/mirged/maylang/issues/1)  
**Relevant paths:** `Cargo.toml`, `toolchain/legacy-rust/crates/`, `toolchain/mayc/main.may`, `README.md`

Rust is currently archived, while fresh clones depend on a tracked bootstrap binary. Maintain Rust as a supported source-only bootstrap path.

- [ ] Define the bootstrap language/runtime subset required by the current Maylang compiler.
- [ ] Maintain Rust lexer/parser/checker/backend compatibility with that subset and document intentional differences.
- [ ] Document cargo build --locked --release -p may_cli followed by compilation of successive self-hosted compiler stages.
- [ ] Add clean-clone CI that excludes all precompiled compiler binaries, builds Rust from source and verifies stage convergence and hello/strict cases.
- [ ] After the source-only path is reliable, remove the tracked bootstrap binary and provide optional release downloads.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 2. Fix full-runtime GC corruption under sustained allocation

**Priority:** P0  
**GitHub:** [Issue #2](https://github.com/mirged/maylang/issues/2)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/runtime.may`, `toolchain/mayc/tests/stress.may`

The compiler guide documents collector corruption under sustained workloads.

- [ ] Reduce the failure to a deterministic reproducer.
- [ ] Audit root scanning, block reuse, coalescing and closure/map/string lifetimes.
- [ ] Fix corruption and exercise repeated forced collections.
- [ ] Add regression coverage and update the limitation after the stress case passes.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 3. Add CI for compiler, compliance and self-hosting verification

**Priority:** P0  
**GitHub:** [Issue #3](https://github.com/mirged/maylang/issues/3)  
**Relevant paths:** `toolchain/mayc/tests/run.sh`, `tests/compliance/run.py`, `.github/workflows/`

Verification scripts exist, but this checkout has no GitHub workflow directory.

- [ ] Add Linux x86-64 CI with explicit Python/binutils requirements.
- [ ] Run compiler stage convergence and compliance checks on pull requests.
- [ ] Upload reports and failure logs and fail on verification errors.
- [ ] Separate required checks from optional emulator/performance jobs.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 4. Package reproducible releases with runtime sidecars

**Priority:** P1  
**GitHub:** [Issue #4](https://github.com/mirged/maylang/issues/4)  
**Relevant paths:** `toolchain/mayc/mayc_new`, `toolchain/mayc/README.md`, `toolchain/maylsp/Makefile`

The compiler requires runtime sidecars, so copying its executable alone is insufficient.

- [ ] Define a bundle layout for compiler, launcher, runtime, stdlib and LSP.
- [ ] Build from tagged source and record version/bootstrap provenance.
- [ ] Publish checksums and verify an extracted bundle outside the checkout.
- [ ] Document installation, PATH and upgrades with binaries distributed as release assets.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 5. Verify Mach-O output on native macOS runners

**Priority:** P1  
**GitHub:** [Issue #5](https://github.com/mirged/maylang/issues/5)  
**Relevant paths:** `toolchain/mayc/src/formats/macho.may`, `toolchain/mayc/tests/core_runtime.py`

The compiler guide says native macOS launches and signing are not yet verified.

- [ ] Cross-emit ARM64 Mach-O fixtures on the supported compiler host.
- [ ] Sign and execute fixtures on Apple Silicon.
- [ ] Check output, allocation, calls and exit behavior.
- [ ] Record tested macOS versions and automate native checks when runner access is available.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 6. Verify PE output on native Windows runners

**Priority:** P1  
**GitHub:** [Issue #6](https://github.com/mirged/maylang/issues/6)  
**Relevant paths:** `toolchain/mayc/src/formats/pe.may`, `toolchain/mayc/tests/core_runtime.py`

Windows execution is emulated; native loader behavior still needs validation.

- [ ] Cross-emit x86-64 PE fixtures for a Windows runner.
- [ ] Exercise kernel32 imports, allocation, output and exit status.
- [ ] Check loading and calling convention behavior with useful logs.
- [ ] Document tested Windows versions and automate the native checks.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 7. Publish and enforce a target/runtime feature compatibility matrix

**Priority:** P1  
**GitHub:** [Issue #7](https://github.com/mirged/maylang/issues/7)  
**Relevant paths:** `toolchain/mayc/README.md`, `toolchain/mayc/src/backend/`, `toolchain/mayc/tests/backends.py`

Supported features vary across targets and full/core/raw runtimes.

- [ ] Inventory supported targets, runtime modes and features in one matrix.
- [ ] Add pass/reject fixtures for documented capabilities.
- [ ] Ensure unsupported features fail before executable output is written.
- [ ] Keep CLI help, matrix and main README consistent.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 8. Define bounded memory management for the core runtime

**Priority:** P2  
**GitHub:** [Issue #8](https://github.com/mirged/maylang/issues/8)  
**Relevant paths:** `toolchain/mayc/runtime/core.may`, `toolchain/mayc/runtime/corelib.may`

Core allocation retains chunks until process exit and has no individual free operation.

- [ ] Measure allocation growth in a long-running core workload.
- [ ] Specify an arena/reset or collector design with clear lifetime rules.
- [ ] Implement the selected API across core targets.
- [ ] Test repeated reclamation and document ownership and restrictions.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 9. Add parser and import-expansion fuzzing with minimized regressions

**Priority:** P1  
**GitHub:** [Issue #9](https://github.com/mirged/maylang/issues/9)  
**Relevant paths:** `toolchain/mayc/src/lexer.may`, `toolchain/mayc/src/parser.may`, `tests/compliance/`

Malformed input coverage can be expanded systematically beyond handwritten cases.

- [ ] Add seeded mutation of tokens, Unicode, nesting and import graphs.
- [ ] Bound compile time/resources and distinguish rejection from crashes.
- [ ] Minimize failures and save reproducible seeds.
- [ ] Add reduced regressions and a bounded CI fuzz smoke run.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 10. Add structured compiler diagnostics with original imported source locations

**Priority:** P1  
**GitHub:** [Issue #10](https://github.com/mirged/maylang/issues/10)  
**Relevant paths:** `toolchain/mayc/main.may`, `toolchain/mayc/src/`, `toolchain/maylsp/src/diagnostics.may`

Automation and editors benefit from a stable diagnostic interface that preserves locations after import expansion.

- [ ] Specify diagnostic codes, severity, file and source ranges.
- [ ] Add a machine-readable CLI output mode.
- [ ] Test nested/selective imports and Unicode positions.
- [ ] Share or consume the representation in the LSP and document schema stability.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 11. Recover from frontend errors and report multiple diagnostics

**Priority:** P2  
**GitHub:** [Issue #11](https://github.com/mirged/maylang/issues/11)  
**Relevant paths:** `toolchain/mayc/src/parser.may`, `toolchain/mayc/src/strict.may`, `toolchain/maylsp/README.md`

The LSP guide says checking stops at the first syntax or semantic error in an import closure.

- [ ] Define parser synchronization and prevent misleading cascading errors.
- [ ] Collect independent semantic errors without generating failed programs.
- [ ] Return multiple stable diagnostics in the language server.
- [ ] Test multiple errors/files and recovery after edits.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 12. Implement workspace-wide pull diagnostics in maylsp

**Priority:** P2  
**GitHub:** [Issue #12](https://github.com/mirged/maylang/issues/12)  
**Relevant paths:** `toolchain/maylsp/main.may`, `toolchain/maylsp/src/scheduler.may`

Workspace-wide pull diagnostics are explicitly not advertised by the current server.

- [ ] Implement workspace/diagnostic negotiation and result identifiers.
- [ ] Cover unopened files with bounded scheduling and progress.
- [ ] Handle cancellation, deletion and unsaved imports without stale results.
- [ ] Add protocol tests for full, unchanged and cancelled reports.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 13. Implement semantic token delta responses in maylsp

**Priority:** P2  
**GitHub:** [Issue #13](https://github.com/mirged/maylang/issues/13)  
**Relevant paths:** `toolchain/maylsp/src/features.may`, `toolchain/maylsp/main.may`

The server caches full tokens but does not advertise token deltas.

- [ ] Negotiate full/delta support and maintain per-document result IDs.
- [ ] Compute token edits against the client's prior result.
- [ ] Fall back to full responses for unknown or invalidated IDs.
- [ ] Test insertions, deletions, Unicode and close/reopen behavior.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 14. Make expensive LSP navigation cancellable and responsive

**Priority:** P2  
**GitHub:** [Issue #14](https://github.com/mirged/maylang/issues/14)  
**Relevant paths:** `toolchain/maylsp/src/index.may`, `toolchain/maylsp/src/features.may`, `toolchain/maylsp/src/scheduler.may`

Navigation runs serially, and cancellation does not affect already-running navigation requests.

- [ ] Benchmark references, rename and symbols near indexing limits.
- [ ] Introduce bounded scheduling or workers for expensive navigation.
- [ ] Honor cancellation and discard results invalidated by edits.
- [ ] Test edits and hover interleaved with large navigation requests.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 15. Align VS Code metadata and server discovery with maylsp

**Priority:** P1  
**GitHub:** [Issue #15](https://github.com/mirged/maylang/issues/15)  
**Relevant paths:** `editors/vscode/package.json`, `editors/vscode/README.md`, `toolchain/maylsp/README.md`

The extension uses example.invalid repository metadata and defaults to maylang-lsp, while the documented build produces maylsp.

- [ ] Replace placeholder repository metadata with the real GitHub repository.
- [ ] Choose one installed server name and align build/release/extension defaults.
- [ ] Provide actionable missing-server errors and preserve serverPath overrides.
- [ ] Compile/package the extension and smoke-test the installed bundle.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 16. Make maypkg compiler selection explicit and fix invocation documentation

**Priority:** P1  
**GitHub:** [Issue #16](https://github.com/mirged/maylang/issues/16)  
**Relevant paths:** `toolchain/maypkg/src/commands.may`, `toolchain/maypkg/README.md`

The README describes maylang build, while implementation invokes mayc and the repository documents mayc_new.

- [ ] Add a compiler setting or MAYC override with a documented default.
- [ ] Use it consistently for native and generated-script build/run/dev.
- [ ] Align README and help text with actual commands.
- [ ] Test spaces in paths, missing compilers and failed compilations.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 17. Include compiler, target and configuration in maypkg build fingerprints

**Priority:** P1  
**GitHub:** [Issue #17](https://github.com/mirged/maylang/issues/17)  
**Relevant paths:** `toolchain/maypkg/src/project.may`, `toolchain/maypkg/src/checksum.may`, `toolchain/maypkg/src/commands.may`

Source digests support incremental builds; audit freshness so toolchain/configuration changes cannot reuse stale outputs.

- [ ] Include compiler identity, target, runtime, options and manifest settings.
- [ ] Include resolved dependencies/stdlib and detect missing executables.
- [ ] Write successful build state atomically only after compilation succeeds.
- [ ] Test toolchain changes, target changes, failed builds and dependency edits.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 18. Add isolated end-to-end tests for maypkg commands

**Priority:** P1  
**GitHub:** [Issue #18](https://github.com/mirged/maylang/issues/18)  
**Relevant paths:** `toolchain/maypkg/main.may`, `toolchain/maypkg/src/`, `toolchain/maypkg/README.md`

Discovery, shell generation, watching and cleanup need a focused reproducible integration suite.

- [ ] Create temporary fixture projects for new/init/sync/tree/lock/verify/build/run.
- [ ] Cover imports, cycles, orphans, ancestor discovery and paths with spaces.
- [ ] Test watcher rebuilds and shutdown with bounded subprocess timeouts.
- [ ] Verify clean/dry-run only affect generated artifacts and document one test command.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 19. Document stdlib API contracts and add runtime-mode conformance tests

**Priority:** P2  
**GitHub:** [Issue #19](https://github.com/mirged/maylang/issues/19)  
**Relevant paths:** `stdlib/README.md`, `stdlib/`, `toolchain/mayc/tests/`

Standard-library edge cases and runtime/platform requirements need an explicit tested contract.

- [ ] Inventory public APIs and mark core/full/platform restrictions.
- [ ] Document types, errors, mutation and Unicode/numeric semantics.
- [ ] Test boundaries for collections, strings, paths and numeric operations.
- [ ] Distinguish experimental ML APIs and link examples to runnable tests.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

## 20. Make the interactive guide reproducible and validate documentation examples

**Priority:** P2  
**GitHub:** [Issue #20](https://github.com/mirged/maylang/issues/20)  
**Relevant paths:** `guide/package.json`, `guide/package-lock.json`, `docs/STRICT.md`, `docs/GRAMMAR.md`, `toolchain/maylsp/docs/generate.py`

The guide declares latest dependency versions and language examples are distributed across several references.

- [ ] Replace latest declarations with an intentional version policy and updated lockfile.
- [ ] Run npm ci and production guide build in CI.
- [ ] Check runnable strict-language examples and mark historical syntax explicitly.
- [ ] Run reference generation with --check and document synchronized reference updates.

**Done when:** the acceptance checklist passes with validation recorded in the linked issue or PR.

