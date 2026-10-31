# Maylang developer tools

Everyday commands built with the [compiler](../compiler/README.md). Each tool
keeps its own tests and build files.

| Tool | Purpose | Start here |
| --- | --- | --- |
| [may](may/README.md) | Workspace runner, explicit targets and verified build cache | `may/main.may` + `may/src/` |
| [mayfmt](mayfmt/README.md) | Shared CLI and editor formatter | `mayfmt/main.may` |
| [maylsp](maylsp/README.md) | Native language server and editor features | `maylsp/main.may` + `maylsp/src/` |
| [maypkg](maypkg/README.md) | Project discovery, dependency checks, lock files, and build scripts | `maypkg/main.may` + `maypkg/src/` |
| [shared](shared/README.md) | Formatter core, filesystem helpers and import scanner used by several tools | `shared/` |

`maylsp` reuses the compiler frontend from `../../compiler/mayc/src/`, and
`may`, `maypkg` and the installer share `shared/fs.may` and `shared/imports.may`.

## Build and test

From the repository root:

```sh
make setup
. "$HOME/.maylang/env.sh"
mayc examples/hello.may -o /tmp/hello
make test-tools
```

`make -C tools/maylsp test` runs only the language server. See
[development setup](../docs/guide/DEVELOPMENT.md) and
[contributing](../CONTRIBUTING.md) for prerequisite checks and targeted root
Make commands. Release installation lives in [dist/](../dist/README.md).
