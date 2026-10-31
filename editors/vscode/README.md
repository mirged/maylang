# Maylang for VS Code

Language support for Maylang: syntax highlighting, snippets, and a language
client for `maylsp` (diagnostics from the self-hosted parser and semantic checker,
source and stdlib hover documentation, cross-file go-to-definition,
references, rename, completion, signature help, document symbols, and
formatting).

## Prerequisites

Build the language server (from the repository root):

```sh
make setup
```

Point the extension at the resulting binary in your VS Code settings:

```json
{
  "maylang.serverPath": "/absolute/path/to/maylang/build/dev/bin/maylsp"
}
```

See [the server README](../../tools/maylsp/README.md) for the complete
feature list and standard library configuration. The default command is `maylsp`, matching the installed toolchain bundle.
Existing installations under another name can use `maylang.serverPath`.

## Run the extension from source

```sh
cd editors/vscode
npm ci
npm run compile
```

Open this folder in VS Code and press <kbd>F5</kbd> ("Run Extension") to launch
an Extension Development Host with `.may` files supported.

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `maylang.serverPath` | `maylsp` | Path to the `maylsp` executable. |
| `maylang.strict` | `true` | Require explicit types and returns; disable for legacy source. |
| `maylang.trace.server` | `off` | Trace JSON-RPC traffic (`off`/`messages`/`verbose`). |

Changing `maylang.serverPath` or `maylang.strict` restarts the language server
with the new value; `maylang.trace.server` applies immediately. If
`maylang.serverPath` names a file that does not exist, the extension shows a
warning and does not start a server until the setting is fixed. If the command
cannot be started, it shows an error with the reason.

## Test

```sh
npm ci
xvfb-run -a npm test    # or plain `npm test` with a display
```

`npm test` downloads VS Code 1.82.0 (the oldest version `engines` allows) into
`.vscode-test/`, then runs `src/test/suite.ts` in an Extension Development
Host. The suite uses `test-fixtures/fake-maylsp` as the server and checks
discovery, the missing and failing server cases, restarts after setting changes,
serialized rapid changes and shutdown on deactivate. Set
`MAYLANG_VSCODE_VERSION` to test another release. `make test-editor` runs the
suite from the repository root.

## Package a `.vsix`

```sh
npm ci
npm exec --yes --package @vscode/vsce@3.6.2 -- vsce package --out /tmp/maylang.vsix
code --install-extension /tmp/maylang.vsix
```

## Files

* `package.json` — extension manifest (language id `maylang`, `.may` files).
* `src/extension.ts` — starts, restarts and stops the language client over stdio.
* `src/test/` — extension-host test runner and suite; `test-fixtures/fake-maylsp` is the fake server.
* `syntaxes/maylang.tmLanguage.json` — TextMate grammar.
* `language-configuration.json` — comments, brackets, indentation.
* `snippets/maylang.json` — function / loop / `may` / `match` snippets.
