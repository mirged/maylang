# Shared Maylang formatter

Build from the repository root:

```sh
toolchain/mayc/mayc_new toolchain/mayfmt/main.may -o /tmp/mayfmt
/tmp/mayfmt source.may
/tmp/mayfmt --check source.may
python3 toolchain/mayfmt/tests/run.py
```

The formatter normalizes indentation, token spacing and statement/block line
breaks. The CLI uses four spaces. The language server calls the same formatter
with the editor's tab size and spaces/tabs setting. `--check` reports changes
without writing and returns 1 when formatting is needed.

Strings, including multiline/interpolated strings, and comment contents keep
their original bytes. Nested comments, compound operators, ranges and powers
stay intact. Formatting is idempotent; executable regressions compare program
output before and after formatting. Unterminated strings/comments and unbalanced
brackets fail before the affected file is written. This tool formats source;
`may check` supplies type and name diagnostics.
