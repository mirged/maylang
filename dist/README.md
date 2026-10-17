# Toolchain distribution

This directory owns packaging, installation and environment migration.
Checkout setup lives in [scripts](../scripts/README.md). Existing
`dist/package.py`, `update.py`, `install.sh` and `install.ps1` forward to
these implementations for users and automation.

Everyday installation starts with the repository-root [download script](../install.sh),
published as the `maylang-init.sh` release asset. It verifies and launches the
prebuilt `maylang-init-x86_64-linux` executable. Users need no build tools.
See the [one-line install command](../docs/guide/INSTALL.md).

| Entry point | Purpose |
| --- | --- |
| `package.py` | Deterministic Linux x86-64 archive, provenance and checksums |
| `install.sh` | Checksummed archive installation or extracted bundle selection without Python |
| `installer.may` | Interactive/headless copied prefix installation, shell integration and uninstall |
| `terminal.may` | Arrow-key selectors, tool checkboxes, progress, plain menus and terminal restoration |
| `bootstrap.c` | Template for the standalone host-cc launcher and embedded Maylang installer |
| `build_installer.py` | Generate self-contained C/shell artifacts from a complete bundle |
| `install.ps1` | Run the Linux installer inside the default WSL distribution |
| `update.py` | Migrate older Bash-managed installations |

## Build and verify a bundle

```sh
sh compiler/rust/build.sh
python3 compiler/mayc/tests/verify.py --compiler compiler/mayc/mayc_new
python3 dist/package.py --compiler compiler/mayc/mayc_new --output /tmp/maylang.tar.gz --installer-output /tmp/maylang-installers
python3 dist/tests/test_package.py /tmp/maylang.tar.gz
python3 dist/tests/test_installer.py --archive /tmp/maylang.tar.gz --artifacts /tmp/maylang-installers
python3 dist/tests/test_download_installer.py --artifacts /tmp/maylang-installers
```

Omit `--compiler` to bootstrap afresh. An explicit compiler is not silently
rebuilt. The archive records tool versions and source dirty state, with source
timestamps (`SOURCE_DATE_EPOCH` can override them).

It contains five tools, the native Maylang installer, runtime sidecars, `stdlib`, the complete Mayboard
workspace, release identity, changelog, provenance and `SHA256SUMS`.
The adjacent `.sha256` checks the archive. Keep the bundle together.

`make test-distribution` runs installer, migration and release source-contract
checks. `make package` also tests an extracted toolchain. Tagged packaging uses
`--release-tag v<version>` and requires a clean checkout at that exact tag;
see [releasing](../docs/guide/RELEASING.md).

The tagged workflow also publishes standalone `install.sh` and `install.ps1`
assets so release users need no checkout. Older releases can use the
compatibility installers in this repository.

`--installer-output DIR` also produces the prebuilt `maylang-init-x86_64-linux`,
the small `maylang-init.sh` downloader, `maylang-bootstrap.c`,
`maylang-install.sh` and their checksums. The native executable is statically
linked and embeds the entire bundle, so it also works offline. Ordinary users
download it; they never compile the C source. Developers can compile the C file with host `cc`;
it launches the embedded, source-built Maylang installer with no runtime tool
dependencies. The generated shell script wraps that compilation and supports
stdin delivery. See [installer options and uninstall](../docs/guide/INSTALL.md).
The C template is not itself an interpreter; run the generator/package command
to fill its payload. Generated assets stay outside tracked source files.

`make setup` and `make install` use `installer.may` to copy an independent
prefix; `make build` leaves disposable checkout development tools. Run
`make test-installer` for actual repository-deletion, TUI, component, bootstrap,
profile and uninstall tests, in addition to `make test-distribution`.

The downloader tests serve the real native asset over loopback HTTP and
exercise the exact `curl | sh` pipeline in a PTY. They check interactive input,
empty build-tool availability, checksum/missing-asset failures and terminal
restoration on interruption. Public download URLs require HTTPS; loopback HTTP
is allowed only for these local tests. Release packaging compares the native
executable along with the other reproducible artifacts before publishing.

The download-script/native-installer split and recommended/custom setup flow
follow the approach documented in [rustup's installer](https://github.com/rust-lang/rustup/blob/main/rustup-init.sh)
and [installation guide](https://rust-lang.github.io/rustup/installation/index.html).
