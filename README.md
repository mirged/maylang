# Maylang

An experimental programming language with a self-hosted compiler, strict
checking by default, and direct native executable output.

[![Maylang 0.14.0 — Elm](https://img.shields.io/badge/Maylang-0.14.0%20Elm-green)](https://github.com/mirged/maylang/releases/tag/v0.14.0)

[Releases](https://github.com/mirged/maylang/releases) ·
[Install](docs/guide/INSTALL.md) · [Language guide](docs/guide/STRICT.md) ·
[Reference](docs/reference/README.md) · [Contribute](CONTRIBUTING.md) ·
[Roadmap](ROADMAP.md)

```may
fun double(value: Int) -> Int {
    return value * 2;
}

print(double(21)); // 42
```

`may { … } otherwise { … }` provides a recovery path for operations that can
fail. The compiler and active language server are written in Maylang. The
Rust workspace bootstraps the compiler from source.

## Install and run your first project

Run this in a **Linux x86-64** terminal, including **x86-64 WSL 2**:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/mirged/maylang/releases/latest/download/maylang-init.sh | sh
```

Press **Enter** for the recommended setup, or choose **Customize setup** to
pick a folder, individual tools and shell integration. Use **↑ ↓** to move,
**Space** to toggle tools, and **Esc** to go back. The installer shows progress
and checks the copied compiler before finishing. No checkout, Rust, Python,
C compiler or build command is needed.


Open a new terminal, then create your first project:

```sh
may new hello
cd hello
may run
```

The installer prints the activation command for your current terminal too.
[Installation options](docs/guide/INSTALL.md) cover unattended setup, plain menus,
updates, uninstall and offline downloads. Your tools live in `~/.maylang`,
independently of any source checkout. Compiler hosts are Linux x86-64;
native macOS, Windows and ARM64 host bundles are not available yet.

## Compiler development

Contributors can bootstrap directly from source on Linux x86-64:

```sh
sh compiler/rust/build.sh
python3 scripts/build_tools.py
```

See [development setup](docs/guide/DEVELOPMENT.md) for contributor prerequisites,
checkout-local tools and tests. To install Maylang for everyday use, use the
one-line installer above.

## Work with a project

The [May workspace runner](tools/may/README.md) manages application,
test, native build, and task targets in `may.json`:

```sh
may new my-project
cd my-project
may run
may check --all
may test
may fmt --check
may dev
```

Local dependencies have content pins, builds verify cached artifacts, and
commands receive literal argument arrays. Existing `mayproj.json` projects
can use `maypkg` or `may migrate`. The [formatter](tools/mayfmt/README.md)
also powers editor formatting.

For a desktop project, use `may new my-app --ui`. The
[native UI library](stdlib/ui/README.md) uses Sokol and needs a C compiler,
X11/Xi/Xcursor/OpenGL development libraries, and DejaVu fonts; windows use
X11/XWayland and OpenGL 4.3. The complete
[Mayboard task board](examples/apps/mayboard/README.md) supports a
preview without a display:

```sh
cd examples/apps/mayboard
may run -- --demo --snapshot /tmp/mayboard.png
```

The [May NES emulator](examples/apps/maynes/README.md) is a playable
native app with a GPU framebuffer, sound, ROM loading and persistent save states.
Run `may run` from `examples/apps/maynes`; an original homebrew game is
included.

## Language and targets

Maylang supports typed functions, structs, generics, pattern matching,
closures, modules, collections, JSON, file I/O, raw pointers, and C ABI calls.
Start with the [strict guide](docs/guide/STRICT.md) and
[runnable examples](docs/reference/EXAMPLES.md). The
[legacy tour](docs/history/LEGACY_TOUR.md) documents older syntax for `--legacy` mode.

The compiler emits native executables without an external assembler or linker.
Compiler **host** support and emitted **program targets** are separate:

| Program target | Format | Runtime |
| --- | --- | --- |
| `x86_64-linux` | ELF64 | Full, core, raw |
| `x86_64-nodeos` | NXF | Full, core, raw; the compiler also runs on NodeOS |
| `arm64-linux` | ELF64 | Core, raw |
| `riscv64-linux` | ELF64 (RV64IM) | Core, raw |
| `arm64-macos` | Mach-O | Core, raw; signing required |
| `x86_64-windows` | PE32+ | Core, raw |

Use `mayc --list-targets` for discovery and see the
[compiler guide](compiler/mayc/README.md#cross-compilation) for feature limits.
mayc writes these executables itself, with no assembler, linker or LLVM. Native Windows and
macOS program execution is covered by the [native target suite](docs/internals/NATIVE_TARGETS.md).
[NodeOS](docs/internals/NODEOS.md), a capability microkernel, runs Maylang
programs and the compiler itself, which rebuilds itself there byte-identically.

## Find your way around

| Directory | Contents |
| --- | --- |
| [compiler/](compiler/README.md) | Self-hosted `mayc` compiler and the Rust source bootstrap |
| [tools/](tools/README.md) | Workspace runner, formatter, language server, legacy package manager |
| [platform/](platform/README.md) | Browser and operating-system experiments |
| [stdlib/](stdlib/README.md) | Standard library, UI and experimental ML modules |
| [dist/](dist/README.md) | Release packaging, installers, environment migration |
| [tests/](tests/README.md) | Cross-component compliance, documentation and UI suites |
| [examples/](examples/README.md) | Small language examples plus complete apps, games and simulations |
| [docs/](docs/README.md) | Guides, internals, design notes, history and the generated [reference](docs/reference/README.md) |
| [editors/vscode/](editors/vscode/README.md) | VS Code extension |
| [scripts/](scripts/README.md) | Checkout setup, prerequisite checks, repository validation |

The [repository map](docs/REPOSITORY.md) lists component boundaries, their
checks, and where paths from the earlier `toolchain/` layout moved.

## Project status and contributions

This project was written mostly by multiple large language models, with human
direction, review, and testing. It is experimental; generated code and
documentation need the same scrutiny as other contributions.

The original sustained-allocation garbage collector report remains open as
[#2](https://github.com/mirged/maylang/issues/2). Core allocation has documented
lifetime and capacity limits. Consult the [compiler guide](compiler/mayc/README.md)
and [library contracts](stdlib/CONTRACTS.md) before relying on a feature.

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, commit conventions, and issue
labels. The [audit](docs/AUDIT.md) records findings and validation; the
[roadmap](ROADMAP.md) links active work. Release identity lives in `RELEASE.json`
and `MAYC_VERSION` in [main.may](compiler/mayc/main.may); see the
[changelog](CHANGELOG.md) and [release convention](docs/guide/RELEASING.md).
