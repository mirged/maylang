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

Measure references, rename and workspace symbols at the scanning limit, with
a hover request queued immediately after each navigation request:

```sh
python3 toolchain/maylsp/tests/benchmark_navigation.py \
  --binary toolchain/maylsp/build/maylsp --files 10016 \
  --report /tmp/navigation-benchmark.json
```

This creates temporary projects, verifies 10,000-file results and records
navigation/hover timings and the server hash. The extra 16 files test the scan
limit. On Linux x86-64, 2026-10-11, one run measured references at 4.72 s,
rename at 7.37 s and symbols at 2.20 s; interleaved hover returned in 0.89 ms,
3.67 ms and 9.21 ms respectively. These are fixture measurements, not latency
guarantees. The optional manually dispatched performance CI job uploads the
same report without timing thresholds.

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
| Diagnostics | Push, document and workspace pull diagnostics from `mayc`'s lexer, parser, resolver, mutability checks and supported annotation checks; missing imports, result IDs, unchanged reports and workspace progress. |
| Hover | Signatures and `///` documentation parsed from the open file, imported files and stdlib sources; the generated reference fills gaps for runtime primitives without a source declaration. |
| Navigation | Definitions and declarations across lexical scopes, selected imports, aliases, structs, enum constructors and known fields. |
| References and rename | Workspace references, highlights, prepare rename, cross-file edits, reserved-name rejection and binding conflict checks. |
| Completion | Visible bindings, keywords, runtime builtins, stdlib symbols, module exports and known struct fields; docs and replacement ranges. |
| Signature help | Source and runtime builtin signatures, parameter documentation and active argument tracking through nested calls. |
| Symbols | Nested document outline and workspace search. |
| Call hierarchy | Prepare, incoming and outgoing calls to named functions, grouped with call-site ranges. |
| Formatting | Configurable spaces/tabs, brace indentation, trailing whitespace removal, blank line normalization; string/comment braces do not affect indentation and multiline string contents are preserved. |
| Semantic tokens | Full, negotiated delta and range requests; keywords, strings, numbers, comments, functions, variables, parameters, types and operators; declaration/readonly modifiers. |
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
src/navigation.may bounded navigation worker, snapshots and streamed results
src/workspace.may workspace diagnostic batches, progress and snapshot cancellation
src/workspacecache.may bounded encoded full reports, cleared on snapshot changes
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

References, rename, workspace symbols and call hierarchy use a separate worker.
One navigation request runs at a time, with at most 32 queued requests, a
30-second deadline and a 16 MiB result limit. References, rename and symbols
index disk files in batches of 32 and stream encoded results to the parent;
unsaved buffers remain in the snapshot. A final worker status commits the
response, so late rename conflicts discard all partial edits. Runtime fatal
output stays on the worker pipe and fails the request without corrupting LSP
transport. Edits and workspace changes discard obsolete results with
`RequestFailed` (-32803), asking the client to retry. Client cancellation returns
`RequestCancelled` (-32800) for active or queued requests. Shutdown reaps all
workers. Local editor requests continue while navigation is running.

Workspace diagnostic pulls use a third worker, independent of document checks
and navigation. Send `workspace/diagnostic` with `previousResultIds: []` for the
first pull and `{uri, value: resultId}` entries for subsequent pulls. The server
advertises `diagnosticProvider.workspaceDiagnostics` and `workDoneProgress`.
Reports carry the current open-buffer version, or `null` for unopened files.
`partialResultToken` streams reports through `$/progress`; the final response
then contains an empty `items` array. `workDoneToken` enables begin/report/end
progress and `window/workDoneProgress/cancel` cancellation.

Document and workspace result IDs include a server session, content/configuration
epoch and canonical URI. Matching previous IDs receive `unchanged`; unknown IDs
receive full reports. Edits and watched-file, folder or compiler-setting changes
invalidate the workspace snapshot with `ServerCancelled` (-32802), requesting a
retry. Client cancellation returns -32800. Deleted files and removed roots clear
previous reports with empty full results; a file omitted only by the scan limit
keeps its existing report. Unsaved buffers override disk files in import checks.
The report formats follow [LSP 3.17 pull diagnostics](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#workspace_diagnostic).

One workspace worker runs at a time, with eight queued requests and at most
10,000 selected files. Each worker checks at most 32 entries before being
reaped and replaced. Clean entries share a compiler check; any batch error
triggers separate checks so lexer failures and recovery limits cannot mask
other files. Reports drain at most 32 per event-loop turn. Requests are limited
to 16 MiB of worker output, 30 seconds without a report and five minutes total.
Workspace IDs encode their session and snapshot. Full reports are cached as
encoded JSON in a 16 MiB mapping with at most 10,000 entries; snapshot changes
clear it. Matching reports check only existence and version; changed files
are checked first. Buffered replies write one frame from encoded parts without
allocating another joined result string. Byte scans use counters and URI encoding
copies spans, avoiding temporary arrays for large frames and repeated prefixes.
Compiler symbol tables own zeroed mappings with explicit release;
AST and strict-checker roots are released between checks.

Unchanged diagnostic requests reuse cached checks, invalidated by document
and filesystem changes. Compiler source assembly uses balanced concatenation
and preserves import offsets in one module copy. Symbol lookups use per-name
indexes and cache imported name resolution. Token lookup uses binary search;
full semantic tokens are cached with a stable result ID until an index change.
The last two full snapshots per document support delta
requests; unknown, evicted, other-document and close/reopen IDs receive a full
response. Deltas compare the encoded integer arrays, including UTF-16 positions.
Range requests do not alter full-token history. Formatting visits tokens
in source order, and text processing uses byte helpers instead of repeatedly
indexing Unicode strings. Document highlights only inspect the current document.
Workspace scanning is
lazy, skips build/cache directories, and is bounded to 24 directory levels
and 10,000 workspace file paths. Imports and open buffers can also load files
outside workspace roots and remain available to navigation snapshots.

## Documentation

The [editor reference](docs/REFERENCE.md) covers keywords, common types,
operators, runtime functions and core library helpers. Its 139 entries include
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

## Workspace diagnostic benchmark

Measure cold streamed checks and unchanged buffered reports, with interleaved hover:

```sh
python3 toolchain/maylsp/tests/benchmark_diagnostics.py \
  --binary toolchain/maylsp/build/maylsp --files 10016 \
  --report /tmp/diagnostic-benchmark.json
```

The fixture checks the 10,000-file cap, open/unopened versions and stable IDs.
It also verifies that existing files omitted by the cap do not receive clears.
The optional CI performance job repeats it on the extracted toolchain and
publishes `diagnostic-benchmark.json` alongside compiler/navigation measurements.
Timings are recorded without thresholds.

## Current limits

The compiler recovers independent top-level syntax and type errors and reports
up to 20 diagnostics per check, with original source ranges and stage codes.
Lexing, module loading and name resolution can still stop at their first error.
Annotation checking follows
`mayc`, with no separate general type inference engine. Member navigation
uses known declarations and simple binding types. Dynamically constructed
map members and dynamically selected callees may have no static definition.

Document indexing still runs serially; compiler diagnostics and expensive
navigation run in separate workers. Large individual files, imports and result
sets remain constrained by the runtime heap and worker limits; failed navigation
or workspace checks return a request error. Workspaces exceeding the scan limit
need individual document pulls for omitted files.
Bodies are limited to 16 MiB. Invalid
transport headers terminate the server on stderr; invalid JSON produces a
recoverable parse error.

Tests exercise real framing, lifecycle errors, Unicode and sequential
edits, dirty imports, compiler diagnostics and recovery, public exports,
shadowing, navigation, references, rename, completion, signature help,
symbols, formatting, tokens, folding, selection, links, hints, code actions,
call hierarchy, file notifications, malformed messages, shutdown, documentation,
diagnostic cancellation, rapid edits, idle publication and hover responsiveness
behind VS Code's startup requests. Additional tests replay token deltas, verify
ID invalidation and interleave edits/hover with large navigation requests,
including queued/active cancellation, queue limits, late rename failures,
worker fatal-output isolation and shutdown reaping.
Workspace tests cover unopened files, full/unchanged reports, progress, restart
IDs, dirty imports, deletion and removed roots, concurrent document requests,
cancellation, stale snapshots, bounded queues and isolation of failed batches.
