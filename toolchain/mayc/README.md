# mayc compiler

`main.may` is the compiler entry point. Imported compiler modules live in
`src/`; runtime sidecars stay beside the entry point. Compiler tests and
bootstrap binaries are kept in `tests/` and `build/` respectively.

No compiler binary is checked in. Run `sh toolchain/rust/build.sh` from
the repository root to build from Rust and C source, or invoke `mayc_new` to
build automatically on first use. Rust and GCC or Clang are required for this
first build. Later invocations use the generated native compiler in
`build/bin/`. See the [bootstrap guide](../rust/README.md).

## Command line

```sh
toolchain/mayc/mayc_new --help
toolchain/mayc/mayc_new examples/hello.may
toolchain/mayc/mayc_new --check examples/strict.may
toolchain/mayc/mayc_new examples/strict.may --output /tmp/strict-example
toolchain/mayc/mayc_new --dump-expanded examples/strict.may
```

When `-o`/`--output` is omitted, mayc writes an executable alongside the source
with the final `.may` suffix removed. If the source has another suffix, `.out`
is appended. `--check` performs import expansion, parsing, strict type checking
and name resolution without writing an executable. `--legacy` opts into
dynamic legacy checking; `--strict` restores strict checking (the default).
`--raw` omits the runtime and standard libraries. `--dump-expanded` prints the
source after textual imports have been expanded and exits. `--version` reports
the self-hosted compiler identity. `--runtime full|core|none` selects the library
set; `none` is equivalent to `--raw`. The default is `full` on x86-64 Linux and
`core` on the other native targets. The experimental `clang-llvm` target defaults
to the full Maylang runtime. `--time` reports elapsed stage times to stderr.

`--diagnostics json` writes a schema-versioned diagnostics object to stderr.
Each diagnostic includes severity, stage, code, original file, message and a
1-based range whose columns count UTF-8 bytes. Independent top-level parser and
type errors recover up to a limit of 20; an error prevents executable emission.

`--debug` instruments user functions in full-runtime builds with source frames.
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
6. `backend.may` selects a `TargetBackend` with IR emission and relocation
   entry points. `backend/x86_64.may` implements the full dynamic runtime;
   `backend/arm64.may` and `backend/riscv.may` implement raw and core programs
   through the shared `CodeEmitter` contract in `backend/raw.may`. Platform
   primitives adapt the shared core runtime to Linux, Darwin or Windows.
7. `formats.may` computes an `ImageLayout` after code padding, then the
   backend applies relocations using that layout. `formats/elf.may`,
   `formats/macho.may`, and `formats/pe.may` write their respective images.
   Address bases, header sizes and file geometry belong to the format writers.

`emitter.may` owns an explicit `EmissionContext`: checked code, data and image
sinks, labels, fixups, symbols, frame allocation, runtime mode, and a snapshot
of the unit's IR and function records. The driver passes it through parsing,
IR lowering, emission, relocation, packaging and writing. Separate contexts
can be interleaved without sharing an output mapping or backend ABI labels.
The frontend still has mutable parsing/type-checking state and a source arena;
this change does **not** make the entire compiler or its GC runtime thread-safe.
Each sink is released after output is written. Capacity checks precede writes;
code, data and image limits are currently 16 MiB, 4 MiB and 32 MiB.

## Experimental Clang/LLVM target

`--target clang-llvm` lowers Maylang's linear `Quad` IR directly to textual
LLVM IR in `src/backend/llvm.may`. The backend also lowers the Maylang runtime,
using its tagged values and conservative garbage collector. Clang compiles the
`.ll` through its LLVM backend and links an x86-64 Linux executable. This path
requires no Rust compiler or generated C. `--emit-llvm` writes IR directly and
does not require Clang.

```sh
sh toolchain/rust/build.sh
toolchain/mayc/mayc_new --target clang-llvm examples/hello.may -o /tmp/hello-llvm
/tmp/hello-llvm
toolchain/mayc/mayc_new --target clang-llvm --emit-llvm examples/hello.may -o /tmp/hello.ll
python3 toolchain/mayc/tests/llvm.py
```

Executable compilation requires Clang, a linker (`ld`), and libc development
files. Set `CLANG` to an executable path or name to override PATH discovery.
Subprocesses inherit the compiler's environment. Paths may contain spaces.
Without `-o`, IR output replaces the final `.may` with `.ll`. Compilation and
link failures preserve existing executable outputs.

The experimental backend supports integer/float arithmetic, strings, lists/maps,
functions, shared captures, pipelines, loops, interpolation, imports, and
`may`/`otherwise`. It currently requires the full runtime on x86-64 Linux;
`--raw`, core/none runtimes, extern functions, and fibers are rejected.
`--check` does not require Clang. The regression script validates direct emission,
compiler invocation, and observable behavior against the native backend.

## Cross compilation

The compiler executable itself currently runs on x86-64 Linux. Target selection
is explicit and does not depend on the host:

| Target | Format | Supported programs |
| --- | --- | --- |
| `x86_64-linux` (default) | ELF64 | Full runtime, core runtime and `--raw` |
| `arm64-linux` | ELF64 | Core runtime and `--raw` |
| `riscv64-linux` | ELF64 | Core runtime and `--raw` (RV64IM) |
| `arm64-macos` | Mach-O ARM64 | Core runtime and `--raw`; sign on macOS |
| `x86_64-windows` | PE32+ | Core runtime with kernel32 imports and `--raw` |
| `clang-llvm` (experimental) | LLVM IR / ELF64 | Full runtime on x86-64 Linux; excludes FFI and fibers |

```sh
toolchain/mayc/mayc_new --target arm64-linux examples/hello.may -o hello-arm64
toolchain/mayc/mayc_new --target riscv64-linux examples/hello.may -o hello-riscv64
toolchain/mayc/mayc_new --target x86_64-windows examples/hello.may -o hello.exe
toolchain/mayc/mayc_new --target arm64-macos examples/hello.may -o hello-macos
# On macOS, before execution:
codesign --force --sign - hello-macos
```

The shared [`runtime/core.may`](runtime/core.may) uses the existing tagged ABI
for integers, booleans, nil, UTF-8 strings and lists. It supplies console output,
indexing and mutation, string comparison/search/split/join, integer arithmetic,
conversion and powers. [`runtime/corelib.may`](runtime/corelib.may) adds
`str`, `substring`, `trim`, `repeat`, `range`, `sum`, `clamp`, `gcd`, `lcm`,
`alloc` and `memcpy`. Case conversion is ASCII-only. Integer overflow and
division by zero print a diagnostic and exit with status 70.
Core heap chunks live until process exit, with a 256 MiB retained-heap cap.
Exhausting it prints `core heap limit exceeded` and exits with status 70. Use
the full collecting runtime for allocation-intensive, long-running programs.

Core allocation uses native heap chunks of at least 1 MiB, retained until
process exit. It has no garbage collector or individual free operation.
Closures, maps/records, floats, exceptions, fibers and FFI still require the
full x86-64 Linux runtime; core compilation diagnoses unsupported operations
before writing output. Use `--runtime core` on Linux for small portable programs
and lower compilation overhead. Deploy the `runtime/` directory beside the
compiler along with its full-runtime sidecars.

ARM64/RISC-V raw targets support integers, literal strings, globals and locals,
conditionals, loops, direct calls and tail self-calls, `addr`/`cstr`/literal `len`,
`ptr`, `load8/16/32/64`, `store8/16/32/64`, `exit`, and native `syscall`.
They currently allow eight function parameters, six syscall arguments and a
2000-byte frame. `syscall` numbers and flags are those of the **selected target**:
Linux ARM64/RISC-V use write=64, mmap=222, exit=93; Darwin uses write=4, exit=1.
`exit` chooses the target ABI automatically. The Windows raw target rejects
`syscall` and `exit`; its entry point returns to the Windows loader. The core
runtime implements exit, output and allocation through Windows imports.

Mach-O output uses `LC_UNIXTHREAD` and needs ad-hoc signing on Apple Silicon;
signing and native macOS/Windows launches have not been tested here. Core
execution on every target is checked with Unicorn, including partial writes,
multiple heap chunks, Windows imports and call alignment. This is cross
emission support; mayc itself still runs on x86-64 Linux.

```sh
python3 toolchain/mayc/tests/core_runtime.py --compiler toolchain/mayc/mayc_new --require-emulation
```

## Build performance

Compiler symbol spans are copied once and cached while their source storage
remains valid. Mutable heap strings bypass the cache. String-key maps use an
open-addressed index while retaining insertion order and existing equality for
other key types. GC sweep coalesces dead runs, reclaims the heap tail and places
small reusable blocks in size bins. Repetition uses binary doubling, and image
copying moves 32-bit words without losing bits through tagged integers.

After checking all source functions, IR lowering follows reachable direct calls
and closure labels, skipping unused library and user functions. Raw runtime
functions remain conservative roots because backends call helpers implicitly.
Function lookup uses a per-emission-context index. These changes reduce repeated
allocation, linear searches and emission work without adding a build cache.

The saved [build measurement](tests/backend/build-performance.json) uses
identical runtime/library sidecars for both compilers, measures complete
processes, compares functional output and runs each rebuilt compiler:

| Program | Previous compiler | Updated compiler |
| --- | ---: | ---: |
| Hello, full runtime | 1.088 s | 0.608 s |
| Features, full runtime | 1.134 s | 0.732 s |
| Compiler rebuild | 75.857 s | 5.954 s |
| Hello, core runtime | — | 0.131 s |

Hello/features/core numbers are medians of three runs. The compiler rebuild
uses one sample per version, giving a measured 12.74× improvement in this run.
No build cache is used. Use `--time` to inspect individual stages:

```sh
toolchain/mayc/mayc_new --time toolchain/mayc/main.may -o /tmp/mayc
python3 toolchain/mayc/tests/build_benchmark.py --compiler toolchain/mayc/mayc_new \
  --baseline /path/to/old/mayc --report /tmp/mayc-build-performance.json
```

`tests/runtime_maps.py` checks real string-hash collisions, ordered iteration,
replacement/removal, mixed key types, forced collections, byte copying and
symbol-cache behavior.

## Runtime performance

`src/regalloc.may` runs a shared basic linear-scan allocator over IR temporaries.
It expires inclusive live intervals, evicts the interval ending farthest away
when registers are full, and reuses stack homes after intervals expire. The
backends use four callee-saved registers: r12–r15 on x86-64, x19–x22 on ARM64,
and s2–s5 on RISC-V. Functions preserve the registers they use. Before x86 calls,
live register values are copied to stack homes for the conservative GC.

This is a conservative first implementation: values spanning control-flow or
exception boundaries, and values with multiple definitions, stay in private
stack homes. It does not split intervals or allocate named locals to registers.
`tests/regalloc.py` checks expiration, pressure spills, stack-home reuse,
loop-carried values, call preservation, and actual collections with live
arguments. Cross-target execution checks use Unicorn when available:

```sh
python3 toolchain/mayc/tests/regalloc.py --compiler toolchain/mayc/mayc_new
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
python3 toolchain/mayc/tests/benchmark.py --compiler toolchain/mayc/mayc_new
# Optional baseline compiler, with its original runtime sidecars:
python3 toolchain/mayc/tests/benchmark.py --compiler toolchain/mayc/mayc_new \
  --baseline /path/to/old/mayc --report /tmp/mayc-performance.json
```

`tests/backends.py` checks context isolation, a signed arithmetic Python oracle,
format headers, target errors, and execution of emitted programs when Unicorn
is installed. `--require-emulation` makes a missing emulator an error:

```sh
python3 toolchain/mayc/tests/backends.py --compiler toolchain/mayc/mayc_new
# In an environment with the Python unicorn package installed:
python3 toolchain/mayc/tests/backends.py --compiler toolchain/mayc/mayc_new --require-emulation
```

Strict typing is enabled by default. Use `--legacy` for untyped source and
`Any` for explicit dynamic boundaries. See the [strict language guide](../../docs/STRICT.md)
for signatures, typed loops, collections, migration and current limitations.
Import metadata, source origins and visibility checks share normalized absolute
module paths, including standard-library fallback paths. Relative and absolute
imports of the same path expand once. Public enum types and their variant
constructors are exported together; selective imports still require each name.
`tests/modules.py` checks these rules in strict and legacy modes, including
imports from outside the repository, private members and ambiguous names:

```sh
python3 toolchain/mayc/tests/modules.py --compiler toolchain/mayc/mayc_new
```

`diagnostics.may` formats source excerpts and caret spans.
Float literals are decoded once during compilation and emitted as binary64
bits with a fresh runtime box, avoiding repeated decimal parsing in hot loops.
`addr(Float)` exposes its payload for lossless serialization. The process API
returns tagged integer PIDs and checks wait failures and signal exit statuses.
`tests/float_literals.py` checks bit parity with the original literal path;
`tests/processes.py` validates process behavior. The ecosystem runner isolates
long allocation histories because the collector still has a reproducible
corruption issue under sustained workloads.

Run the bootstrap, feature regressions, ABI and diagnostics checks, all current
example/project entry points, and ELF validation with:

```sh
toolchain/mayc/tests/run.sh
```

The launcher obtains its initial native compiler from the Rust → C bootstrap.
The verifier rebuilds it as `build/bootstrap/mayc_v2_seed`, then checks three
successive native generations in `build/bootstrap/` for byte-identical output.
`python3 toolchain/rust/test.py` separately verifies the complete
source-only chain, including C stage 1 and convergence of native stages 2 and 3.

Additional runtime and language compliance regressions live in
[`tests/compliance`](../../tests/compliance/README.md). Run them with
`python3 tests/compliance/run.py` after bootstrapping. Verification artifacts
and reports are stored there as well.

The binary layouts and ABIs follow the primary specifications:
[Arm AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst),
[RISC-V ISA](https://riscv.github.io/riscv-isa-manual/snapshot/spec/),
[Apple Mach-O headers](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h),
[Microsoft PE/COFF](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format),
and the [Windows x64 calling convention](https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention?view=msvc-170).
