# Repository Guidelines

## Project Structure & Module Organization

`toolchain/mayc/` contains the active self-hosted compiler: `main.may`, frontend/IR modules in `src/`, architecture backends, executable formats, and runtime sidecars. `toolchain/rust/crates/` provides the source bootstrap and shared Rust components. `toolchain/maylsp/`, `maypkg/`, and `maybrowser/` contain developer tools with their own tests. Library modules live in `stdlib/`; sample programs in `examples/` and `example_projects/`. Use `docs/` for architecture documentation and `editors/vscode/` for extension code, grammars, and snippets. Browser HTML fixtures live in `toolchain/maybrowser/examples/`.

## Build, Test, and Development Commands

Run from the repository root. Compiler development requires Linux x86-64, Rust, GCC/Clang, Python 3, and binutils.

- `sh toolchain/rust/build.sh`: rebuild the native compiler from source; rerun after compiler changes because the launcher caches its binary.
- `toolchain/mayc/mayc_new examples/hello.may -o /tmp/hello`: compile a sample; run `/tmp/hello`.
- `toolchain/mayc/mayc_new --check examples/strict.may`: check without emitting code.
- `cargo test --offline --locked --workspace`: run Rust tests.
- `python3 toolchain/rust/test.py`: verify source bootstrap and compiler-generation convergence.
- `toolchain/mayc/tests/run.sh`: run native compiler verification and self-hosting checks.
- `python3 tests/compliance/run.py`: run language/runtime compliance cases.
- `make -C toolchain/maylsp test`: build and test LSP behavior.
- `make -C toolchain/maybrowser check test`: check and test the browser; see its README for native dependencies.
- `cd editors/vscode && npm ci && npm run compile`: compile the extension.

## Coding Style & Naming Conventions

Use four-space indentation for Maylang, Python, and Rust; two spaces for extension TypeScript. Follow adjacent code. Prefer `snake_case` functions/files, `PascalCase` types, and uppercase constants. Write typed Maylang signatures and explicit returns; strict checking is the default. Rust supports `cargo fmt --all`; no shared Maylang/Python formatter configuration is present.

## Testing Guidelines

Tests use Python subprocess/protocol harnesses and Cargo unit/integration tests. Add focused regressions covering success and failure paths. Place compiler fixtures under `toolchain/mayc/tests/`, including `fail/` for invalid programs; follow existing area-based script names such as `reachability.py` and `test_lsp.py`. For backend changes, also run `python3 toolchain/mayc/tests/llvm.py` and relevant core-target tests. No numeric coverage threshold is enforced.

## Commit & Pull Request Guidelines

Use focused commits following history: `feat(maylsp): ...`, `fix(compiler): ...`, `perf(codegen): ...`, `test(...): ...`, or `docs: ...`. PRs should explain the behavior change, link relevant issues, and report actual validation and limitations. Include screenshots for visual changes and measured reports for performance claims. Preserve unrelated working-tree edits; stage specific files and exclude generated binaries/build artifacts. Keep runtime sidecars with copied compiler executables.
