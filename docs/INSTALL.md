# Install the Maylang toolchain

The compiler, project manager and language server currently run on Linux
x86-64. Building from source requires Rust, GCC or Clang, Python 3 and binutils.
LLVM output additionally requires Clang. The packaged tools need no Rust or C
compiler for normal direct native compilation. `may` needs the `sha256sum` command from coreutils. Native UI recipes additionally
need a C compiler, X11 development headers and a TrueType font. `maypkg` retains
its POSIX shell workflow for existing projects.

## Build and verify a bundle

From the checkout:

```sh
sh toolchain/rust/build.sh
python3 toolchain/mayc/tests/verify.py --compiler toolchain/mayc/mayc_new
python3 toolchain/package.py --compiler toolchain/mayc/mayc_new --output /tmp/maylang.tar.gz
python3 toolchain/tests/test_package.py /tmp/maylang.tar.gz
```

Omit `--compiler` from the package command to bootstrap afresh. The source
launcher caches its generated compiler; after changing compiler sources, run
`sh toolchain/rust/build.sh` again. Packaging does not silently refresh a compiler
explicitly supplied with `--compiler`.

The archive contains `bin/mayc`, `bin/may`, `bin/mayfmt`, `bin/maypkg`, `bin/maylsp`, runtime sidecars and
`stdlib`, plus the complete Mayboard source workspace at
`example_projects/apps/mayboard`. It also contains `VERSION`, `provenance.json` (source commit, dirty
state, host and compiler digest) and `SHA256SUMS`. The adjacent `.sha256` file
checks the archive itself. Archive timestamps are deterministic for the source
commit; `SOURCE_DATE_EPOCH` can override them.

## Install or upgrade

Download `maylang-linux-x86_64.tar.gz` and its adjacent `.sha256` from the
[GitHub releases](https://github.com/mirged/maylang/releases), together with the
optional `maylang-vscode.vsix` and its checksum. Nightly/prerelease tags are
marked as prereleases. The bundle's `provenance.json` records the source tag,
commit, compiler digest and Rust/C bootstrap tool versions.

```sh
cd /tmp
sha256sum -c maylang.tar.gz.sha256
mkdir -p "$HOME/.local/share/maylang"
tar -xzf maylang.tar.gz -C "$HOME/.local/share/maylang"
```

From a source checkout, configure Bash and select the newest extracted stable
release with:

```sh
python3 toolchain/update.py
source "$HOME/.local/share/maylang/env.sh"
```

The script keeps a `current` symlink to the complete bundle and configures both
`PATH` and `MAYLANG_STDLIB` through it. It backs up `.bashrc` to
`.bashrc.maylang-backup` before migrating old version-specific Maylang exports,
and preserves other shell settings. It also restores executable permissions
on the five tools if extraction lost them. Keep the entire bundle together;
copying only `mayc` loses runtime and library discovery.

After extracting a new release beside the old one, run `maylang-update` in Bash
to select the newest stable version and refresh that shell. It does not download
or build releases. Select a specific version (including a prerelease), or roll
back, with `maylang-update 0.11.2`. An extracted bundle directory is also accepted:

```sh
maylang-update /path/to/maylang-0.11.2-x86_64-linux
```

Use `python3 toolchain/update.py --dry-run` to preview the initial setup.
`--root` and `--bashrc` allow a different install location or Bash configuration.
Other open shells should source `env.sh` to refresh their environment.

```sh
mayc --version
may new /tmp/hello
cd /tmp/hello
may run
```

For `may`, compiler selection uses the manifest's `compiler`, then `MAYC`,
then `mayc` beside `may`, then `PATH`. Relative configured paths resolve from the project root.
`MAYLANG_STDLIB` supplies colon-separated library overrides before normal
discovery. See [May workspace configuration](../toolchain/may/README.md).

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
