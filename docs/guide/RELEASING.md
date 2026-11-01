# Release names

Maylang uses numeric versions for tools and nature codenames for people:
**0.13.102 “Dahlia”** is tagged `v0.13.102`. `mayc --version` prints the numeric
version, so scripts and bundle paths do not need to parse a codename.

Each minor series gets the next alphabetical nature name. Aster starts the
convention; Bramble names 0.11, Clover names 0.12, Dahlia names 0.13, and
Elm is the suggested next series. Patch releases keep
their series name: 0.10.1 is still Aster. A new small feature normally advances
the minor version; fixes advance the patch. While Maylang is below 1.0, minor
versions can also contain breaking changes, which must be described in notes.

For preview builds use ordered prerelease suffixes such as `0.11.0-alpha.1`
or `0.11.0-rc.1`. A codename is a label, not a prerelease suffix. Release dates
use `YYYY-MM-DD` in UTC and stay outside tags; no version or published tag is
reused. A named numeric release does not change the language's experimental
status or its documented runtime limits.

## Preparing a release

1. Update `MAYC_VERSION` in `compiler/mayc/main.may`, `RELEASE.json`, the README
   badge and the editor extension version/lockfile. The metadata records the
   same numeric version, its codename and the actual release date.
2. Write `CHANGELOG.md` for that release. Include its small feature, behavior
   changes and remaining limits.
3. Rebuild from source and run focused regressions, compiler verification,
   source-generation convergence and reference freshness checks. Commit the
   source and documentation together and push the branch for CI.
4. Create an annotated `v<version>` tag on the verified source commit and push
   it. The [release workflow](../../.github/workflows/release.yml) validates source
   identity, compares two packages and tests an extracted installation before
   publishing the bundle, VSIX and checksums.

Packaging checks `RELEASE.json` against the compiler and stores its metadata
inside the bundle and its provenance. GitHub uses the codename in the release
title. The release notes are only that version's `# Maylang <version> — <codename>`
section of `CHANGELOG.md`, extracted by `dist/release_notes.py`; the release
fails if the section is missing, empty or duplicated, so a prerelease tag needs
its own heading (for example `# Maylang 0.16.0-rc.1 — Gorse`). Preview the notes
with `python3 dist/release_notes.py v<version>`. See [installation](INSTALL.md) for
bundle layout and upgrade instructions.
