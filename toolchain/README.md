# Maylang toolchain

The active compiler, editor server, package manager, and operating-system
project live here. Each component keeps its own tests and build files.

| Component | Purpose | Start here |
| --- | --- | --- |
| [Rust bootstrap](bootstrap/README.md) | Minimal source-only Maylang → C compiler for bootstrapping mayc | `bootstrap/src/main.rs` |
| [mayc](mayc/README.md) | Self-hosted compiler, runtime, bootstrap stages, and compiler tests | `mayc/main.may` + `mayc/src/` |
| [maylsp](maylsp/README.md) | Native language server and editor features | `maylsp/main.may` + `maylsp/src/` |
| [maypkg](maypkg/README.md) | Project discovery, dependency checks, lock files, and build scripts | `maypkg/main.may` + `maypkg/src/` |
| [mayos](mayos/README.md) | Bootable Maylang OS and kernel development example | `mayos/main.may`, `src/`, and `boot/` |
| [legacy Rust](legacy-rust/) | Historical compiler, parser, checker, and LSP crates (non-supported) | `legacy-rust/crates/` |

## Build the core tools

From the repository root:

```sh
toolchain/mayc/mayc_new examples/hello.may -o /tmp/hello
make -C toolchain/maylsp build
```

Run compiler verification with `toolchain/mayc/tests/run.sh`; use
`make -C toolchain/maylsp test` for the language server. MayOS build and test
requirements are documented in its README.
