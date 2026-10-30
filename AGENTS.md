# AGENTS.md

Guidance for coding agents working in the Maylang repository. Read it before
changing code. It records how the repository actually behaves, including the
traps that are not obvious from the source. Human-oriented detail lives in
[CONTRIBUTING.md](CONTRIBUTING.md), [docs/REPOSITORY.md](docs/REPOSITORY.md) and
[docs/guide/DEVELOPMENT.md](docs/guide/DEVELOPMENT.md). When this file and the
code disagree, trust the code and fix this file.

## What this repository is

Maylang is an experimental, self-hosted language. The compiler `mayc` is
written in Maylang (`compiler/mayc/`) and emits native executables directly
(ELF, NXF, Mach-O and PE) without an assembler or linker. It is its own
toolchain: do not add backends that go through LLVM, an external assembler
or a C compiler (an experimental `clang-llvm` target was removed for this
reason). A small Rust crate
(`compiler/rust/crates/may_bootstrap`) compiles the compiler to C, which builds
the first native generation, so no binary compiler is checked in. Tools (`may`,
`mayfmt`, `maylsp`, `maypkg`), the standard library and the platform
experiments are also Maylang. The current version is in `RELEASE.json`.

Compiler development needs Linux x86-64 (WSL 2 works), Rust/Cargo, GCC or
Clang, Python 3.10+ and binutils (`readelf`). Run `make doctor` to check.

## Ground rules

- Run commands from the repository root unless a component's README says
  otherwise. `make help` lists the supported entry points.
- Preserve unrelated working-tree changes. Stage specific paths and never
  use `git add -A` or `git add .`.
- Do not commit generated output: `build/`, `target/`, `.may/`, compiled
  binaries, `node_modules/`, `__pycache__/` or machine-specific reports. The
  exception is a deliberately recorded measurement (see Performance work).
  `platform/maybrowser/maybrowser` is a tracked shell launcher, not a build
  artifact.
- Keep runtime sidecars with any copied compiler executable (see below).
- Report validation honestly: list the commands you ran, their results, and
  anything you skipped because a dependency was missing.
- Keep behavior changes separate from mechanical moves or reformatting so
  each can be reviewed.
- Do not edit, fix or test anything under `frozen/`. It is kept for later
  but not built or maintained; see [frozen/README.md](frozen/README.md).

## Repository map

| Path | Contents | Main check |
| --- | --- | --- |
| `compiler/mayc/` | Self-hosted compiler: `main.may` driver, `src/` frontend/IR/backends/formats, runtime sidecars, `tests/` | `make test-compiler test-compliance` |
| `compiler/rust/` | Source bootstrap (`build.sh`, `test.py`) and the Cargo workspace crates | `make test-rust test-bootstrap` |
| `tools/may/` | Workspace runner (`may.json`), task graph, verified artifact cache | `make test-tools` |
| `tools/mayfmt/`, `tools/shared/` | Formatter CLI and the formatter core shared with `may`/`maylsp` | `make test-tools` |
| `tools/maylsp/` | Language server; reuses `compiler/mayc/src/` | `make test-tools` or `make -C tools/maylsp test` |
| `tools/maypkg/` | Legacy `mayproj.json` manager; `src/fs.may` is shared by `may` and the installer | `make test-tools` |
| `stdlib/` | Library modules, `ui/` (native UI), experimental `ml/` | Compiler stdlib contracts, `make test-ui` |
| `platform/maybrowser/`, `platform/mayos/` | Browser and OS experiments | `make test-browser`; mayos Makefile |
| `dist/` | Packaging, installers, updates; tests in `dist/tests/` | `make test-distribution` |
| `tests/compliance/`, `tests/docs/`, `tests/ui/` | Cross-component suites only | `make test-compliance`, `test-docs`, `test-ui` |
| `examples/` | Single-file examples and complete projects | Run by `compiler/mayc/tests/verify.py` |
| `docs/` | `guide/`, `internals/`, `design/`, `history/`, generated `reference/` | `make check test-docs` |
| `editors/vscode/` | VS Code extension (TypeScript, grammar, snippets) | `make editor` |
| `scripts/` | `doctor.py`, `build_tools.py`, `check_repository.py` | `make check` |
| `frozen/` | Unmaintained code outside the Linux x86-64 focus ([frozen/README.md](frozen/README.md)) | None |

Component tests live beside their implementation. `tests/` holds only suites
that span components. Relative imports between siblings use
`../../<group>/<component>/` (for example `tools/maylsp` imports
`../../compiler/mayc/src/...`). The October 2026 re-layout renamed
`toolchain/` and `example_projects/`; the path migration table is in
[docs/REPOSITORY.md](docs/REPOSITORY.md#path-migration).

## Building the compiler

- `compiler/mayc/mayc_new` is a launcher script. On first use it runs
  `compiler/rust/build.sh`, which builds a Rust → C → native stage 1, then
  compiles a stage 2 into `compiler/mayc/build/bin/mayc_new`. After that the
  launcher only executes the cached binary.
- **After editing compiler sources (`compiler/mayc/main.may`, `src/**`), rebuild
  with `sh compiler/rust/build.sh` (or `make build`).** Otherwise you are
  testing the old compiler.
- **Runtime sidecars are read at compile time and need no rebuild:**
  `compiler/mayc/native.may`, the `compiler/mayc/runtime/` files
  (`fat.may`, `fat_linux.may`, `fat_core.may`, `fat_corelib.may`, `math.may`,
  `nodeos.may`) and `stdlib/prelude.may` are
  symlinked beside the cached binary, so edits apply to the next program you
  compile. They are still compiled into the compiler itself, so a sidecar
  change that the compiler relies on also needs a rebuild and a bootstrap
  check.
- The active full-runtime native library is `compiler/mayc/native.may`.
  `stdlib/native.may` is a byte-identical mirror read by the language server
  and the API docs. Edit the active copy, then
  `cp compiler/mayc/native.may stdlib/native.may`; `make check` fails while
  they differ.
- A copied compiler needs `native.may`, `prelude.may` and the `runtime/`
  directory next to it. The `runtime/fat*.may` files must be there; for
  `prelude.may`/`native.may`/`runtime/math.may`, `mayc` also tries their
  checkout locations two levels above the executable or under the current
  directory. Outside a checkout, missing
  sidecars are an error. `runtime/math.may` (shared float parsing, display and
  transcendentals) is loaded by every runtime with a library prelude.
- `--target x86_64-nodeos` routes every `syscall` site through a gate into
  `runtime/nodeos.may`, a Linux-syscall personality written in the raw subset
  ([docs/internals/NODEOS.md](docs/internals/NODEOS.md)). Its globals must be
  zero-initialized (runtime initializers never run) and it must not allocate
  from the Maylang heap. Running NodeOS images needs a NodeOS checkout:
  `make test-maylang` there boots them, and the compiler, in QEMU.
- `make build` additionally builds the tools into `build/dev/` and writes
  `build/dev/env.sh` (sets `PATH`, `MAYC`, `MAYLANG_STDLIB`). `make tools`
  rebuilds only the tools with `$(MAYC)`.
- Useful compiler flags: `--check` (parse, type and name checks with no output),
  `--dump-expanded` (source after import expansion), `--time` (stage timings),
  `--diagnostics json`, `--debug` (source traces), `--legacy` (untyped mode),
  `--target x86_64-nodeos|arm64-linux|riscv64-linux|arm64-macos|x86_64-windows`,
  `--runtime full|core|none`, and `--raw`. See
  [compiler/mayc/README.md](compiler/mayc/README.md) for the capability matrix.
- **A failed compile leaves any previous output file in place** (deliberately,
  as with GCC). Check the compiler's exit status before running the binary;
  a pipeline such as `mayc x.may -o x | head && ./x` hides the failure and runs
  a stale build.

## Commands

| Command | What it does |
| --- | --- |
| `make check` | Markdown link check, JSON/Python syntax, generated-reference freshness. Fast; run it for every change. |
| `make test` | `check` plus Rust, compiler, compliance, docs and distribution suites |
| `make test-rust` | `cargo test --offline --locked --workspace` |
| `make test-compiler` | `compiler/mayc/tests/verify.py --compiler $(MAYC)`: fixtures, diagnostics, CLI, strict types, modules, backends, regalloc, core runtime, GC, stdlib contracts, all example entry points, ELF checks |
| `make test-bootstrap` | `compiler/rust/test.py`: full source-only chain and byte-identical stages 2 and 3 (bootstrap fixpoint). Slow; run it for compiler or runtime changes. |
| `make test-compliance` | `tests/compliance/run.py`: runtime and coercion boundary cases |
| `make test-tools` | `may`, `mayfmt`, `maypkg` and `maylsp` suites |
| `make test-docs` | Compiles and runs the snippets in `docs/reference/EXAMPLES.md` and `docs/guide/STRICT.md` |
| `make test-ui`, `make test-browser` | Native UI/browser checks (X11/OpenGL/libcurl/duktape; see the doctor profiles) |
| `make test-limits` | GC pressure, capacity and codegen reports |
| `make test-all` | Everything, including optional integrations |
| `make editor` | `npm ci && npm run compile` in `editors/vscode` |
| `make package` | Builds a release bundle and installers, then tests the extracted bundle |

`MAYC=/abs/path/to/mayc make test-...` tests a specific compiler. Check optional
requirements with `python3 scripts/doctor.py --profile test|ui|browser|editor|package`.
Socket and window tests skip when unavailable; say so in your report.

## Choosing checks

| You changed | Run at least |
| --- | --- |
| Anything | `make check` |
| Compiler frontend, IR, sema or strict checker | rebuild, `make test-rust test-compiler test-compliance`; `make test-bootstrap` before merging |
| Backend or code generation | the above plus `python3 compiler/mayc/tests/raw_codegen.py --compiler compiler/mayc/mayc_new`, and core-target harnesses (`backends.py`, `core_runtime.py`; add `--require-emulation` when Unicorn is installed) |
| `native.may`, `prelude.may`, `runtime/` | `make test-compiler test-compliance` and the bootstrap fixpoint (`make test-bootstrap`) |
| `compiler/rust/**` | `make test-rust test-bootstrap` |
| `stdlib/**` | `make test-compiler` (stdlib contracts), regenerate docs (below), `make test-ui` for `stdlib/ui` |
| `tools/**` | `make test-tools` |
| `dist/**`, `scripts/**`, installer | `make test-distribution test-installer`; `make package` for bundle changes |
| `platform/maybrowser/**` | `make test-browser` |
| `editors/vscode/**` | `make editor` |
| Docs only | `make check test-docs` |
| An example project | build and run it, then `make test-compiler` if `verify.py` lists it |

## Adding tests

- **Compiler feature fixtures:** every `compiler/mayc/tests/*.may` file
  (except `mod_a.may`, `architecture.may` and `abi.may`) is compiled, run, and
  compared byte-for-byte with its entry in `compiler/mayc/tests/legacy_behavior.json`
  (exit code plus base64 stdout/stderr). A new fixture **must** get a matching
  entry, or the verifier fails with a `KeyError`. Generate the base64 from a run
  you have checked by hand.
- **Diagnostic fixtures:** invalid programs go in `compiler/mayc/tests/fail/`.
  Register each one in the `errors` dictionary in `architecture()` in
  `compiler/mayc/tests/verify.py`, with a message substring. The check also
  requires a caret excerpt, the file name in the error, and that no executable
  was written.
- **Area harnesses:** most compiler behavior is tested by Python scripts named
  after their area (`strict_types.py`, `modules.py`, `raw_codegen.py`,
  `regalloc.py`, `gc.py`, `reachability.py`, …) that take `--compiler`. Extend
  the closest one and add a new script to `verify.py` `main()` only for a new
  area. Cover both success and failure paths.
- **Example entry points:** `verify.py` `targets()` compiles and runs every
  top-level `examples/*.may` except `ui_showcase.may` with stdin
  `red fish blue fish\nred fish\n` (or `10\n` for `m_to_km.may`) and requires
  exit 0 (`selfhost_test.may` exits 42). A new top-level example must therefore
  finish non-interactively. Complete projects are an explicit list in
  `targets()`; add yours there if it should be verified.
- **Docs snippets:** each `- Title: `code`` bullet in
  `docs/reference/EXAMPLES.md` needs an expected-output entry in
  `tests/docs/run.py`. `docs/guide/STRICT.md` must keep exactly the number of
  ```` ```may ```` blocks asserted there.
- **Tools:** add cases to `tools/may/tests/run.py`, `tools/mayfmt/tests/run.py`,
  `tools/maypkg/tests/test_workflows.py` or `tools/maylsp/tests/test_lsp.py`.
- Tests assert observable behavior (output, exit status, files, protocol
  messages), not implementation details.

## Writing Maylang

Strict typing is the default. The [language reference](docs/reference/LANGUAGE.md),
[strict guide](docs/guide/STRICT.md), [runtime API](docs/reference/RUNTIME.md)
and [stdlib contracts](stdlib/CONTRACTS.md) are authoritative. In short:

- End statements with `;`. Functions need typed parameters, every path must
  `return` explicitly (a trailing expression is not a return), and you need
  `return;` in `-> Nil` functions. Add a `return` after loops even if they never
  exit, because return analysis is conservative.
- Conditions must be `Bool`. Use `bool(x)`/`truthy(x)` for dynamic truthiness.
- `let` is an immutable binding; `mut` is reassignable. Lists, maps and
  structs are shared references, so `let xs: List<Int> = []; push(xs, 1);` is fine.
- Use `List<T>`, `Map<K, V>`, `Option<T>`, `Result<T, E>`, `(A) -> R`. Bare
  `List`/`Map` annotations are invalid. Map indexing yields an optional value,
  so write `counts[k] ?? 0`.
- `Any` is an explicit dynamic boundary. Implicit narrowing from `Any` to a
  concrete type is rejected: convert with `str()`, `int()`, `float()`,
  `bool()`, or use generics.
- `struct Point { x: Int, y: Int }` is constructed positionally (`Point(3, 4)`)
  and fields are mutable. Enums are matched with
  `match (v) { Variant(a) => ..., _ => ... }`, and enum/Result matches must be
  exhaustive.
- Error handling uses `may { expr } otherwise { fallback }`, with `err.kind`,
  `err.message` and `err.stack` inside `otherwise`. `fail("msg")` raises.
  `return`, `break` and `continue` inside `may` remain control flow.
- **Not in the language:** hexadecimal literals (`0x10` is a name error) and
  destructuring in strict mode. Use `load8`/`store8` for byte work.
- Values of different types cannot be compared: strict mode rejects `Int` vs
  `Float` (write `0.0` or convert with `to_float`). On `Any` values `==` across
  types is `false`, `!=` is `true`, and ordering raises a `type` fault, so
  `Any`-typed numeric code must normalize with `to_float` before comparing.
- Values are fat on every runtime and target (16 bytes: a type word and a
  payload; [docs/design/FAT_VALUES.md](docs/design/FAT_VALUES.md)), so `Int`
  is signed 64-bit. `compiler/mayc/runtime/fat.may` is shared; its hosts are
  `fat_linux.may` (full runtime: collector, files, processes) and
  `fat_core.may` (core runtime, every target). Dynamic code is lowered by
  `src/backend/x86_64_fat.may` on x86-64 and `src/backend/raw_fat.may` on
  ARM64/RISC-V; runtime functions are raw code (`raw.may`, the x86-64 code
  generator) and take two words per value, returning the type word in
  `RTAG`. Raw mode uses native 64-bit words. On x86-64, all-`Int`/`Ptr`/`Bool`
  functions (`compiler/mayc/src/words.may`) compile as native-word functions
  and bitwise expressions are outlined into them. Overflow and division by
  zero raise catchable `arithmetic` faults (uncaught faults exit 70). `/`
  truncates toward zero and `%` has the dividend's sign.
- The compiler itself runs on fat values once built, but the Rust/C stage 1
  does not, so keep integer literals in compiler sources within ±2^60.
- Strings are UTF-8 and `len`/indexing count code points. For byte length use
  `byte_length` from `import "net";`, or `load64(addr(s) - 8)` as `net.may`
  does. `print` always appends a newline; for raw output use
  `syscall(1, 1, addr(s), bytes)`.
- Multi-line string literals are allowed. Interpolation is `"${expr}"`, and `\$`
  escapes a literal dollar sign.
- Imports: `import "src/x.may";`, `import "math" as math;`,
  `from "algo" import zip;`. Paths resolve relative to the importer first and
  then the stdlib. The same resolved file expands only once. A module that
  marks any declaration `pub` exports only its `pub` names.
- Maps, records, structs, enums and closures work in the core runtime on every
  native target, including recoverable faults, debug traces and cooperative
  fibers. Core supports Float/Float32 arithmetic, conversions, rounding,
  square roots, transcendentals and floating powers (pure binary64, identical
  bits on every target). Float display is shortest round-trip and parsing is
  correctly rounded everywhere. FFI and OS libraries still need the full x86-64
  Linux runtime.
- Many older files (and much of the compiler) use `Any`-typed signatures.
  Follow the style of the file you are editing; write new code with concrete
  types.

## Formatting and style

- Use four spaces for Maylang, Python and Rust; two spaces for TypeScript,
  JavaScript, YAML and `editors/vscode` JSON; tabs in Makefiles. Files are LF
  with a final newline (`.editorconfig`). Existing `may.json` files use four
  spaces.
- Use `snake_case` functions, variables and files, `PascalCase` types, and
  `UPPER_CASE` constants. Use `///` doc comments directly above declarations.
- `mayfmt` exists (`compiler/mayc/mayc_new tools/mayfmt/main.may -o /tmp/mayfmt`),
  but the repository is not mayfmt-clean; even `examples/hello.may` reports
  changes. **Do not run it over whole existing files.** Format only the code you
  write, or match the surrounding style by hand.
- Rust: `cargo fmt --all`. Builds use `--offline --locked`; keep `Cargo.lock`
  authoritative.
- Match the comment density, naming and idioms of neighbouring code.

## Generated documentation

- `docs/reference/` is mostly generated. `STDLIB.md`, `SYNTAX.md`, `RUNTIME.md`, the
  `stdlib/*.md` module pages and `inventory.json` come from source declarations,
  `docs/reference/descriptions.json` and `tools/maylsp/docs/reference.json`.
  `LANGUAGE.md`, `TOOLCHAIN.md` and `EXAMPLES.md` are edited by
  hand.
- Every reference page is list-only: each nonblank line is a top-level
  `- ` bullet, with no headings, tables or fenced code.
- After adding, removing or changing a stdlib/native declaration, add its
  description to `descriptions.json` (coverage is enforced), then run
  `python3 docs/reference/generate.py` and `python3 tools/maylsp/docs/generate.py`
  and commit the regenerated files. `make check` runs both with `--check`.
- `scripts/check_repository.py` validates every relative Markdown link in
  tracked and untracked files, so moved files break links in other documents.
- Update the guide or README for any user-visible behavior change.

## Projects and examples

- New applications use a [`may` workspace](tools/may/README.md): `may.json` with
  `app`, `test` (`.test.may` files), `native` and `task` targets. The root
  `.gitignore` ignores every `.may/` cache. `may migrate` converts a
  `mayproj.json`.
- `maypkg` and `mayproj.json` are legacy. Existing projects still use them, but
  do not start new ones that way. `mayproj.lock` keys are paths relative to the
  project root (`../` for stdlib dependencies); `maypkg` still reads older
  absolute-path lockfiles. Relock after changing modules, and run `maypkg`
  with `PWD` set to the project directory, as the Makefiles do.
- Build `may` with `compiler/mayc/mayc_new tools/may/main.may -o /tmp/may` and
  `export MAYC="$PWD/compiler/mayc/mayc_new"`, or use `build/dev/bin/may` after
  `make build`. Useful commands: `may run -- ARGS`, `may build TARGET`,
  `may test`, `may check`, `may tasks`, `may clean`.
- Multi-file projects keep the entry point and manifest at the root, modules
  in `src/`, tests in `tests/` and outputs in `build/` or `.may/`. Link new
  projects from `examples/README.md` and `docs/reference/EXAMPLES.md`.

## Performance work

- Performance claims need a measured, reproducible report. Backend reports live
  in `compiler/mayc/tests/backend/` as a Markdown write-up plus the raw JSON
  samples (see `raw-call-gaps.md`). The tools have `PERFORMANCE.md` files.
- Use the existing harnesses: `compiler/mayc/tests/benchmark.py`,
  `build_benchmark.py`, `raw_performance.py`, `limits.py`, and
  `tools/may/tests/benchmark.py`. Record medians, sample counts, baseline
  compiler/sidecar identity and output equality. Timings do not gate CI.
- Optimizations must preserve evaluation order, effects and faults. Add
  oracle tests that compare against unoptimized behavior.

## Git, commits and pull requests

- Commit subjects follow `type(scope): imperative summary`. Types are
  `feat`, `fix`, `perf`, `test`, `docs`, `refactor`, `chore`, `revert`.
  Common scopes: `compiler`, `codegen`, `raw`, `raw/x86_64`, `runtime`,
  `stdlib`, `gc`, `maylsp`, `may`, `maypkg`, `ui`, `distribution`, `targets`,
  `compliance`, `examples`, `release`. A bare `docs:` or `feat:` is fine for
  cross-cutting work.
- Bodies explain the mechanism and its limits, and mention added tests.
  Reference issues with `Refs #N` or close them with `Closes #N`/`Fixes #N`.
- Branches are named `type/short-slug` (for example `perf/raw-extended-gaps`
  or `refactor/repo-layout`). Commit only when asked, and branch before
  committing if you are on `main`.
- Keep commits focused. A typical feature or optimization series is the
  change plus its tests, followed by a separate `docs(...)` commit that records
  measurements and updates `CHANGELOG.md`.
- Add user-visible changes to the `# Unreleased` section at the top of
  `CHANGELOG.md`, with issue/PR numbers and links to reports where relevant.
- PRs follow [.github/pull_request_template.md](.github/pull_request_template.md):
  describe the problem and the resulting behavior, list the checks actually
  run with their results, state skips, and attach screenshots or measurements
  where relevant. Open a draft while checks or design questions are open. Use
  `gh ... --body-file` for long bodies. Issue labels are described in
  [CONTRIBUTING.md](CONTRIBUTING.md#report-bugs-and-propose-work).
- Releases (version in `compiler/mayc/main.may` `MAYC_VERSION`,
  `RELEASE.json`, the README badge and `editors/vscode/package*.json`, plus
  the changelog) follow [docs/guide/RELEASING.md](docs/guide/RELEASING.md).
  Do not bump versions as part of ordinary changes.

## CI

`.github/workflows/`: `bootstrap.yml` runs `make check` and
`make test-distribution` as a quick `repository` job, then the source-only
bootstrap, Rust tests, compiler verification, UI under X11, compliance,
packaging and the editor; it also has optional core-emulation and performance
jobs. `native-targets.yml` runs real Windows/macOS loaders. `maybrowser.yml`
runs the browser suite under Xvfb. `release.yml` runs `bootstrap.yml` on a
tag, then packages and publishes. CI uses Ubuntu 24.04 and Node 22.

## Known hazards

- **GC corruption under sustained allocation** ([#2](https://github.com/mirged/maylang/issues/2)).
  Long-running, allocation-heavy programs can crash in the full runtime.
  Prefer preallocated lists of integers in hot loops. A crash in a long
  workload may be this bug rather than your change, so reproduce it before
  blaming the change.
- **Heap tests rewrite one line:** harnesses shrink the full runtime's heap
  by replacing `mut sz: Any = 268435456;` in `runtime/fat_linux.may`, and
  the core heap limit by replacing `CORE_RETAINED + size > 268435456` in
  `runtime/fat_core.may`. Keep those exact texts unique; the reservation
  (four times `sz`, so the collection threshold can grow) is derived from it.
- **Source size limits:** each source file is limited to 1 MiB and the
  expanded import closure to 4 MiB; both are rejected with an error, not
  truncated (#37, #38). The 256 MiB source arena is bounded and can be resized
  with `MAYC_ARENA_BYTES` (#39).
- The compiler's frontend uses mutable global state
  ([#49](https://github.com/mirged/maylang/issues/49)). It is not thread-safe or
  re-entrant across compilation units.
- Two `native.may` files exist; edit `compiler/mayc/native.may` and copy it to
  the `stdlib/` mirror.
- `make test-compiler` has been seen to fail intermittently in
  `raw_codegen.py` (an `idiv` for a division by 2^31 that should use shifts),
  including on unmodified `main`, while the script and `verify.py` pass when
  run directly. Rerun the script directly before treating that failure as a
  regression.
- A stale `compiler/mayc/build/bin/mayc_new` hides compiler source edits until
  you rebuild.
- Open findings and their priorities are tracked in [ROADMAP.md](ROADMAP.md)
  and [docs/AUDIT.md](docs/AUDIT.md). Link a known issue rather than filing a
  duplicate.
