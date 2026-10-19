# Shared Maylang formatter

Build from the repository root:

```sh
compiler/mayc/mayc_new tools/mayfmt/main.may -o /tmp/mayfmt
/tmp/mayfmt source.may
/tmp/mayfmt --check source.may
/tmp/mayfmt --help
python3 tools/mayfmt/tests/run.py
```

The formatter normalizes indentation, token spacing and statement/block line
breaks. The CLI uses four spaces. The language server calls the same formatter
with the editor's tab size and spaces/tabs setting. `--check` reports changes
without writing and returns 1 when formatting is needed. `--help` or `-h`
prints usage and exits 0 without reading or writing any file; running with no
file operands prints the same usage and exits 2.

Strings, including multiline/interpolated strings, and comment contents keep
their original bytes. Nested comments, compound operators, ranges and powers
stay intact. Formatting is idempotent; executable regressions compare program
output before and after formatting. Unterminated strings/comments and unbalanced
brackets fail before the affected file is written. This tool formats source;
`may check` supplies type and name diagnostics.
