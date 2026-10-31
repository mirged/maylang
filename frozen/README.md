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

None yet.
