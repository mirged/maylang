# Contributing to Maylang

Use Linux x86-64 for compiler and toolchain development. Start with
[development setup](docs/guide/DEVELOPMENT.md), run `make doctor`, then `make setup`.
`make help` lists the supported repository commands.

## Repository boundaries

The [repository map](docs/REPOSITORY.md) describes component ownership.
Keep compiler work in `compiler/mayc`, shared Rust/bootstrap work in
`compiler/rust`, developer tools in `tools`, public libraries in `stdlib`, and
component tests beside their implementation. Distribution work and its tests
belong in `dist`; only suites spanning components go in `tests`. Checkout setup
and repository checks belong in `scripts`. Compiler sidecars must travel with
copied executables.

## Choose checks for the change

Run `make check` for every change. It checks local Markdown file links,
JSON/Python syntax, and generated reference freshness.

| Change | Validation |
| --- | --- |
| Compiler/frontend/runtime | `make test-rust test-compiler test-compliance` |
| Bootstrap | `make test-bootstrap` |
| Backend/code generation | `make test-llvm` and relevant core/native target harnesses |
| Workspace/formatter/legacy manager/LSP | `make test-tools` |
| Runnable docs | `make test-docs` |
| Installer/packaging/developer setup | `make test-distribution test-installer`; `make package` for extracted bundles and standalone bootstrap |
| Native UI | `make test-ui`; use the UI harness's `--require-x11` for required window checks |
| Browser | `make test-browser`; see its README for required network/window checks |
| VS Code extension | `make editor` |

`make test` runs the default Rust/compiler/compliance/docs/distribution checks.
`make test-all` includes optional native integrations and bootstrap convergence.
Pass `MAYC=/absolute/path/to/mayc` when testing a particular compiler. Build
before testing changed compiler sources: the launcher caches its binary.
Record skips and missing dependencies explicitly.

Add focused regressions for changed behavior, including failure paths.
Compiler fixtures belong under `compiler/mayc/tests`; invalid programs go in
`fail/`. Tests should verify observable contracts. Do not commit generated
executables, build directories, or machine-specific reports.

## Style and commits

Follow adjacent code. Use four spaces for Maylang, Python, and Rust, and two
for TypeScript. Prefer `snake_case` functions/files, `PascalCase` types, typed
Maylang signatures, and explicit returns. Rust formatting uses `cargo fmt --all`.

Use focused subjects such as `fix(compiler): ...`, `feat(maylsp): ...`,
`perf(codegen): ...`, `test(runtime): ...`, or `docs: ...`. Stage specific files,
preserve unrelated work, and tie performance claims to measured reports.

PR descriptions should state the problem and resulting behavior, link issues,
and report actual checks and limitations. Include screenshots for visual
changes. The [PR template](.github/pull_request_template.md) supplies a checklist.
Use draft PRs while required checks or design decisions remain open.

## Report bugs and propose work

Search [existing issues](https://github.com/mirged/maylang/issues?q=is%3Aissue)
first. Include a minimal program, compiler version, host, target/runtime,
command, actual output, and expected behavior. Separate reproduced defects,
findings from source inspection, and feature proposals.

The established GitHub label convention uses:

- One primary `type:*`: bug, feature, enhancement, refactor, docs, test, or performance.
- One `priority:*`: p0 for crashes/corruption, p1 for major defects, p2 for ordinary work, p3 for polish.
- Relevant `area:*` labels for affected components.
- One current `status:*`; use `needs-triage` initially and `confirmed` after reproduction or source validation.

Apply `help-wanted`, `good-first-issue`, `regression`, `compatibility`,
`breaking-change`, or `design:discussion` when applicable. Priority is a triage
decision, not a delivery commitment. Label descriptions are tracked in
[.github/labels.json](.github/labels.json).

Use `gh issue list`, `gh issue view`, and `gh pr list` to inspect context.
Write long bodies to a file and use `--body-file`:

```sh
gh issue create --title 'fix(component): concrete behavior' --body-file /tmp/issue.md \
  --label type:bug --label area:compiler --label status:needs-triage
gh pr create --draft --title 'docs: explain the changed workflow' --body-file /tmp/pr.md
```

Review and test generated code. Move public paths with migration support and
keep behavior changes separately reviewable from mechanical restructuring.
