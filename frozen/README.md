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
| Native-loader CI | `.github/workflows/native-targets.yml` | Last success `89a32a2` (run 40927832675); cancelled on later pushes | Emits ARM64 Mach-O and x86-64 PE fixtures with `compiler/mayc/tests/native_targets.py` and runs them on macOS 14/15 and Windows Server 2022/2025 | #55 |
| Core emulation CI | The `core-emulation` job of `.github/workflows/bootstrap.yml` (see `git show 2ec1b1a:.github/workflows/bootstrap.yml`) | `233909e` on `main` (run 41107159389) | `core_runtime.py` and `portable_values.py` with `--require-emulation` and `unicorn==2.1.4` against the bootstrap artifact | |
| Windows installer | `dist/install.ps1` | Published with v0.14.0; never tested in CI | Runs `install.sh` inside the default WSL distribution | |
| ARM64 and RISC-V backends | `compiler/mayc/src/backend/{arm64,riscv,raw,raw_fat,raw_float,portable}.may` | `28bcc9b` | `backends.py`, `regalloc.py`, `reachability.py`, `native_words.py`, `float_math.py`, `float_text.py` with `--target arm64-linux`/`riscv64-linux` (Unicorn or QEMU user emulation) | #93, #55 |
| Mach-O, PE and NXF formats | `compiler/mayc/src/formats/{macho,pe,nxf,portable}.may` | `28bcc9b` | `backends.py` (layout and Darwin/Windows ABI under Unicorn), `cli.py`, `native_targets.py` | #55 |
| NodeOS target | `compiler/mayc/runtime/nodeos.may`, `compiler/mayc/src/backend/x86_64_nodeos.may`, `docs/internals/NODEOS.md` | `28bcc9b` | `nodeos.py`; `make test-maylang` in the NodeOS checkout boots images and the compiler in QEMU | |
| Core runtime | `compiler/mayc/runtime/{fat_core,fat_corelib}.may`, `compiler/mayc/src/platform.may`, `docs/reference/stdlib/core.md`, `docs/internals/CORE_MEMORY.md` | `28bcc9b` | `core_runtime.py`, `portable_values.py` and the `--runtime core` modes of `cli.py`, `list_guards.py`, `float_literals.py`, `float_text.py`, `numeric_contracts.py`, `native_words.py`, `reachability.py`, `behavior_reports.py`, `build_benchmark.py` | |
| Target harnesses and docs | `compiler/mayc/tests/{core_runtime,portable_values,native_targets,nodeos}.py`, the pre-freeze `backends.py`, `tests/backend/{core,arena,portable_*}.may`, `docs/internals/{NATIVE_TARGETS,BACKEND_PARITY_PROGRESS}.md` | `28bcc9b` | `make test-compiler` | |
| ML examples | `examples/ml_xor.may`, `examples/simulations/ecosystem/` | `2ec1b1a`, `make test-compiler` | `compiler/mayc/tests/verify.py` example entry points; the ecosystem's own `make test` | #57 |

Reviving the ML library also means restoring the removed checks in
`stdlib_expanded.may` and `boundaries.may`, the `ml/` entries in
`descriptions.json`, the experimental-API branches in
`docs/reference/generate.py` and the Tensor snippet in
`docs/reference/EXAMPLES.md`/`tests/docs/run.py`; `git show` on the freezing
commit lists them. Reviving the browser restores `make test-browser` and the
doctor's `browser` profile.

Reviving a target also means restoring its `target_select` entry and driver
paths in `compiler/mayc/main.may`, `src/backend.may`, `src/formats.may`,
`src/backend/x86_64.may` (NodeOS gate, Windows entry), `x86_64_fat.may`
(core builtins, `__nodeos_syscall`), `platform_x86.may` (`__host_*`),
`sema.may`, `strict.may`, `words.may`, `runtime/fat_linux.may` (NodeOS
spawn without fork), the docs generator's `core` module and the bundle
checks in `dist/`; `git show` on the freezing commit lists them.
