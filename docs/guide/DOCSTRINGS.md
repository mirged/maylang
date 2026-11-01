# Doc comments

A Maylang doc comment is a run of `///` lines directly above a declaration,
with no blank line in between. The comment is the only place a library
declaration is described. The [API reference](../reference/STDLIB.md), the
[runtime reference](../reference/RUNTIME.md), the
[editor reference](../../tools/maylsp/docs/REFERENCE.md) and `maylsp` hover,
completion and signature help are all built from it.

## Form

```may
/// Clamp `index` to a valid position in a list of length `size`.
///
/// Negative indices count from the end of the list.
///
/// Params:
/// - `index`: The requested position. Positions past either end move to the
///   nearest valid one.
/// - `size`: The list length.
///
/// Returns: An index from 0 to `size - 1`.
///
/// Faults: `fail("empty list")` when `size` is zero.
///
/// Example:
/// ```may
/// print(clamp_index(-1, 3)); // 2
/// ```
fun clamp_index(index: Int, size: Int) -> Int {
    if (size == 0) { fail("empty list"); }
    let i: Int = if (index < 0) { index + size } else { index };
    return max(0, min(i, size - 1));
}
```

- **Summary.** The first paragraph, one sentence where possible, ending with a
  period. Functions start with an imperative verb: "Return…", "Split…",
  "Report whether…", not "Returns…", "The…" or "Whether…". Types and
  bindings use a noun phrase ("A TCP socket handle.").
- **Detail.** Optional further paragraphs: preconditions, edge cases, cost,
  how the function relates to others.
- **Sections.** Optional, in this order, each starting at the beginning of a
  comment line:
  - `Params:` followed by one `` - `name`: description `` item per
    parameter. The names must be the function's parameter names. Indent a
    continuation line by two spaces.
  - `Returns:` the result, when the summary does not already say it.
  - `Faults:` the errors the function raises (`err.kind` values or the
    `fail` message), when callers are expected to handle them.
  - `Example:` followed by one fenced ```` ```may ```` block that runs as
    written.
- **Markdown.** The text is Markdown. Write code, names and values in
  backticks. Keep lines to 100 columns, including indentation and `///`.

Use the sections where they add information. A one-line summary is enough for
most helpers; the runtime functions in `native.may` that appear in the editor
catalog carry all of them.

## Where descriptions live

| What | Where |
| --- | --- |
| Functions, structs, enums and bindings in `stdlib/`, `native.may`, `prelude.may` and `runtime/math.may` | Their `///` comments |
| Module summaries and module-wide notes | `modules` and `notes` in [descriptions.json](../reference/descriptions.json) |
| Runtime primitives with no source declaration (`mkdir`, `exec`, …) | `runtime_extra` in `descriptions.json` |
| Keywords, types, operators and compiler built-ins (`print`, `len`, `push`, …) | [reference.json](../../tools/maylsp/docs/reference.json) |

A `reference.json` entry for a function that the standard library defines
only names its source file, for example `"sort": {"source": "native.may"}`.
Its signature, text and example come from the `///` comment.

After changing a doc comment, regenerate the pages:

```sh
python3 docs/reference/generate.py
python3 tools/maylsp/docs/generate.py
```

## Checks

`make check` runs both generators with `--check`. It fails when:

- a top-level declaration in `stdlib/` (including `native.may` and
  `prelude.may`) has no doc comment;
- a function summary does not start with an imperative verb, or a summary does
  not end with a period;
- a section is misspelled (`Parameters:`, `Return:`), repeated, out of order,
  or malformed, or `Params:` names something that is not a parameter;
- a doc comment line is longer than 100 columns;
- `descriptions.json` describes a declaration, or a source-backed
  `reference.json` entry has its own text;
- the generated pages are out of date.

The checker is `docs/reference/docstrings.py`. The compiler runtime
(`runtime/fat.may`, `runtime/fat_linux.may`) is not checked yet; give new
`rt_*` functions a `///` summary anyway.

## Editors

The language server shows a doc comment as Markdown in hover and completion,
with the sections rendered like the generated catalog. Signature help takes a
parameter's text from its `Params:` item; the older `@param name: text` form
still works. The VS Code extension gives `///` comments their own scope
(`comment.line.documentation.maylang`) and highlights backtick spans and
section names in them. It also highlights ```` ```may ```` and
```` ```maylang ```` fences in hovers, in the Markdown editor and in the
Markdown preview.
