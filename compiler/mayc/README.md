# mayc compiler

`main.may` is the compiler entry point. Imported compiler modules live in
`src/`; runtime sidecars stay beside the entry point. Compiler tests and
bootstrap binaries are kept in `tests/` and `build/` respectively.

No compiler binary is checked in. Run `sh compiler/rust/build.sh` from
the repository root to build from Rust and C source, or invoke `mayc_new` to
build automatically on first use. Rust and GCC or Clang are required for this
first build. Later invocations use the generated native compiler in
`build/bin/`. See the [bootstrap guide](../rust/README.md).

## Command line

```sh
compiler/mayc/mayc_new --help
compiler/mayc/mayc_new examples/hello.may
compiler/mayc/mayc_new --check examples/strict.may
compiler/mayc/mayc_new examples/strict.may --output /tmp/strict-example
compiler/mayc/mayc_new --dump-expanded examples/strict.may
```

When `-o`/`--output` is omitted, mayc writes an executable alongside the source
with the final `.may` suffix removed. If the source has another suffix, `.out`
is appended. `--check` performs import expansion, parsing, strict type checking
and name resolution without writing an executable. `--legacy` opts into
dynamic legacy checking; `--strict` restores strict checking (the default).
`--raw` omits the runtime and standard libraries. It aligns function
bodies and loop heads to 16 bytes with NOP padding; `--no-code-align` turns that
off for layout experiments. `--dump-expanded` prints the
source after textual imports have been expanded and exits. `--version` reports
the self-hosted compiler identity. `--runtime full|none` selects the library
set; `full` is the default and `none` is equivalent to `--raw`. `--time` reports elapsed stage times to stderr.

Individual input files, including imports, are limited to 1 MiB. The compiler
rejects larger files with an error instead of compiling a truncated prefix.
The expanded import closure (every imported file, once) is limited to 4 MiB;
exceeding it reports the line being copied and each import that led to it.
Source bytes and other raw frontend buffers live in a bounded arena of 256 MiB.
The compiler reports an error when the arena cannot be mapped or is exhausted;
set `MAYC_ARENA_BYTES` (4096 to 1099511627776) to choose another size.

`--diagnostics json` writes a schema-versioned diagnostics object to stderr.
Each diagnostic includes severity, stage, code, original file, message and a
1-based range whose columns count UTF-8 bytes. Independent top-level parser and
type errors recover up to a limit of 20; an error prevents executable emission.
Schema 1 clients should ignore unknown object keys. Incompatible changes to
field meanings or coordinate units require a schema-version change. Stage codes
such as `E_PARSE` and `E_TYPE` identify categories rather than unique errors.
LSP consumes the same records and converts byte columns to its UTF-16 positions.

`--debug` instruments user functions with source frames.
Uncaught faults print the captured trace; caught faults expose it in `err.stack`.
Frames name the function and its declaration location, rather than every call
site. Tail calls keep bounded trace depth, handlers restore unwound frames, and
cooperative fibers retain independent traces. Storage holds 1024 frames and
snapshots show at most 64. This is error tracing, not a DWARF debugger interface.

`main.may` expands imports and drives a staged compiler:

1. `lexer.may` emits source-positioned `Token` structs.
2. `parser.may` parses with a Pratt expression parser into named variants in
   `ast.may`; it does not emit target instructions.
3. `strict.may` requires explicit types and returns and checks signatures, generics,
   collections, nominal records and assignments before code generation.
4. `sema.may` resolves nested scopes, rewrites local bindings to unique names,
   checks mutability and supported concrete annotations, and computes closure
   environments.
5. `ir.may` lowers syntax into linear `Quad` records with virtual values,
   branches, labels, calls, and handler operations. It also folds safe integer
   constants and removes unreachable statements after unconditional exits.
   Before lowering, `words.may` marks functions whose parameters, result,
   locals and operations are all `Int`, `Ptr` or `Bool` (including
   `load*`/`store*`);
   the backend lowers them like raw
   code and emits 64-bit words, checked arithmetic and a fat entry that checks
   the arguments' type words.
6. `backend.may` selects the `TargetBackend` with IR emission and relocation
   entry points. `backend/x86_64.may` emits raw code and runtime functions;
   `backend/x86_64_fat.may` lowers dynamic code on fat values.
7. `formats.may` computes an `ImageLayout` after code padding, then the
   backend applies relocations using that layout. `formats/elf.may` writes
   the image; address bases, header sizes and file geometry belong to it.

`emitter.may` owns an explicit `EmissionContext`: checked code, data and image
sinks, labels, fixups, symbols, frame allocation, runtime mode, and a snapshot
of the unit's IR and function records. The driver passes it through parsing,
IR lowering, emission, relocation, packaging and writing. Separate contexts
can be interleaved without sharing an output mapping or backend ABI labels.
The frontend still has mutable parsing/type-checking state and a source arena;
this change does **not** make the entire compiler or its GC runtime thread-safe.
Each sink is released after output is written. Capacity checks precede writes;
code, data and image limits are currently 16 MiB, 4 MiB and 32 MiB.

## One toolchain

mayc writes every executable itself: it emits machine code and the ELF
container directly, with no assembler, linker, C compiler or
LLVM. An experimental `clang-llvm` target that lowered the IR to LLVM IR was
removed in favor of this; `--target clang-llvm` and `--emit-llvm` now fail
with an explanation.

## Target and runtimes

The compiler runs on x86-64 Linux and emits x86-64 Linux ELF64 executables.
That is the only supported target for now: `--target x86_64-nodeos`,
`arm64-linux`, `riscv64-linux`, `arm64-macos` and `x86_64-windows` and
`--runtime core` fail with an error. Their backends, formats and runtimes are
[frozen](../../frozen/README.md) ([why](../../docs/design/LINUX_X86_64_FOCUS.md)).

| Capability | Full runtime (default) | `--raw` / `--runtime none` |
| --- | --- | --- |
| Integers, booleans, direct functions and control flow | Yes | Yes |
| Allocated UTF-8 strings and lists | Yes | Literal strings and pointer operations |
| Maps, records, structs and enums | Yes | Use raw storage/operations |
| Closures, shared captures and higher-order calls | Yes | No injected callable runtime |
| Float literals, arithmetic, conversions and Float32 | Yes | Use raw storage/operations |
| Transcendentals and floating-point powers | Yes (portable trig; x87 logs/exp/pow) | Use raw storage/operations |
| Recoverable faults and source traces | Yes; uncaught faults exit 70 | No injected runtime |
| Cooperative fibers | Yes | No injected scheduler |
| Typed extern functions | Yes | No full-runtime ABI |
| File/process/network libraries | Yes | Explicit Linux syscalls |
| Heap lifetime | Conservative GC | Program manages raw allocations |

The full runtime is [`runtime/fat.may`](runtime/fat.may) with its Linux host
[`runtime/fat_linux.may`](runtime/fat_linux.may) (collector, files,
processes). `runtime/math.may` is loaded with the library prelude and holds
the shared binary64 code:

- Display (`str`, `print`, nested values) prints the shortest digits that parse
  back to the same value, like Python's `repr`, in Maylang's layout (`1e20`,
  `0.30000000000000004`, `-0.0`); nonfinite values print as `nan`, `inf` or
  `-inf`. `float(text)`, JSON numbers and float literals are correctly rounded.
- `sin`, `cos` and `tan` reduce arguments of any finite magnitude exactly.
  `ln`, `log2`, `log10`, `exp` and floating `pow`/`**` use x87 sequences.
  Every result is within one ulp of a correctly rounded result, and zeros,
  infinities, NaN and negative bases follow C99 `pow`/`exp`. The `pow` builtin
  always returns a Float, while `**` keeps integer powers exact.

Deploy `native.may`, `prelude.may` and the `runtime/` directory beside a
copied compiler.

`syscall` uses Linux x86-64 numbering. In `--raw` code, frames are limited to
2000 bytes and syscalls accept six arguments.

## Build performance

Compiler symbol spans are copied once and cached while their source storage
remains valid. Mutable heap strings bypass the cache. String-key maps use an
open-addressed index while retaining insertion order and existing equality for
other key types. GC sweep coalesces dead runs, reclaims the heap tail and places
small reusable blocks in size bins. Repetition uses binary doubling, and image
copying moves 32-bit words.

After checking all source functions, IR lowering follows reachable direct calls
and closure labels, skipping unused library and user functions. Runtime IR stays
available for implicit backend calls, but emission starts at main and follows a
deduplicated function worklist. Native code relocations retain exactly the helpers they reference, including GC, exceptions,
closures and ABI trampolines. Unused functions, their literals and ELF symbols
are omitted. The native fiber switch is emitted only when referenced.

Unused foreign declarations receive normal type/name checks but do not allocate
loader slots or introduce library/symbol dependencies. Top-level and imported
initialization still execute, and every declaration is checked before pruning.
Function lookup uses a per-emission-context index; original function labels use
constant-time worklist membership. This reduces emission work without a build
cache or a duplicate table of implicit runtime dependencies.

The [reachability measurement](tests/backend/reachability-performance.json)
records identical sidecars, three sequential samples and matching program output:

| Program | Before image | Pruned image | Reduction |
| --- | ---: | ---: | ---: |
| Hello, full runtime | 252,864 bytes | 133,088 bytes | 47.4% |
| Features, full runtime | 314,072 bytes | 207,216 bytes | 34.0% |

Observed compilation medians were 1.063s -> 0.608s for hello and 0.983s -> 0.762s
for features. These are local measurements without timing gates. This comparison
uses `--skip-rebuild`: the older compiler exhausted its fixed runtime heap when
rebuilding the updated compiler source, so no rebuild speedup is claimed. The
updated compiler rebuilds successfully and the default benchmark still measures
and executes a full rebuild.

The earlier [build measurement](tests/backend/build-performance.json) uses
identical runtime/library sidecars for both compilers, measures complete
processes, compares functional output and runs each rebuilt compiler:

| Program | Previous compiler | Updated compiler |
| --- | ---: | ---: |
| Hello, full runtime | 1.088 s | 0.608 s |
| Features, full runtime | 1.134 s | 0.732 s |
| Compiler rebuild | 75.857 s | 5.954 s |

Hello/features numbers are medians of three runs. The compiler rebuild
uses one sample per version, giving a measured 12.74× improvement in this run.
No build cache is used. Use `--time` to inspect individual stages:

```sh
compiler/mayc/mayc_new --time compiler/mayc/main.may -o /tmp/mayc
python3 compiler/mayc/tests/build_benchmark.py --compiler compiler/mayc/mayc_new \
  --baseline /path/to/old/mayc --report /tmp/mayc-build-performance.json
```

Omit `--baseline` to record the current compiler's timings without a comparison.
Use `--skip-rebuild` with a baseline to compare example codegen only; the report
records zero rebuild samples and excludes a compiler rebuild speedup.
The report also records compiler/sidecar hashes and image sizes. The optional
`performance` CI job runs this mode on manual workflow dispatches and uploads
`build-benchmark.json`; timings do not gate pull requests.

`tests/runtime_maps.py` checks real string-hash collisions, ordered iteration,
replacement/removal, mixed key types, forced collections, byte copying and
symbol-cache behavior.

`tests/reachability.py` executes retained calls, function values, captures,
recursion, initialization and errors, checks unused code/literals and foreign
loader entries, and inspects stripping of raw programs.

## Runtime performance

Use `make test-limits` for retained GC/codegen experiments, or run
[the limits runner](tests/limits/README.md) directly. It keeps generated sources,
executables, assembly, symbol statistics and resource measurements.
The [signed constant-division report](PERFORMANCE_LIMITS.md) records a measured
optimization discovered with these workloads and its raw timing samples.

`src/regalloc.may` runs a shared basic linear-scan allocator over IR temporaries.
It expires inclusive live intervals, evicts the interval ending farthest away
when registers are full, and reuses stack homes after intervals expire. The
backend uses four callee-saved registers, r12–r15. Functions preserve the
registers they use. Before x86 calls,
live register values are copied to stack homes for the conservative GC.

This is a conservative first implementation: values spanning control-flow or
exception boundaries, and values with multiple definitions, stay in private
stack homes. It does not split intervals or allocate named locals to registers.
`tests/regalloc.py` checks expiration, pressure spills, stack-home reuse,
loop-carried values, call preservation, and actual collections with live
arguments:

```sh
python3 compiler/mayc/tests/regalloc.py --compiler compiler/mayc/mayc_new
```

The x86-64 backend emits guarded integer arithmetic/comparisons directly.
Non-integer operands, overflow and division by zero retain the runtime path,
including caught arithmetic errors. Signed division and remainder by positive
constant powers of two use sign bias and shifts/masks; negative operands still
truncate toward zero. This also removes divisions from the runtime's `% 8` tag
checks. Allocation skips the freelist function call when the list is empty.

The reproducible workload in `tests/backend/bench.may` runs Collatz for seeds
1 through 50000 (5,025,114 steps), allocates 20000 three-element lists, and
prints the checksums `5025114 400020000`. This gives a concrete workload for the
reported timing, whose exact source was not supplied. The saved local
[measurement](tests/backend/performance.json) records median times of 318.065 ms
before the change, 41.634 ms after it (7.64× faster), and 290.512 ms for Python,
with nine measured runs per executable. The harness excludes
compilation, includes process startup, checks output on every run, and reports
medians after one warm-up:

A separate [allocator comparison](tests/backend/regalloc-performance.json)
measured 55.057 ms before register allocation and 52.499 ms after it, with nine
runs each. These samples overlap substantially; the small median improvement
should be treated as noisy, rather than a reliable speedup estimate.

```sh
python3 compiler/mayc/tests/benchmark.py --compiler compiler/mayc/mayc_new
# Optional baseline compiler, with its original runtime sidecars:
python3 compiler/mayc/tests/benchmark.py --compiler compiler/mayc/mayc_new \
  --baseline /path/to/old/mayc --report /tmp/mayc-performance.json
```

`tests/backends.py` checks context isolation, relocations, a signed
arithmetic Python oracle and target diagnostics:

```sh
python3 compiler/mayc/tests/backends.py --compiler compiler/mayc/mayc_new
```

Strict typing is enabled by default. Use `--legacy` for untyped source and
`Any` for explicit dynamic boundaries. See the [strict language guide](../../docs/guide/STRICT.md)
for signatures, typed loops, collections, migration and current limitations.
Import metadata, source origins and visibility checks share normalized absolute
module paths, including standard-library fallback paths. Relative and absolute
imports of the same path expand once. Public enum types and their variant
constructors are exported together; selective imports still require each name.
`tests/modules.py` checks these rules in strict and legacy modes, including
imports from outside the repository, private members and ambiguous names:

```sh
python3 compiler/mayc/tests/modules.py --compiler compiler/mayc/mayc_new
```

`diagnostics.may` formats source excerpts and caret spans.
Float literals are decoded once during compilation and emitted as binary64
bits with a fresh runtime box, avoiding repeated decimal parsing in hot loops.
Floats are unboxed payloads (`math.may` reads their bits with intrinsics). The
process API returns integer PIDs and checks wait failures and signal exit statuses.
`tests/float_literals.py` checks bit parity with the original literal path;
`tests/processes.py` validates process behavior. The collector still has a
reproducible corruption issue under sustained workloads (#2).

Run the feature regressions, area harnesses, ABI and diagnostics checks, all
current example/project entry points, and ELF validation with:

```sh
make test-compiler
```

The launcher obtains its initial native compiler from the Rust → C bootstrap.
`make test-bootstrap` (`compiler/rust/test.py`) verifies the complete
source-only chain, including C stage 1 and byte-identical native stages 2 and 3.

Additional runtime and language compliance regressions live in
[`tests/compliance`](../../tests/compliance/README.md). Run them with
`python3 tests/compliance/run.py` after bootstrapping. Verification artifacts
and reports are stored there as well.

The source-only workflow keeps source convergence, compiler/library checks,
project workflows, LSP, extracted installation and compliance in `bootstrap`.
Editor packaging runs in `editor`. The optional `performance` job uses
`continue-on-error`, so a failing measurement does not fail the required
checks. Branch protection can require `bootstrap` and `editor`.
