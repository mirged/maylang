# Install the Maylang toolchain

The compiler, project manager and language server currently run on Linux
x86-64. Building from source requires Rust, GCC or Clang, Python 3 and binutils.
LLVM output additionally requires Clang. The packaged tools need no Rust or C
compiler for normal direct native compilation. `maypkg` uses a POSIX shell and
the `sha256sum` command from coreutils.

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

The archive contains `bin/mayc`, `bin/maypkg`, `bin/maylsp`, runtime sidecars and
`stdlib`. It also contains `VERSION`, `provenance.json` (source commit, dirty
state, host and compiler digest) and `SHA256SUMS`. The adjacent `.sha256` file
checks the archive itself. Archive timestamps are deterministic for the source
commit; `SOURCE_DATE_EPOCH` can override them.

## Install or upgrade

```sh
cd /tmp
sha256sum -c maylang.tar.gz.sha256
mkdir -p "$HOME/.local/share/maylang"
tar -xzf maylang.tar.gz -C "$HOME/.local/share/maylang"
```

Add the extracted bundle's `bin` directory to `PATH`, using its actual versioned
directory name. Keep the entire bundle together; copying only `mayc` loses
runtime and library discovery. To upgrade, extract the new version beside the
old one and update `PATH`. This also makes rollback a path change.

```sh
mayc --version
maypkg new /tmp/hello
cd /tmp/hello
maypkg run
```

Compiler selection is `MAYC`, then the manifest's `compiler`, then `mayc` beside
`maypkg`, then `PATH`. Relative configured paths resolve from the project root.
`MAYLANG_STDLIB` supplies colon-separated library overrides before normal
discovery. See [maypkg configuration](../toolchain/maypkg/README.md).

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

## Target limits

Full runtime applications run on Linux x86-64. The core runtime emits Linux
ARM64/RISC-V64, macOS ARM64 and Windows x86-64 programs, with fewer language and
OS features and a bounded process-lifetime heap. Cross-target core execution is
tested with an emulator; macOS signing and real Windows/macOS host behavior
still require testing on those systems. LLVM output is experimental and
excludes fibers and typed extern functions. See the
[compiler target matrix](../toolchain/mayc/README.md#cross-compilation).
