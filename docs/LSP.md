# Maylang language server

The language server is implemented in Maylang in
[`toolchain/maylsp`](../toolchain/maylsp/README.md). It builds with the self-hosted
compiler and runs as a native executable over stdio.

```sh
make -C toolchain/maylsp build
python3 toolchain/maylsp/tests/test_lsp.py --binary toolchain/maylsp/build/maylsp
```

Set the VS Code extension's `maylang.serverPath` to the absolute path of
`toolchain/maylsp/build/maylsp`, or configure that executable as your editor's stdio
language server for `.may` files. The project README contains the feature
list, configuration examples, architecture, and current limits.

Compiler diagnostics run in the background so hover and completion can respond
while a check is underway. The [editor reference](../toolchain/maylsp/docs/REFERENCE.md)
documents keywords, types, operators and core functions with examples; the same
documentation appears in hover, completion and signature help.

After rebuilding, run **Developer: Reload Window** in VS Code to load the new
server executable.
