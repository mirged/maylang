# Development setup

Compiler development requires Linux x86-64, including x86-64 WSL 2 on Windows.
A compiler that emits Windows or macOS programs still runs on Linux.
For everyday installation, use the [one-line interactive installer](INSTALL.md).
The commands below are for contributors working on the compiler.

## Prerequisites

On Ubuntu/Debian:

```sh
sudo apt-get update
sudo apt-get install build-essential binutils python3 git
```

Install Rust through your preferred installation method; `cargo` and `rustc`
must be on `PATH`. Python 3.10+ is required for repository scripts; extracted
archive checks use Python 3.12+ for `tarfile` extraction filters. The source
bootstrap uses `CC` (or `cc`) and locked, offline Cargo builds.

```sh
make doctor
make setup
. "$HOME/.maylang/env.sh"
mayc --version
may help
```

`make setup` builds into ignored `build/dev/`, then opens the Maylang installer
to copy a complete toolchain into `~/.maylang` or your chosen independent
prefix. It offers shell integration and creates `bin/may-uninstall`.
For CI use `make setup INSTALL_ARGS='--yes --prefix=/tmp/maylang --no-modify-path'`.
Installed copies survive moving, cleaning or deleting the checkout.

For compiler development, explicitly enable the disposable checkout tools:

```sh
make build
. "$PWD/build/dev/env.sh"
```

This local environment sets `PATH`, `MAYC` and `MAYLANG_STDLIB`; its library
and runtime are copied into `build/dev`. It lasts only as long as that build
directory. Rerun `make build` after compiler/runtime changes; `make tools`
rebuilds the other tools with the selected compiler. Run `make install` to
refresh the independent installation from the current sources.

See the [Rust bootstrap](../../compiler/rust/README.md) and
[compiler guide](../../compiler/mayc/README.md) for compiler-only work.

## Optional dependency profiles

These checks report requirements without installing anything:

```sh
python3 scripts/doctor.py --profile test
python3 scripts/doctor.py --profile llvm
python3 scripts/doctor.py --profile ui
python3 scripts/doctor.py --profile browser
python3 scripts/doctor.py --profile editor
python3 scripts/doctor.py --profile package
```

| Profile | Extra requirements |
| --- | --- |
| Test | `readelf` from binutils |
| LLVM | Clang/LLVM; `sudo apt-get install clang llvm` |
| UI | `libx11-dev`, `libxi-dev`, `libxcursor-dev`, `libgl-dev`, `fonts-dejavu-core`; X11/XWayland and OpenGL 4.3 for Sokol windows |
| Browser | UI dependencies, libcurl and `libduktape.so.207` |
| Window testing | `xvfb`, `xauth`, `xdotool` |
| Editor | Node.js and npm; CI uses Node 22 |
| Package verification | Python 3.12+, base build and UI dependencies for extracted scaffold tests |
| Core emulation | Unicorn in a Python virtual environment; see compiler tests |

The LLVM profile checks the compiler selected by `CLANG` (default: `clang`).
Set `CLANG=clang-19` when using a versioned installation.

The [browser](../../platform/maybrowser/README.md) and [UI](../../stdlib/ui/README.md)
guides have full commands. Socket/window tests may skip when unavailable;
required integration modes turn those skips into failures.

## Editor setup

Install the released VSIX or run `make editor` for extension development.
Set `maylang.serverPath` in VS Code to the absolute checkout path
`/path/to/maylang/build/dev/bin/maylsp`, or source the environment before
launching an editor that inherits tools from `PATH`.

## Testing and packaging

`make help` lists commands. [CONTRIBUTING.md](../../CONTRIBUTING.md) maps changes
to checks. `make check` is quick; `make test` exercises the default suites.
`make test-all` also needs optional integrations.

```sh
make check
make test
make test-tools
make package BUNDLE=/tmp/maylang-dev.tar.gz
```

Packaging records commit and dirty state. Tagged release packaging requires a
clean checkout at the exact version tag. See [distribution](../../dist/README.md).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `mayc` or `maylsp` not found | Source the printed environment command; restart editors after changing PATH |
| Compiler source edits seem ineffective | Run `make build`; the launcher caches its binary |
| Runtime or stdlib missing | Keep sidecars with the compiler and source the environment file |
| Cargo offline dependency error | Inspect `Cargo.lock` and toolchain; keep `--locked` |
| X11 header/font/library missing | Run the matching doctor profile and install reported requirements |
| Check succeeds but app cannot run | Check host versus output target and runtime restrictions |
| Unclear Make target | Run `make help` or inspect it with `make -n TARGET` |
