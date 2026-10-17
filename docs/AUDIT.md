# Repository audit — 2026-10-14

This audit starts at commit `ba78973`. It covers the tracked repository inventory,
component boundaries, build/install/release flows, GitHub history and CI,
compiler/runtime hotspots, project processes and cache keys, language-server
transport and scheduling, native adapters, library contracts, editor integration,
examples and tests. Findings distinguish source inspection from reproduction.
This is a repository-wide engineering audit, not a claim of exhaustive formal
verification of every code path or third-party header.

The initial inventory contains 606 tracked files: 293 toolchain files, 95 example
project files, 86 compliance files, 38 reference files, 35 library files, 21 small
examples, 13 editor files, 12 docs and 4 workflows, plus root metadata.
Existing issues #1–#35 and recent PR/CI/release history were inspected to avoid
refiling completed work. The sustained GC report remains tracked in #2.

## Implemented restructuring

- Group release packaging, installers and migration in `dist`, with compatibility launchers at the existing paths.
- Provide root Make commands, read-only prerequisite profiles, and a complete checkout-local five-tool setup with sidecars and a sourceable environment.
- Separate release installation, source development, contribution conventions, repository navigation, active roadmap and historical work.
- Add repository-wide local Markdown link/JSON/Python syntax checks and fast CI for repository/distribution contracts.
- Add issue forms, a PR template and a versioned catalog of existing GitHub labels.
- Correct broken legacy-guide links and list the workspace runner and formatter in the toolchain overview.

## Review coverage

| Component | Review focus | Evidence / follow-up |
| --- | --- | --- |
| Self-hosted compiler | Source allocation/reading, import expansion, frontend state, target/runtime contracts | Reproduced truncation; source-validated buffer/arena gaps; native/LLVM regressions |
| Runtime and bootstrap | GC history, source generation, builtin copies, core lifetime limits | Existing GC #2 retained; convergence and runtime tests; parity follow-up |
| Workspace and legacy tooling | Executable discovery, process shutdown, cache keys and dependency ownership | Reproduced PATH/cache/shutdown defects; workspace and legacy workflow tests |
| LSP and editor | Framing/limits, workers, cancellation, discovery and extension lifecycle | Existing LSP protocol suite and extension compile; extension-host coverage follow-up |
| Distribution | Archive validation, sidecars, provenance, migration, standalone installers | Reproduced link escape; installer/migration/provenance tests and real bundle |
| Browser and native UI | Fetching, font/image boundaries, ABI declarations, vendor copies | Source inspection; resource/cancellation/sanitizer/provenance issues |
| Libraries | Generated API inventory, runtime/platform contracts, ML implementation and coverage | 485 declarations checked; contracts/docs tests; independent ML oracle follow-up |
| Examples and MayOS | Entrypoint discovery, project recipes, OS prerequisites and QEMU coverage | Compiler example/project verification; MayOS reviewed but not booted locally |
| Repository and GitHub | Contribution paths, Markdown links, labels, history, workflows, releases | New repository check/forms/templates/catalog; no duplicate of resolved issue work |

## Open findings

Twenty-one new issues were filed. Each carries type, priority, area and status
labels, evidence, scope and acceptance criteria. Five failures were reproduced:
source truncation, environment-insensitive native cache reuse, PATH shadowing,
unbounded child shutdown, and installer symlink permission changes. Memory bounds
findings from inspection are labeled for triage, not presented as crash repros.
The existing sustained-GC issue [#2](https://github.com/mirged/maylang/issues/2)
was labeled and retained instead of duplicated.

| Issue | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| [#37](https://github.com/mirged/maylang/issues/37) | P1 | fix(compiler): reject or fully read source files above 1 MiB | Reproduced |
| [#38](https://github.com/mirged/maylang/issues/38) | P1 | fix(compiler): enforce import expansion buffer capacity | Source inspection / proposal |
| [#39](https://github.com/mirged/maylang/issues/39) | P1 | fix(compiler): bound source arena allocation and handle mmap failure | Source inspection / proposal |
| [#40](https://github.com/mirged/maylang/issues/40) | P1 | fix(may): include declared environment inputs in native cache identity | Reproduced |
| [#41](https://github.com/mirged/maylang/issues/41) | P2 | fix(may): skip non-executable entries during PATH lookup | Reproduced |
| [#42](https://github.com/mirged/maylang/issues/42) | P1 | fix(may): bound child shutdown and escalate after SIGTERM | Reproduced |
| [#43](https://github.com/mirged/maylang/issues/43) | P1 | fix(distribution): reject archive links that escape the toolchain bundle | Reproduced |
| [#44](https://github.com/mirged/maylang/issues/44) | P1 | feat(maybrowser): enforce network and decoded-image resource budgets | Source inspection / proposal |
| [#45](https://github.com/mirged/maylang/issues/45) | P2 | feat(maybrowser): keep navigation cancellable during network requests | Source inspection / proposal |
| [#46](https://github.com/mirged/maylang/issues/46) | P2 | refactor(maybrowser): compile the curl adapter against official headers | Source inspection / proposal |
| [#47](https://github.com/mirged/maylang/issues/47) | P2 | test(native): run malformed-input adapter tests with sanitizers | Source inspection / proposal |
| [#48](https://github.com/mirged/maylang/issues/48) | P2 | refactor(native): track shared vendored headers and upstream provenance | Source inspection / proposal |
| [#49](https://github.com/mirged/maylang/issues/49) | P2 | refactor(compiler): replace ambient frontend globals with typed context | Source inspection / proposal |
| [#50](https://github.com/mirged/maylang/issues/50) | P2 | refactor(tooling): extract shared filesystem and import helpers from maypkg | Source inspection / proposal |
| [#51](https://github.com/mirged/maylang/issues/51) | P2 | test(runtime): enforce prelude parity across bootstrap and self-hosted tools | Source inspection / proposal |
| [#52](https://github.com/mirged/maylang/issues/52) | P2 | test(vscode): cover language server lifecycle and configuration changes | Source inspection / proposal |
| [#53](https://github.com/mirged/maylang/issues/53) | P2 | test(mayos): exercise deterministic boot and disk persistence in CI | Source inspection / proposal |
| [#54](https://github.com/mirged/maylang/issues/54) | P2 | docs: clarify repository license scope and third-party notices | Source inspection / proposal |
| [#55](https://github.com/mirged/maylang/issues/55) | P2 | feat(bootstrap): define a roadmap for native ARM64 and desktop compiler hosts | Source inspection / proposal |
| [#56](https://github.com/mirged/maylang/issues/56) | P2 | feat(may): record native host toolchain identity for reproducible recipes | Source inspection / proposal |
| [#57](https://github.com/mirged/maylang/issues/57) | P2 | test(stdlib): add independent numerical oracles for experimental ML APIs | Source inspection / proposal |

## Validation of this restructure

- A real archive install into a temporary path with spaces/apostrophes passed shell setup and `may new/run/test/fmt --check`.
- `make setup`: rebuilt the source compiler and all five developer tools, preserving runtime sidecars.
- `make test`: passed repository/reference checks, Rust workspace tests, compiler verification, all 69 compliance cases, 25 runnable documentation examples, and isolated distribution/developer checks.
- `make test-tools`: passed workspace, formatter, legacy manager and LSP integration checks.
- `make test-bootstrap test-llvm`: passed source generation convergence and LLVM/reachability checks.
- `make editor`: locked npm installation and TypeScript compilation passed.
- `make test-ui test-browser` with temporary X11 development dependencies: UI model/headless checks and all four browser groups passed, including real local HTTP. Live window input was skipped because no X11 test display/tools were available.
- Real archive packaging succeeded; the first extracted installation test passed core compiler/CLI/formatter/LSP checks, then correctly failed building its UI scaffold because this host lacked X11 development headers. A second run using development headers/libraries extracted under `/tmp` passed every extracted check, including the UI scaffold, bundled Mayboard model tests and PNG rendering. No system packages were installed.

The pre-change GitHub bootstrap run for `ba78973` also passed after the previous
commit's documentation failures. The new PR's own CI is separate evidence.
No collector correctness guarantee, additional native compiler host, browser
security certification, or MayOS boot validation is implied by these checks.

Developer checks also cover failure preservation, shell metacharacters and repeated
environment sourcing. Workflow and issue-form YAML parsed successfully.
