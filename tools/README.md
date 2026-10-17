# Maylang toolchain

The active compiler, editor server, package manager, and operating-system
project live here. Each component keeps its own tests and build files.

| Component | Purpose | Start here |
| --- | --- | --- |
| [Rust workspace](../compiler/rust/README.md) | Shared Rust compiler crates, LSP, and source-only bootstrap | `rust/crates/` |
| [mayc](../compiler/mayc/README.md) | Self-hosted compiler, runtime, bootstrap stages, and compiler tests | `mayc/main.may` + `mayc/src/` |
| [may](may/README.md) | Workspace runner, explicit targets and verified build cache | `may/main.may` + `may/src/` |
| [mayfmt](mayfmt/README.md) | Shared CLI and editor formatter | `mayfmt/main.may` |
| [maylsp](maylsp/README.md) | Native language server and editor features | `maylsp/main.may` + `maylsp/src/` |
| [maypkg](maypkg/README.md) | Project discovery, dependency checks, lock files, and build scripts | `maypkg/main.may` + `maypkg/src/` |
| [maybrowser](../platform/maybrowser/README.md) | Graphical browser, HTML/CSS engine, JavaScript, and PNG export | `maybrowser/main.may` + `maybrowser/src/` |
| [mayos](../platform/mayos/README.md) | Bootable Maylang OS and kernel development example | `mayos/main.may`, `src/`, and `boot/` |
| [distribution](../dist/README.md) | Packaging, release installation and legacy environment migration | `distribution/` |

## Install a release

Use `sh dist/install.sh /path/to/maylang-linux-x86_64.tar.gz` on Linux
x86-64, or `dist/install.ps1 -Bundle <archive>` from PowerShell on Windows
x86-64 with WSL 2. Keep the adjacent `.sha256` file beside the archive. No Python
is required. See the [installation guide](../docs/guide/INSTALL.md).

## Build the core tools

From the repository root:

```sh
make setup
. "$HOME/.maylang/env.sh"
mayc examples/hello.may -o /tmp/hello
```

Run compiler verification with `compiler/mayc/tests/run.sh`; use
`make -C tools/maylsp test` for the language server. MayOS build and test
requirements are documented in its README.

See [development setup](../docs/guide/DEVELOPMENT.md) and [contributing](../CONTRIBUTING.md)
for prerequisite checks and targeted root Make commands. The top-level installer
and packaging paths remain compatibility entry points into `distribution/`.
