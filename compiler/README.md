# Maylang compiler

| Component | Purpose | Start here |
| --- | --- | --- |
| [mayc](mayc/README.md) | Self-hosted compiler, runtime sidecars, backends, formats and compiler tests | `mayc/main.may` + `mayc/src/` |
| [rust](rust/README.md) | Source-only bootstrap and shared Rust crates (CLI, checker, LSP) | `rust/crates/` |

Build the native compiler from source, then use the cached launcher:

```sh
sh compiler/rust/build.sh
compiler/mayc/mayc_new examples/hello.may -o /tmp/hello
```

Rerun the build after compiler changes, because the launcher caches its binary.
`make test-compiler test-compliance` verifies the compiler and
`make test-bootstrap` checks generation convergence.
