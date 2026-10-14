# Install the Maylang toolchain

The compiler, project manager and language server currently run on Linux
x86-64. Building from source requires Rust, GCC or Clang, Python 3 and binutils.
LLVM output additionally requires Clang. The packaged tools need no Rust or C
compiler for normal direct native compilation. `may` needs the `sha256sum` command from coreutils. Native UI recipes additionally
need a C compiler, X11 development headers and a TrueType font. `maypkg` retains
its POSIX shell workflow for existing projects.

## Install or upgrade (no Python required)

### Interactive Maylang installer

From source, run `make setup` (or `make install`). The installer is written in
Maylang and prompts for an independent prefix, components and shell integration.
The default prefix is `~/.maylang`. It copies the entire runtime and standard
library, verifies compilation using the copied compiler, then selects the new
generation. Cleaning or deleting the checkout does not affect the installation.

```sh
make setup
. "$HOME/.maylang/env.sh"
mayc --version
```

For unattended setup, explicit locations and existing shell configurations:

```sh
make setup INSTALL_ARGS='--yes --prefix=/tmp/my-maylang --no-modify-path'
. /tmp/my-maylang/env.sh
```

The installed `bin/may-installer` also accepts `--bundle DIR`, `--prefix=DIR`,
`--components=compiler` or a comma-separated list of tools (`mayc` is always
included), `--profile=FILE`, `--yes`, and `--no-modify-path`. `--profile` chooses
a Bash, Zsh or POSIX shell startup file; otherwise `$SHELL` selects `.bashrc`,
`.zshrc` or `.profile`. Interactive installs ask before writing a managed PATH
block. `--yes` accepts the chosen settings; use `--no-modify-path` to leave
profiles untouched. Profiles with malformed managed blocks are rejected.

Each generation is a physical copy under the prefix's `releases/` directory.
The `current`, `bin` and `stdlib` symlinks stay entirely inside that prefix.
Reinstallation preserves older generations. Choose an empty prefix or one
managed by this installer; older shell-installed prefixes can be kept alongside
a new prefix rather than being overwritten.

Uninstall removes owned generations, environment files and only this prefix's
managed shell blocks. Unrelated files and settings remain. Repeating uninstall
through a saved installer is a safe no-op:

```sh
"$HOME/.maylang/bin/may-uninstall"
# Or: /path/to/may-installer --uninstall --yes --prefix="$HOME/.maylang"
```

### Self-contained C and shell bootstrap

New packages produce `maylang-bootstrap.c` and `maylang-install.sh`, plus
checksums. The single C file embeds a source-built native Maylang installer and
complete toolchain. Host `cc` and libc are sufficient to build it; running that
binary uses no Python, Rust, archive utilities, network requests or installed
Maylang compiler. It extracts into a private temporary directory and launches
the embedded Maylang program, whose own runtime is already compiled into it.
This is a native launcher, not a Maylang source interpreter or compiler.

```sh
cc -std=c11 -O2 maylang-bootstrap.c -o /tmp/maylang-install
/tmp/maylang-install
# Headless:
/tmp/maylang-install --yes --prefix="$HOME/tools/maylang" --no-modify-path
# The equivalent self-contained shell artifact:
sh maylang-install.sh --yes --no-modify-path
```

The shell artifact wraps the same C file using `sh`, `cc`, `cat`, `mktemp` and
`rm`. It can be fed through `sh` on stdin, including a downloaded script;
interactive prompts open `/dev/tty`. Verify the downloaded asset's adjacent
SHA-256 checksum before execution. Tagged releases built with this workflow
publish both bootstrap artifacts; older releases do not contain them.

### Existing release archives

Download `maylang-linux-x86_64.tar.gz` and
`maylang-linux-x86_64.tar.gz.sha256` from the
[release page](https://github.com/mirged/maylang/releases). Keep both files in
one folder with their original names. Installation requires no Rust, C compiler,
or Python. If you use GitHub CLI, download both assets together:

```sh
mkdir -p /tmp/maylang-download
gh release download --repo mirged/maylang --dir /tmp/maylang-download \
  --pattern maylang-linux-x86_64.tar.gz --pattern maylang-linux-x86_64.tar.gz.sha256
```

Get the installers from a source checkout (`git clone
https://github.com/mirged/maylang.git`). Releases made with the restructured
workflow will also include standalone `install.sh` and `install.ps1` assets;
older releases such as v0.11.2 need the checkout installer. The implementations
live in `toolchain/distribution`; existing `toolchain/install.*` commands remain
supported. When using the download directory above, pass
`/tmp/maylang-download/maylang-linux-x86_64.tar.gz` as the archive path.

### Linux x86-64

From the repository root, run:

```sh
sh toolchain/install.sh "$HOME/Downloads/maylang-linux-x86_64.tar.gz"
. "$HOME/.local/share/maylang/env.sh"
mayc --version
may new "$HOME/hello-maylang"
cd "$HOME/hello-maylang"
may run
```

The installer verifies the archive checksum, checks that the bundle is complete,
and copies it into `~/.local/share/maylang` before selecting its internal
`current` link. Extracted source bundles are copied too; deleting them cannot
break the installed tools. Keep the entire installed bundle
together so the compiler can find its runtime and standard library.

To enable future shells, add this line once to `~/.bashrc` for Bash,
`~/.zshrc` for Zsh, or `~/.profile` for a POSIX login shell:

```sh
. "$HOME/.local/share/maylang/env.sh"
```

The installer leaves your shell configuration untouched. It needs standard
Linux utilities: `sh`, `tar`, `sha256sum`, `awk`, `grep`, `diff`, and coreutils.

### Windows (WSL 2, x86-64)

Run `wsl --install` in an administrator PowerShell if WSL is not installed.
Restart Windows if prompted, then open the Linux distribution and finish its
initial account setup. From the repository root in PowerShell:

```powershell
.\toolchain\install.ps1 -Bundle "$HOME\Downloads\maylang-linux-x86_64.tar.gz"
```

This installs into the default WSL distribution. In a WSL terminal, run:

```sh
. "$HOME/.local/share/maylang/env.sh"
mayc --version
may new "$HOME/hello-maylang"
cd "$HOME/hello-maylang"
may run
```

Use the Linux shell startup instructions above to persist the environment.
The compiler and projects run inside WSL. Native Windows and macOS host bundles
are not available yet; cross-compiling programs for those systems does not
provide a native toolchain installation. ARM64 hosts are also unsupported by
the current release bundle.

### Upgrade, rollback, or choose a location

Download a new archive and checksum, then run the same installer and source
`env.sh` again. Previous versions remain installed. To switch back, pass an
extracted bundle directory:

```sh
sh toolchain/install.sh "$HOME/.local/share/maylang/maylang-0.11.2-x86_64-linux"
. "$HOME/.local/share/maylang/env.sh"
```

An optional second argument sets the installation root:

```sh
sh toolchain/install.sh /path/to/maylang-linux-x86_64.tar.gz "$HOME/tools/maylang"
. "$HOME/tools/maylang/env.sh"
```

In PowerShell, use `-InstallRoot /home/yourname/tools/maylang` (a Linux path).
The installer also accepts bundles extracted by the older `update.py` workflow;
remove its managed startup block if you stop using that environment file.

For `may`, compiler selection uses the manifest's `compiler`, then `MAYC`,
then `mayc` beside `may`, then `PATH`. Relative configured paths resolve from
the project root. See [May workspace configuration](../toolchain/may/README.md).

## Editor

Install the VS Code extension from `editors/vscode`, or build a VSIX:

```sh
cd editors/vscode
npm ci
npm exec --yes --package @vscode/vsce@3 -- vsce package --out /tmp/maylang.vsix
```

Use VS Code's **Install from VSIX** command. The extension starts `maylsp` from
`PATH`; set `maylang.serverPath` to an absolute path when needed. Restart the
editor after changing its inherited `PATH`. VS Code 1.82 or later is required.
Other LSP editors can launch the same `maylsp` executable over stdin/stdout.

## Build from source or package a bundle

Run `make doctor` and `make setup` from the checkout, then source the installed
prefix's `env.sh`. See [development setup](DEVELOPMENT.md) for prerequisites
and editor configuration. Packaging and archive verification are documented
in [distribution](../toolchain/distribution/README.md).

## Preparing a tagged release

The [Tagged release workflow](../.github/workflows/release.yml) runs when a
maintainer pushes `v<compiler-version>`. Set `MAYC_VERSION` in
`toolchain/mayc/main.may` before tagging. Packaging rejects a different version,
a tag pointing at another commit, or a dirty checkout. For example, the
compiler version `0.10.0` requires the exact source tag `v0.10.0`. Annotated
tags are recommended. Keep `RELEASE.json` synchronized with the compiler; it
records the codename (**Bramble**) and release date (**2026-10-13**). See the
[release convention](RELEASING.md) for future versions.

The workflow bootstraps from tagged source, checks compiler generations and
contracts, packages twice and compares the archives byte for byte, then tests
an extracted installation. It builds the VSIX with locked project dependencies
and a fixed packager version. Assets and checksums are attached to a draft
release before publication; tags containing a hyphen publish as prereleases.
A failure before publication leaves no published incomplete release. Ordinary
branch CI continues to upload artifacts without creating a release or tag.

To enforce the same source contract locally from a clean tagged checkout:

```sh
python3 toolchain/package.py --release-tag v0.10.0 --output /tmp/maylang-linux-x86_64.tar.gz
python3 toolchain/tests/test_package.py /tmp/maylang-linux-x86_64.tar.gz
```

## Target limits

Full runtime applications run on Linux x86-64. The core runtime emits Linux
ARM64/RISC-V64, macOS ARM64 and Windows x86-64 programs, with fewer language and
OS features and a bounded process-lifetime heap. Cross-target core execution is
tested with an emulator and with real macOS/Windows loaders in the
[native target suite](NATIVE_TARGETS.md). LLVM output is experimental and
excludes fibers and typed extern functions. See the
[compiler target matrix](../toolchain/mayc/README.md#cross-compilation).

New projects use [May workspaces](../toolchain/may/README.md). Run `may test`,
`may fmt --check`, and `may dev` from the workspace or a subdirectory.
