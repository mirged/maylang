# Repository map

```text
compiler/    mayc (self-hosted compiler) and rust (source bootstrap, shared crates)
tools/       may, mayfmt, maylsp, maypkg and their shared formatter
stdlib/      public libraries and native UI
dist/        packaging, installers, update and migration scripts
tests/       cross-component suites: compliance, docs, ui
examples/    single-file examples and complete apps, games, simulations
docs/        guides, internals, design, history and generated reference
editors/     VS Code extension
scripts/     checkout setup, prerequisite and repository checks
frozen/      kept but unmaintained code for other targets and experiments
```

| Boundary | Purpose | Validation |
| --- | --- | --- |
| `compiler/mayc/` | Self-hosted frontend, IR, backends, formats and runtime sidecars | `make test-compiler test-compliance` |
| `compiler/rust/` | Source bootstrap and shared Rust crates | `make test-rust test-bootstrap` |
| `tools/may/` | Workspace graphs, processes and verified artifact cache | `make test-tools` |
| `tools/mayfmt/` | Shared command-line/editor formatter | `make test-tools` |
| `tools/maylsp/` | Active Maylang language server | `make test-tools` |
| `tools/maypkg/` | Legacy manager and shared filesystem/import helpers | `make test-tools` |
| `tools/shared/` | Formatter core shared by `may`, `mayfmt` and `maylsp` | `make test-tools` |
| `stdlib/` | Public libraries and UI | Compiler contracts and `make test-ui` |
| `dist/` | Packaging, installers and Bash migration; tests in `dist/tests/` | `make test-distribution package` |
| `tests/compliance/` | Legacy runtime/coercion and boundary regressions | `make test-compliance` |
| `tests/docs/` | Runnable documentation examples | `make test-docs` |
| `tests/ui/` | Native UI harness and demo for `stdlib/ui` | `make test-ui` |
| `examples/` | Small examples and complete apps/games/simulations | Compiler verification and component workflows |
| `docs/reference/` | Generated API/language documentation | `make check test-docs` |
| `editors/vscode/` | Extension, grammar and snippets | `make editor` |
| `scripts/` | Checkout setup, dependency and repository checks | `make test-distribution` |
| `frozen/` | Code moved out of the supported Linux x86-64 scope; see its [README](../frozen/README.md) | None: not built or tested |
| `.github/` | CI, contribution forms, PR template and labels | Repository checks and GitHub CI |

Component tests stay beside their implementation; `tests/` holds only suites
that span components. Directory depth was preserved where possible, so
relative imports between `compiler/` and `tools/` siblings use
`../../<group>/<component>/`.

## Path migration

The October 2026 re-layout replaced `toolchain/`, `example_projects/` and the top-level
`reference/`. Update scripts, editor settings and bookmarks as follows:

| Before | After |
| --- | --- |
| `toolchain/mayc/`, `toolchain/rust/` | `compiler/mayc/`, `compiler/rust/` |
| `toolchain/{may,mayfmt,maylsp,maypkg,shared}/` | `tools/…/` |
| `toolchain/{maybrowser,mayos}/` | `platform/…/`, now `frozen/platform/…/` |
| `toolchain/distribution/`, `toolchain/{install.sh,install.ps1,package.py,update.py}` | `dist/` |
| `toolchain/tests/` | `dist/tests/`; `documentation.py` is now `tests/docs/run.py` |
| `toolchain/mayui/` | `tests/ui/` |
| `example_projects/<group>/` | `examples/<group>/`, also inside release bundles |
| `reference/` | `docs/reference/` |
| `MAYLANG_UNIFIED_BEHAVIOR_DESIGN.md` | `docs/design/UNIFIED_BEHAVIOR.md` |
| `docs/*.md` | `docs/{guide,internals,design,history}/` |

Further extraction should follow tests and measured hotspots. The
[audit](AUDIT.md) tracks typed compiler state, shared tooling helpers, runtime
duplication and native dependency ownership as separate reviewable work.
