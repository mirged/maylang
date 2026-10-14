# Maylang toolchain

The active compiler, editor server, package manager, and operating-system
project live here. Each component keeps its own tests and build files.

| Component | Purpose | Start here |
| --- | --- | --- |
| [Rust workspace](rust/README.md) | Shared Rust compiler crates, LSP, and source-only bootstrap | `rust/crates/` |
| [mayc](mayc/README.md) | Self-hosted compiler, runtime, bootstrap stages, and compiler tests | `mayc/main.may` + `mayc/src/` |
| [may](may/README.md) | Workspace runner, explicit targets and verified build cache | `may/main.may` + `may/src/` |
| [mayfmt](mayfmt/README.md) | Shared CLI and editor formatter | `mayfmt/main.may` |
| [maylsp](maylsp/README.md) | Native language server and editor features | `maylsp/main.may` + `maylsp/src/` |
| [maypkg](maypkg/README.md) | Project discovery, dependency checks, lock files, and build scripts | `maypkg/main.may` + `maypkg/src/` |
| [maybrowser](maybrowser/README.md) | Graphical browser, HTML/CSS engine, JavaScript, and PNG export | `maybrowser/main.may` + `maybrowser/src/` |
| [mayos](mayos/README.md) | Bootable Maylang OS and kernel development example | `mayos/main.may`, `src/`, and `boot/` |
| [distribution](distribution/README.md) | Packaging, release installation and legacy environment migration | `distribution/` |

## Install a release

Use `sh toolchain/install.sh /path/to/maylang-linux-x86_64.tar.gz` on Linux
x86-64, or `toolchain/install.ps1 -Bundle <archive>` from PowerShell on Windows
x86-64 with WSL 2. Keep the adjacent `.sha256` file beside the archive. No Python
is required. See the [installation guide](../docs/INSTALL.md).

## Build the core tools

From the repository root:

```sh
make setup
. "$PWD/build/dev/env.sh"
mayc examples/hello.may -o /tmp/hello
```

Run compiler verification with `toolchain/mayc/tests/run.sh`; use
`make -C toolchain/maylsp test` for the language server. MayOS build and test
requirements are documented in its README.

See [development setup](../docs/DEVELOPMENT.md) and [contributing](../CONTRIBUTING.md)
for prerequisite checks and targeted root Make commands. The top-level installer
and packaging paths remain compatibility entry points into `distribution/`.
