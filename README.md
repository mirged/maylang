# Maylang

An experimental programming language with a self-hosted compiler, strict
checking by default, and direct native executable output.

> **Status:** experimental and not production-ready. Linux x86-64 only. Expect
> breaking changes between releases; see the [roadmap](ROADMAP.md) and the
> [security policy](SECURITY.md).

[![Maylang 0.15.0 — Fern](https://img.shields.io/badge/Maylang-0.15.0%20Fern-green)](https://github.com/mirged/maylang/releases/tag/v0.15.0)

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
independently of any source checkout. Maylang currently supports only
Linux x86-64 (including WSL 2).

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
commands receive literal argument arrays. `may migrate` converts an older
`mayproj.json` project. The [formatter](tools/mayfmt/README.md)
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
[runnable examples](docs/reference/EXAMPLES.md).

The compiler emits native x86-64 Linux ELF executables itself, with no
assembler, linker or LLVM. Programs use the full runtime (garbage
collector, files, processes, sockets, C calls) or, with `--raw`, compile to
plain machine words with no runtime.

For now Linux x86-64 is the only supported host and target
([why](docs/design/LINUX_X86_64_FOCUS.md)). The earlier ARM64, RISC-V, macOS,
Windows and NodeOS targets, the portable core runtime and the platform
experiments were removed from `main`; their last versions are in the
[`frozen-archive`](https://github.com/mirged/maylang/tree/frozen-archive) tag.

## Find your way around

| Directory | Contents |
| --- | --- |
| [compiler/](compiler/README.md) | Self-hosted `mayc` compiler and the Rust source bootstrap |
| [tools/](tools/README.md) | Workspace runner, formatter and language server |
| [stdlib/](stdlib/README.md) | Standard library and native UI |
| [dist/](dist/README.md) | Release packaging, installers, environment migration |
| [tests/](tests/README.md) | Cross-component compliance, documentation and UI suites |
| [examples/](examples/README.md) | Small language examples plus complete apps, games and simulations |
| [docs/](docs/README.md) | Guides, internals, design notes and the generated [reference](docs/reference/README.md) |
| [editors/vscode/](editors/vscode/README.md) | VS Code extension |
| [scripts/](scripts/README.md) | Checkout setup, prerequisite checks, repository validation |

The [repository map](docs/REPOSITORY.md) lists component boundaries, their
checks, and where paths from the earlier `toolchain/` layout moved.

## Project status and contributions

This project was written mostly by multiple large language models, with human
direction, review, and testing. It is experimental; generated code and
documentation need the same scrutiny as other contributions.

The full runtime's collector is conservative and has documented capacity
limits; the old sustained-allocation report
[#2](https://github.com/mirged/maylang/issues/2) is closed and does not
reproduce on the current runtime. Consult the [compiler guide](compiler/mayc/README.md)
and [library contracts](stdlib/CONTRACTS.md) before relying on a feature.

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, commit conventions, and issue
labels. The [roadmap](ROADMAP.md) links active work. Release identity lives in `RELEASE.json`
and `MAYC_VERSION` in [main.may](compiler/mayc/main.may); see the
[changelog](CHANGELOG.md) and [release convention](docs/guide/RELEASING.md).

## License

Maylang is released under the [MIT License](LICENSE). The same license covers
the compiler, tools, standard library, examples, native adapters and the
[VS Code extension](editors/vscode/README.md). Vendored third-party sources
keep their own licenses; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
lists them and reproduces the required notices. Contributions are accepted
under the MIT License.

