# Maylang

An experimental programming language with a self-hosted compiler, strict
checking by default, and direct native executable output.

[Releases](https://github.com/mirged/maylang/releases) ·
[Install](docs/INSTALL.md) · [Language guide](docs/STRICT.md) ·
[Reference](reference/README.md) · [Contribute](CONTRIBUTING.md) ·
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

The toolchain runs on **Linux x86-64**, including **x86-64 WSL 2** on Windows.
Release installation needs standard Linux utilities and no Python, Rust, or
C compiler. Download the Linux archive and matching `.sha256` file from
[Releases](https://github.com/mirged/maylang/releases). From this checkout:

```sh
sh toolchain/install.sh "$HOME/Downloads/maylang-linux-x86_64.tar.gz"
. "$HOME/.local/share/maylang/env.sh"
mayc --version
may new "$HOME/hello-maylang"
cd "$HOME/hello-maylang"
may run
may test
```

The [installation guide](docs/INSTALL.md) covers downloads with `gh`, WSL,
shell setup, upgrades, rollback, and the VS Code extension. Native macOS,
Windows, and ARM64 compiler hosts currently have no release bundle.

## Build from source

Install Rust, a C compiler available as `cc`, GNU Make, Python 3.10+, and
binutils on Linux x86-64. Then:

```sh
git clone https://github.com/mirged/maylang.git
cd maylang
make doctor
make setup
. "$PWD/build/dev/env.sh"
mayc examples/hello.may -o /tmp/maylang-hello
/tmp/maylang-hello
```

`make setup` rebuilds the compiler and creates a complete local toolchain with
`mayc`, `may`, `mayfmt`, `maypkg`, and `maylsp` in `build/dev/bin`. It prints a
shell command to enable them; it does not edit shell startup files. Rerun
`make build` after compiler or runtime changes.

For a compiler-only build, run `sh toolchain/rust/build.sh` and use
`toolchain/mayc/mayc_new`. See [development setup](docs/DEVELOPMENT.md) for
dependency profiles, editor configuration, and targeted checks.

## Work with a project

The [May workspace runner](toolchain/may/README.md) manages application,
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
can use `maypkg` or `may migrate`. The [formatter](toolchain/mayfmt/README.md)
also powers editor formatting.

For a desktop project, use `may new my-app --ui`. The
[native UI library](stdlib/ui/README.md) needs a C compiler, X11 development
headers, and DejaVu fonts; windows use X11/XWayland. The complete
[Mayboard task board](example_projects/apps/mayboard/README.md) supports a
preview without a display:

```sh
cd example_projects/apps/mayboard
may run -- --demo --snapshot /tmp/mayboard.png
```

## Language and targets

Maylang supports typed functions, structs, generics, pattern matching,
closures, modules, collections, JSON, file I/O, raw pointers, and C ABI calls.
Start with the [strict guide](docs/STRICT.md) and
[runnable examples](reference/EXAMPLES.md). The
[legacy tour](docs/LEGACY_TOUR.md) documents older syntax for `--legacy` mode.

The compiler emits native executables without an external assembler or linker.
Compiler **host** support and emitted **program targets** are separate:

| Program target | Format | Runtime |
| --- | --- | --- |
| `x86_64-linux` | ELF64 | Full, core, raw |
| `arm64-linux` | ELF64 | Core, raw |
| `riscv64-linux` | ELF64 (RV64IM) | Core, raw |
| `arm64-macos` | Mach-O | Core, raw; signing required |
| `x86_64-windows` | PE32+ | Core, raw |
| `clang-llvm` | LLVM IR / ELF64 | Experimental full runtime on Linux x86-64 |

Use `mayc --list-targets` for discovery and see the
[compiler guide](toolchain/mayc/README.md#cross-compilation) for feature limits.
LLVM output requires Clang and excludes fibers and FFI. Native Windows and
macOS program execution is covered by the [native target suite](docs/NATIVE_TARGETS.md).

## Find your way around

| Directory | Contents |
| --- | --- |
| [toolchain/](toolchain/README.md) | Compiler, workspace runner, formatter, LSP, legacy manager, browser, OS |
| [toolchain/distribution/](toolchain/distribution/README.md) | Release packaging, installers, environment migration |
| [scripts/](scripts/README.md) | Checkout setup, prerequisite checks, repository validation |
| [stdlib/](stdlib/README.md) | Standard library, UI and experimental ML modules |
| [examples/](examples/) | Small language examples |
| [example_projects/](example_projects/README.md) | Complete apps, games, simulations, and learning projects |
| [docs/](docs/README.md) | Setup, language, architecture, audit and release guides |
| [reference/](reference/README.md) | Generated language and library reference |
| [editors/vscode/](editors/vscode/README.md) | VS Code extension |
| [tests/compliance/](tests/compliance/README.md) | Runtime and language boundary regressions |

## Project status and contributions

This project was written mostly by multiple large language models, with human
direction, review, and testing. It is experimental; generated code and
documentation need the same scrutiny as other contributions.

The original sustained-allocation garbage collector report remains open as
[#2](https://github.com/mirged/maylang/issues/2). Core allocation has documented
lifetime and capacity limits. Consult the [compiler guide](toolchain/mayc/README.md)
and [library contracts](stdlib/CONTRACTS.md) before relying on a feature.

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, commit conventions, and issue
labels. The [audit](docs/AUDIT.md) records findings and validation; the
[roadmap](ROADMAP.md) links active work. Release identity lives in `RELEASE.json`
and `MAYC_VERSION` in [main.may](toolchain/mayc/main.may); see the
[changelog](CHANGELOG.md) and [release convention](docs/RELEASING.md).
