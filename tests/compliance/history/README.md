# Historical compliance reports

These snapshots were tracked at the audit baseline (`ba78973`). They retain
earlier validation evidence, including original source/build paths, and are
not current test results. The cleanup preserves their bytes in this directory.

Run `python3 tests/compliance/run.py` to create current results under
`tests/compliance/build/reports/`. Compiler verification writes separate
verification artifacts. Current generated results are ignored by Git.
