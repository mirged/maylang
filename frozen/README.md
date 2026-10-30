# Frozen code

For now Maylang supports only Linux x86-64, with the full and raw runtimes
([Focus on Linux x86-64](../docs/design/LINUX_X86_64_FOCUS.md), #102). Code for
other targets and the platform experiments moves here. It is kept, with its
history, for when there is a reason and the capacity to bring it back.

## Rules

- Paths mirror where the code used to live: `frozen/platform/maybrowser/`
  was `platform/maybrowser/`. Files are moved with `git mv`, so
  `git log --follow` shows their history.
- Nothing here is compiled, imported, tested, formatted, indexed or
  packaged. `scripts/check_repository.py` skips this directory (links inside
  frozen Markdown are not checked), and the language server does not scan it.
- Frozen code is not maintained. Changes to the active compiler, runtime or
  libraries may leave it out of date, and nobody updates it here. Do not fix,
  reformat or extend it.
- Open issues for frozen areas carry the `status:frozen` label and have no
  milestone.
- **Reviving** an area means moving it back, updating it to the current
  compiler, restoring its tests and CI, and removing its entry below, all in
  one reviewed series.

## Frozen areas

Each entry records the last commit at which the area was tested, the
commands that tested it then, and the issues that tracked it.

| Area | Paths | Last tested | Tested with | Issues |
| --- | --- | --- | --- | --- |
| Browser | `platform/maybrowser/`, `.github/workflows/maybrowser.yml` | `2ec1b1a`, CI `maybrowser.yml` under Xvfb | `make test-browser` (`make -C platform/maybrowser check test`), doctor profile `browser` | #45 |
| MayOS | `platform/mayos/`, `platform/README.md` | Booted locally during #92 (`8d322c0`); never in CI | `make -C platform/mayos test` (QEMU) and `check` | #53 |
| ML library | `stdlib/ml/`, `docs/reference/stdlib/ml/` | `2ec1b1a`, `make test-compiler` | `examples/stdlib_expanded.may` (tensor, data, classical, loss, nn, optim and model checks), `compiler/mayc/tests/library/boundaries.may` (fixed inference), reference generator entries in `docs/reference/descriptions.json` | #57 |
| ML examples | `examples/ml_xor.may`, `examples/simulations/ecosystem/` | `2ec1b1a`, `make test-compiler` | `compiler/mayc/tests/verify.py` example entry points; the ecosystem's own `make test` | #57 |

Reviving the ML library also means restoring the removed checks in
`stdlib_expanded.may` and `boundaries.may`, the `ml/` entries in
`descriptions.json`, the experimental-API branches in
`docs/reference/generate.py` and the Tensor snippet in
`docs/reference/EXAMPLES.md`/`tests/docs/run.py`; `git show` on the freezing
commit lists them. Reviving the browser restores `make test-browser` and the
doctor's `browser` profile.
