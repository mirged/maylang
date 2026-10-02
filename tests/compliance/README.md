# Maylang compliance and regression tests

The suite uses the self-hosted `toolchain/mayc/mayc_new` compiler.
The deprecated Rust reference implementation is not involved.

From the repository root:

```sh
toolchain/mayc/tests/run.sh
python3 tests/compliance/run.py
```

The first command rebuilds the self-hosted compiler, verifies that three
successive stages are byte-identical, and runs the existing feature, stress,
ABI, diagnostic, example/project, and ELF checks. Its report is
`verification.json`; the latest captured console output is `verification.log`
in this directory. The entrypoint
list is discovered dynamically, so adding an example no longer breaks a
hard-coded count assertion.

The second command runs historical dynamic runtime cases with `--legacy` and
writes `report.json`. The compiler verification also runs `strict_types.py`
with strict defaults, checking missing annotations, returns and concrete types.
It exits nonzero on failure. To test another self-hosted compiler, set `MAYC`
to its absolute path. Compiler binaries need their `runtime.may` and
`native.may` sidecars in the same directory.

All test sources, fixtures, and reports live here; generated executables
and verification artifacts go under `build/`. Each compilation is limited
to 30 seconds and each compliance executable to 3 seconds. Core dumps are
disabled. Python 3 and Linux are required.

## Fixed behavior

| Area | Regression expectation |
| --- | --- |
| Invalid calls | Calling a non-function raises a catchable `type` error instead of crashing. |
| Cyclic collections | Lists and maps print `<cycle>` at back-references; repeated non-cyclic references print normally. |
| Modules | Module globals have distinct linkage names; aliases, selective imports, and `pub` visibility are respected. Ambiguous imported references are rejected. |
| Integer literals | The full signed 61-bit range compiles, including the minimum value. Out-of-range literals produce diagnostics. |
| Integer conversion and arithmetic | Parsing the minimum value succeeds; negating it, taking its absolute value, or dividing it by -1 raises `arithmetic`. |
| Compound assignment | Indexed and property targets support `+=`, `-=`, `*=`, `/=`; receiver and index are evaluated once, before the right-hand side. |
| JSON Unicode | Surrogate pairs decode to valid UTF-8; malformed or unpaired surrogate escapes raise `parse`. |
| Invalid declarations/control flow | Duplicate parameters and returns outside functions are rejected. |

The suite also checks closure captures, tail calls, cleanup of exception
handlers, argument order, short-circuiting, Unicode indexing, and syntax
errors. One arithmetic test compares 100 deterministic expressions with an
independent Python calculation (integer division truncates toward zero).

Some cases exercise the same underlying fix from different directions;
the number of passing cases is not a count of distinct fixes. Expected
compile errors count as passes only when compilation fails with a diagnostic
and produces no executable. Runtime checks compare exact output bytes, so
invalid UTF-8 cannot pass by being replaced during decoding.

The `json_unicode` case records the existing source-string escape behavior.
The JSON compliance tests construct backslash bytes explicitly to avoid
confusing source-language escapes with JSON escapes.

Current counts and individual outcomes are recorded in `report.json` and
`verification.json`, including the self-hosting fixpoint and discovered entrypoints.
