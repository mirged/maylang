# Checkout development scripts

Use `make help` at the repository root. These scripts use Python's standard
library and require Python 3.10+.

- `doctor.py`: read-only build, test, UI, browser, editor and package prerequisite checks.
- `build_tools.py`: compile tools into `build/dev/bin`, copy runtime sidecars and generate a sourceable environment.
- `check_repository.py`: check local Markdown file links and parse JSON/Python syntax without generating bytecode.
- `install_nightly.sh`: build the compiler and tools from this checkout, stamp the version
  `<release>-nightly.<date>.<commit>[.dirty]`, check that the new compiler builds and
  runs a program, and install it into `~/.maylang` (or `--prefix DIR`) as a new
  generation with the native installer. `--pull` fast-forwards first; `--keep N` deletes
  all but the newest N nightly generations.
- `tests/test_developer.py`: prerequisite failures, shell quoting/idempotence and distribution CLI compatibility.

`make setup` rebuilds the compiler first, then uses the Maylang installer to
copy an independent user installation. `make build` only produces disposable
checkout tools. `make tools MAYC=/absolute/path/to/mayc`
uses a prebuilt compiler from this source tree. Compiler and runtime sources
must match. Outputs stay under ignored `build/`. Release scripts live in
[dist](../dist/README.md).
