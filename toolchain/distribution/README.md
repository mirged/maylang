# Toolchain distribution

This directory owns packaging, installation and environment migration.
Checkout setup lives in [scripts](../../scripts/README.md). Existing
`toolchain/package.py`, `update.py`, `install.sh` and `install.ps1` forward to
these implementations for users and automation.

| Entry point | Purpose |
| --- | --- |
| `package.py` | Deterministic Linux x86-64 archive, provenance and checksums |
| `install.sh` | Checksummed archive installation or extracted bundle selection without Python |
| `install.ps1` | Run the Linux installer inside the default WSL distribution |
| `update.py` | Migrate older Bash-managed installations |

## Build and verify a bundle

```sh
sh toolchain/rust/build.sh
python3 toolchain/mayc/tests/verify.py --compiler toolchain/mayc/mayc_new
python3 toolchain/distribution/package.py --compiler toolchain/mayc/mayc_new --output /tmp/maylang.tar.gz
python3 toolchain/tests/test_package.py /tmp/maylang.tar.gz
```

Omit `--compiler` to bootstrap afresh. An explicit compiler is not silently
rebuilt. The archive records tool versions and source dirty state, with source
timestamps (`SOURCE_DATE_EPOCH` can override them).

It contains five tools, runtime sidecars, `stdlib`, the complete Mayboard
workspace, release identity, changelog, provenance and `SHA256SUMS`.
The adjacent `.sha256` checks the archive. Keep the bundle together.

`make test-distribution` runs installer, migration and release source-contract
checks. `make package` also tests an extracted toolchain. Tagged packaging uses
`--release-tag v<version>` and requires a clean checkout at that exact tag;
see [releasing](../../docs/RELEASING.md).

The tagged workflow also publishes standalone `install.sh` and `install.ps1`
assets so release users need no checkout. Older releases can use the
compatibility installers in this repository.
