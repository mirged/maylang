# Repository map

| Boundary | Purpose | Validation |
| --- | --- | --- |
| `toolchain/mayc/` | Self-hosted frontend, IR, backends, formats and runtime sidecars | `make test-compiler test-compliance` |
| `toolchain/rust/` | Source bootstrap and shared Rust crates | `make test-rust test-bootstrap` |
| `toolchain/may/` | Workspace graphs, processes and verified artifact cache | `make test-tools` |
| `toolchain/mayfmt/` | Shared command-line/editor formatter | `make test-tools` |
| `toolchain/maylsp/` | Active Maylang language server | `make test-tools` |
| `toolchain/maypkg/` | Legacy manager and shared filesystem/import helpers | `make test-tools` |
| `toolchain/distribution/` | Packaging, installers and Bash migration | `make test-distribution package` |
| `toolchain/maybrowser/` | Experimental browser and native adapter | `make test-browser` |
| `toolchain/mayos/` | OS/kernel experiment | Component Makefile and README |
| `stdlib/` | Public libraries, UI and experimental ML | Compiler contracts and `make test-ui` |
| `examples/`, `example_projects/` | Small examples and complete apps/games/simulations | Compiler verification and component workflows |
| `tests/compliance/` | Legacy runtime/coercion and boundary regressions | `make test-compliance` |
| `editors/vscode/` | Extension, grammar and snippets | `make editor` |
| `reference/` | Generated API/language documentation | `make check test-docs` |
| `scripts/` | Checkout setup, dependency and repository checks | `make test-distribution` |
| `.github/` | CI, contribution forms, PR template and labels | Repository checks and GitHub CI |

Keep components beside their tests. Public compiler/runtime paths stay stable:
import graphs, bootstraps, sidecars and editors consume them. The October 2026
restructuring moves distribution implementations behind compatibility entry
points, provides root developer commands, and separates active roadmap work
from completed history.

Further extraction should follow tests and measured hotspots. The
[audit](AUDIT.md) tracks typed compiler state, shared tooling helpers, runtime
duplication and native dependency ownership as separate reviewable work.
