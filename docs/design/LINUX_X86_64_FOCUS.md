# Focus on Linux x86-64

Status: proposed. Tracked in the issue linked from
[ROADMAP.md](../../ROADMAP.md#focus-linux-x86-64).

For now Maylang supports one platform: **Linux on x86-64**, with the full and
raw runtimes. Every other target, the core runtime and the platform
experiments are frozen: moved into `frozen/`, kept for later, not built, not
tested and not maintained. The effort they took goes into making the language
itself better: speed, correctness, ergonomics, documentation and tools.

This is a temporary scope reduction, not a deletion. The code stays in the
tree, with its history, until there is a reason and the capacity to bring it
back.

## Why

- **One backend to optimize.** The [performance roadmap](PERFORMANCE_ROADMAP.md)
  needs register allocation, type-directed lowering and an IR optimizer. Today
  every change to dynamic code has to land in `x86_64_fat.may` and again in
  `raw_fat.may` (ARM64, RISC-V), and keep the core runtime and the NodeOS
  personality in step.
- **No image budget.** NodeOS loads a compiler image of at most 4 MiB, which
  limits inlining and runtime fast paths. The compiler is 3.2 MB today.
- **Smaller surface.** About 2 300 of the compiler's 12 800 source lines exist
  only for other targets (`backend/arm64.may`, `backend/riscv.may`,
  `backend/raw_fat.may`, `formats/macho.may`, `formats/pe.may`,
  `formats/nxf.may`, `runtime/nodeos.may`, `runtime/fat_core.may`,
  `runtime/fat_corelib.may`). `platform/` and `stdlib/ml/` add about 4 600
  lines of Maylang with their own suites and CI.
- **Faster feedback.** Fewer harnesses in `make test-compiler`, no
  cross-target emulation job, no Windows and macOS runners.

## What stays

- Target `x86_64-linux`: ELF output, the full runtime (`runtime/fat.may`,
  `runtime/fat_linux.may`, collector, files, processes, FFI), raw mode
  (`--raw`, `--runtime none`) and native-word functions.
- The source bootstrap (`compiler/rust/`) and the bootstrap fixpoint.
- Tools: `may`, `mayfmt`, `maylsp`, `maypkg` (legacy), the VS Code extension.
- The standard library except `stdlib/ml/`, including `stdlib/ui/` (X11 and
  OpenGL on Linux).
- Examples and complete projects that run on Linux x86-64.
- Linux packaging and installers (`dist/install.sh`, updates, systemd timer).

## What is frozen

| Area | Paths today | Notes |
| --- | --- | --- |
| ARM64 and RISC-V backends | `src/backend/arm64.may`, `src/backend/riscv.may`, `src/backend/raw_fat.may` | `raw_float.may` imports `riscv.may`, so its RISC-V parts must be separated first |
| macOS, Windows and NodeOS formats | `src/formats/macho.may`, `src/formats/pe.may`, `src/formats/nxf.may` | `main.may` imports `nxf.may` directly |
| NodeOS target | `runtime/nodeos.may`, the syscall gate in the x86-64 backends | The sibling NodeOS checkout's `make maylang` will stop working |
| Core runtime | `runtime/fat_core.may`, `runtime/fat_corelib.may`, `--runtime core` | Exists for the portable targets; `--runtime none` and raw stay |
| Target tests | `tests/backends.py` (portable parts), `core_runtime.py`, `portable_values.py`, `native_targets.py`, `nodeos.py`, portable fixtures in `tests/backend/portable_*.may` and `core.may` | Target loops in `float_math.py`, `float_text.py`, `raw_codegen.py`, `regalloc.py`, `native_words.py`, `reachability.py` and `behavior_reports.py` shrink to x86-64 Linux |
| CI | `.github/workflows/native-targets.yml`, the `core-emulation` job, `.github/workflows/maybrowser.yml` | |
| Windows installer | `dist/install.ps1` | |
| Platform experiments | `platform/maybrowser/`, `platform/mayos/` | |
| Experimental ML library | `stdlib/ml/`, `docs/reference/stdlib/ml/` | |
| Target docs | `docs/internals/NATIVE_TARGETS.md`, `NODEOS.md`, `BACKEND_PARITY_PROGRESS.md` | References in `README.md`, `AGENTS.md`, `TOOLCHAIN.md` and the compiler README are rewritten |

Open issues for frozen areas get a `status:frozen` label and leave the active
milestones: #93 (native words on ARM64/RISC-V), #55 (ARM64 and desktop
compiler hosts), #45 (maybrowser), #53 (mayos) and #57 (ML oracles).

## How freezing works

- `frozen/` at the repository root mirrors the original paths, for example
  `frozen/compiler/mayc/src/backend/arm64.may` and
  `frozen/platform/maybrowser/`. Files move with `git mv` so `git log
  --follow` keeps their history.
- `frozen/README.md` lists every frozen area, the commit it was last tested
  at, the commands that tested it then, and the issues that tracked it.
- Nothing in `frozen/` is compiled, imported, tested, formatted, indexed or
  packaged. `scripts/check_repository.py`, `verify.py`, the docs generators,
  the language server's workspace scan, `may` workspaces and `dist/package.py`
  skip the directory. Links inside frozen Markdown are not checked.
- Frozen code is not maintained. Changes to the active compiler may leave it
  out of date, and nobody fixes it there. `AGENTS.md` says so.
- The compiler rejects the frozen options with a clear error, for example
  `target arm64-linux is frozen; Maylang currently supports x86_64-linux
  (see frozen/README.md)`. `--target x86_64-linux` stays accepted.
- **Reviving** an area means moving it back, updating it to the current
  compiler, restoring its tests and CI, and removing it from
  `frozen/README.md`, all in one reviewed series.

## Steps

Each step is one PR, green on its own (`make check test`, and
`make test-bootstrap` for compiler steps).

1. **Baseline and triage.** Record compiler source lines, binary size,
   `make test` and `make test-bootstrap` wall time, and CI duration. Create the
   `status:frozen` label and relabel the issues above. Add `frozen/README.md`
   and the exclusions in the repository checks, with nothing frozen yet.
2. **Platform experiments and ML.** Move `platform/maybrowser/`,
   `platform/mayos/`, `stdlib/ml/` and their reference pages. Remove
   `maybrowser.yml`, the browser and mayos Make targets and doctor profiles,
   and the ML entries in `descriptions.json`, the stdlib reference and
   `EXAMPLES.md`. No compiler change.
3. **CI and distribution.** Remove `native-targets.yml` and the
   `core-emulation` job, and freeze `dist/install.ps1`. Package text mentions
   only Linux x86-64.
4. **Separate the compiler seams.** Split the RISC-V helpers that
   `raw_float.may` uses, make `backend.may` and `formats.may` stop importing
   the portable backends and formats, and isolate the NodeOS syscall gate in
   the x86-64 backends. Behaviour is unchanged, all targets still pass. This
   step is reviewable on its own.
5. **Freeze the targets.** Move the backends, formats, NodeOS and core
   runtimes and their tests into `frozen/`. Reject frozen `--target` and
   `--runtime core` values. Trim target loops in the remaining harnesses.
   Rebuild and check the bootstrap fixpoint. This is a breaking change:
   `CHANGELOG.md` under *Unreleased*, `breaking-change` label.
6. **Documentation.** Rewrite `README.md`, `AGENTS.md` (repository map,
   commands, hazards; drop the NodeOS sections), `TOOLCHAIN.md`, the compiler
   README capability matrix and `docs/REPOSITORY.md`. Remove the NodeOS image
   budget from the [performance roadmap](PERFORMANCE_ROADMAP.md).
7. **Measure again.** Same numbers as step 1, recorded in this document.

## Baseline

Recorded 2026-10-30 at `2ec1b1a` before anything was frozen, on an Intel Core
i5-13500H (16 threads), one run each, with `MAYC` set to the checkout
compiler. Step 7 repeats these measurements.

| Measurement | Value |
| --- | ---: |
| Compiler source (`main.may` and `src/`) | 12 823 lines |
| Runtime sidecars (`native.may`, `runtime/`, `prelude.may`) | 4 501 lines |
| Target-only compiler and runtime files (listed under [Why](#why)) | 2 265 lines |
| `platform/` and `stdlib/ml/` Maylang | 4 582 lines |
| Compiler executable (`build/bin/mayc_new`) | 3 191 456 bytes |
| `sh compiler/rust/build.sh` (Rust → C → stage 1 → stage 2) | 40 s |
| `make test` | 677 s |
| `make test-bootstrap` | 70 s |
| CI `bootstrap.yml` on `main` (run 41107159389), wall time | 14 min 53 s |
| — `bootstrap` job | 13 min 29 s |
| — `core-emulation` job | 1 min 15 s |
| CI `maybrowser.yml` (run 41107159309) | 1 min 26 s |
| CI `native-targets.yml` (last success, run 40927832675) | 1 min 31 s |

## What "better" means meanwhile

With the scope reduced, work goes to the language on Linux x86-64, in this
order:

1. **Speed**: the [performance roadmap](PERFORMANCE_ROADMAP.md) (#101),
   starting with the algorithmic runtime fixes #97, #99 and struct layout #98.
2. **Correctness and robustness**: faults and recovery, the collector under
   sustained allocation, fuzzing the frontend, typed context instead of
   frontend globals (#49), prelude parity (#51).
3. **Language ergonomics**: features the strict language still lacks
   (hexadecimal and binary literals, destructuring in strict mode), `Map`
   keys of every type behaving as expected, clearer diagnostics.
4. **Standard library**: concrete types instead of `Any` signatures, complete
   modules with tests, documented contracts.
5. **Documentation and editors**: #100 (highlighting, docstring coverage and
   a single docstring standard), a repository that is `mayfmt`-clean,
   language server coverage (#52).

## Progress

| Step | State |
| --- | --- |
| 1 Baseline and triage | done: [baseline](#baseline), `frozen/README.md`, checks skip `frozen/` |
| 2 Platform experiments and ML | done; the ML examples (`ml_xor.may`, the ecosystem simulation) are frozen too |
| 3 CI and distribution | not started |
| 4 Compiler seams | not started |
| 5 Freeze targets | not started |
| 6 Documentation | not started |
| 7 Measure again | not started |
