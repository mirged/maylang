# Shared tool modules

Internal Maylang modules imported by more than one developer tool. They have no
command-line interface of their own and no compatibility promise outside this
repository; change them together with every consumer listed here.

| Module | Contents | Consumers |
| --- | --- | --- |
| `format.may` | Formatter core | `mayfmt/main.may`, `may/main.may`, `maylsp/src/features.may` |
| `fs.may` | Path math, `mkdirs`, directory listing, atomic writes, stdlib search path | `may/main.may`, `may/src/{build,process,workspace}.may`, `maypkg/src/*.may`, `../dist/installer.may` |
| `imports.may` | Comment/string-aware import scanner, resolution and graph traversal | `may/src/build.may`, `maypkg/src/{commands,project,render}.may` |

Tools must not import another tool's `src/` directory; move reusable code here
instead. `scripts/check_repository.py` (run by `make check`) rejects imports of
`tools/<tool>/src/` from outside that tool.

Tests run through the consumers: `make test-tools` (the `may`, `maypkg` and
`maylsp` suites) and `make test-distribution` (the installer).
