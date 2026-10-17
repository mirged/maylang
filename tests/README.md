# Cross-component tests

Component suites live beside their code (`compiler/mayc/tests/`,
`tools/*/tests/`, `dist/tests/`). This directory holds suites that span
components.

| Suite | Covers | Command |
| --- | --- | --- |
| [compliance](compliance/README.md) | Runtime/coercion and language boundary regressions | `make test-compliance` |
| `docs/` | Runnable examples from the strict guide and reference | `make test-docs` |
| `ui/` | `stdlib/ui` native library, raster checks, X11 input and a demo | `make test-ui` |

Pass `MAYC=/absolute/path/to/mayc` to test a particular compiler.
