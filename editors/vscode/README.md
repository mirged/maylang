# Maylang for VS Code

Language support for Maylang: syntax highlighting, snippets, and a language
client for `maylsp` (diagnostics from the self-hosted parser and semantic checker,
source and stdlib hover documentation, cross-file go-to-definition,
references, rename, completion, signature help, document symbols, and
formatting).

## Prerequisites

Build the language server (from the repository root):

```sh
make -C toolchain/maylsp build
```

Point the extension at the resulting binary in your VS Code settings:

```json
{
  "maylang.serverPath": "/absolute/path/to/maylang/toolchain/maylsp/build/maylsp"
}
```

See [the server README](../../toolchain/maylsp/README.md) for the complete
feature list and standard library configuration. The default command is `maylsp`, matching the installed toolchain bundle.
Existing installations under another name can use `maylang.serverPath`.

## Run the extension from source

```sh
cd editors/vscode
npm install
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

## Package a `.vsix`

```sh
npm install                 # only typescript + vscode-languageclient
npm run compile
npx @vscode/vsce@3 package  # vsce 3 works on Node 20; use latest on Node 22+
code --install-extension maylang-0.1.0.vsix   # run inside the WSL remote
```

## Files

* `package.json` — extension manifest (language id `maylang`, `.may` files).
* `src/extension.ts` — starts the language client over stdio.
* `syntaxes/maylang.tmLanguage.json` — TextMate grammar.
* `language-configuration.json` — comments, brackets, indentation.
* `snippets/maylang.json` — function / loop / `may` / `match` snippets.
