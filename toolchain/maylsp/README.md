# maylsp

Diagnostics require explicit types and returns by default. See the
[strict language guide](../../docs/STRICT.md). VS Code sends `maylang.strict`
(default `true`); other clients can set `initializationOptions.strict` to
`false` for legacy files.

A native language server written entirely in Maylang. It implements the
[Language Server Protocol 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
over stdin/stdout, using the self-hosted compiler for diagnostics. The server
has no external runtime dependencies. Python is used only by its tests.

## Build and test

From the repository root:

```sh
make -C toolchain/maylsp build
python3 toolchain/maylsp/tests/test_lsp.py --binary toolchain/maylsp/build/maylsp
```

Or use the project Makefile:

```sh
make -C toolchain/maylsp
make -C toolchain/maylsp test
```

`mayc_new` can also build the server. Override the compiler with
`make -C toolchain/maylsp MAYC=../mayc/mayc_new test`. The test script
builds a temporary executable when run without `--binary`.

To measure the opening request queue, cached semantic tokens and formatting:

```sh
python3 toolchain/maylsp/tests/benchmark_lsp.py
```

Use `--binary /path/to/maylsp` to compare builds and `--source /path/to/file.may`
to profile another source file. Timings depend on file size and machine load.

Run `toolchain/maylsp/build/maylsp` to start the server. It waits for framed LSP
messages. The native executable currently targets Linux x86-64, matching
the self-hosted compiler's syscall runtime.

## Editor configuration

For the existing VS Code extension, set an absolute path:

```json
{
  "maylang.serverPath": "/absolute/path/to/maylang/toolchain/maylsp/build/maylsp"
}
```

For opencode:

```json
{
  "lsp": {
    "maylang": {
      "command": ["/absolute/path/to/maylang/toolchain/maylsp/build/maylsp"],
      "extensions": [".may"]
    }
  }
}
```

Other clients can launch the same executable with stdio transport and the
`maylang` language ID. Positions use UTF-16, including non-BMP characters.
Packets use UTF-8 byte lengths.

Standard library discovery checks `initializationOptions.stdlibPath`,
`MAYLANG_STDLIB`, `stdlib` in the current directory and workspace folders,
then `stdlib` beside or above the executable, including an extracted toolchain
bundle. You can override discovery with `MAYLANG_STDLIB`. Imports resolve
relative to their source file before the stdlib; `.may` is optional.

## Features

| Feature | Behavior |
| --- | --- |
| Lifecycle and transport | Initialize, shutdown, exit, JSON-RPC errors, buffered streaming, partial reads/writes, strict JSON and UTF-8 validation. |
| Document synchronization | Open, close, save, incremental and full changes, ordered edits, stale version protection; unsaved buffers override disk. |
| Diagnostics | Push and document pull diagnostics from `mayc`'s lexer, parser, resolver, mutability checks and supported annotation checks; missing import diagnostics. |
| Hover | Signatures and `///` documentation parsed from the open file, imported files and stdlib sources; the generated reference fills gaps for runtime primitives without a source declaration. |
| Navigation | Definitions and declarations across lexical scopes, selected imports, aliases, structs, enum constructors and known fields. |
| References and rename | Workspace references, highlights, prepare rename, cross-file edits, reserved-name rejection and binding conflict checks. |
| Completion | Visible bindings, keywords, runtime builtins, stdlib symbols, module exports and known struct fields; docs and replacement ranges. |
| Signature help | Source and runtime builtin signatures, parameter documentation and active argument tracking through nested calls. |
| Symbols | Nested document outline and workspace search. |
| Call hierarchy | Prepare, incoming and outgoing calls to named functions, grouped with call-site ranges. |
| Formatting | Configurable spaces/tabs, brace indentation, trailing whitespace removal, blank line normalization; string/comment braces do not affect indentation and multiline string contents are preserved. |
| Semantic tokens | Full and range requests; keywords, strings, numbers, comments, functions, variables, parameters, types and operators; declaration/readonly modifiers. |
| Folding and selection | Multiline brackets, consecutive comment blocks and nested token/block/document selections. |
| Document links | Clickable resolved import paths. |
| Inlay hints | Literal types, constructors, declared function return types, known builtin results and binding aliases; unknown results are omitted and explicit annotations are not repeated. |
| Code actions | Sort consecutive imports with `source.organizeImports`. |
| Workspace changes | Multiple roots, added/removed folders, file notifications and stdlib configuration changes. |

Navigation indexes lexical scopes and common binding forms, including
destructuring, anonymous functions, short lambdas, comprehensions, match
bindings and string interpolations. It respects public exports and avoids
resolving ambiguous unqualified imports.

## Implementation

```text
main.may          lifecycle, capabilities, synchronization and dispatch
src/protocol.may  framed stdio and strict JSON encoding/decoding
src/text.may      byte slices, UTF-16 positions and file URI conversion
src/index.may     tokens, scopes, bindings, imports and workspace index
src/diagnostics.may in-process mayc lexer/parser/semantic checker adapter
src/scheduler.may background compiler workers, debounce and cancellation
src/docs.may      generated documentation compiled into the executable
src/features.may  navigation and editor features
docs/reference.json  editable documentation catalog
docs/REFERENCE.md    generated readable language reference
tests/test_lsp.py  subprocess protocol tests
```

Compiler checks run in a forked worker with a snapshot of all unsaved buffers.
Editor requests continue while checks run; document diagnostic requests wait
asynchronously for the worker's result. Edits are coalesced for 120 ms before
checking, and newer edits stop obsolete workers. Results are published only
when their snapshot is current. Cancellation removes pending diagnostic
requests; shutdown stops and reaps the worker. The parent alone writes LSP
packets, including push diagnostics when the client is idle.

Unchanged diagnostic requests reuse cached checks, invalidated by document
and filesystem changes. Compiler source assembly uses balanced concatenation
and preserves import offsets in one module copy. Symbol lookups use per-name
indexes and cache imported name resolution. Token lookup uses binary search;
full semantic tokens are cached until an index change. Formatting visits tokens
in source order, and text processing uses byte helpers instead of repeatedly
indexing Unicode strings. Document highlights only inspect the current document.
Workspace scanning is
lazy, skips build/cache directories, and is bounded to 24 directory levels
and 10,000 indexed files. Imports also load files outside workspace roots.

## Documentation

The [editor reference](docs/REFERENCE.md) covers keywords, common types,
operators, runtime functions and core library helpers. Its 117 entries include
examples and API behavior; callable entries also explain parameters and return
values. The same catalog appears in hover, completion details and signature help.
Local and imported declarations retain their own source comments when they
shadow a library function.

Document declarations with consecutive `///` comments immediately above them.
These comments are read from the source file and take precedence over fallback
reference entries. `@param name: description` lines also populate parameter
documentation in signature help.

```may
/// Add two integers.
///
/// `a` and `b` are the values to add. Returns their sum.
/// Example: `add(2, 3)` returns `5`.
pub fun add(a: Int, b: Int) -> Int { return a + b; }
```

Document Maylang functions, structs, enums and fields in their `.may` source
files. `docs/reference.json` is the fallback catalog for language syntax and
runtime primitives that have no source declaration. To update that catalog,
run `python3 toolchain/maylsp/docs/generate.py` from the repository root, then
rebuild. Run the generator with `--check` to check the generated reference.

After rebuilding, use **Developer: Reload Window** in VS Code to restart the
server with the new executable. The configured `maylang.serverPath` stays the
same.

## Current limits

The compiler recovers independent top-level syntax and type errors and reports
up to 20 diagnostics per check, with original source ranges and stage codes.
Lexing, module loading and name resolution can still stop at their first error.
Annotation checking follows
`mayc`, with no separate general type inference engine. Member navigation
uses known declarations and simple binding types. Dynamically constructed
map members and dynamically selected callees may have no static definition.

Indexing and navigation requests still run serially; compiler diagnostics run
in the background. Cancellation applies to pending document diagnostic
requests, not to navigation requests already executing. Workspace-wide pull
diagnostics and semantic
token deltas are not advertised. Bodies are limited to 16 MiB. Invalid
transport headers terminate the server on stderr; invalid JSON produces a
recoverable parse error.

Tests exercise real framing, lifecycle errors, Unicode and sequential
edits, dirty imports, compiler diagnostics and recovery, public exports,
shadowing, navigation, references, rename, completion, signature help,
symbols, formatting, tokens, folding, selection, links, hints, code actions,
call hierarchy, file notifications, malformed messages, shutdown, documentation,
diagnostic cancellation, rapid edits, idle publication and hover responsiveness
behind VS Code's startup requests.
