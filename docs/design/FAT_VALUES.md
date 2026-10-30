# Fat values

Status: done. Every runtime and target uses fat values; the 3-bit tagged
encoding, its runtimes and the `--values` option were removed
([#92](https://github.com/mirged/maylang/issues/92)). The ledger at the end
records the steps.

## Problem

Every dynamic value is one 64-bit word whose low three bits are its type:
`n << 3` for Int, `ptr | 1` for Str, `ptr | 5` for List, `ptr | 7` for Map,
2, 3 and 4 for nil, false and true, and boxed floats. Closures are tag-0
words that the runtime tells apart from integers by looking them up in the
heap. The consequences are the ones #92 lists: Int has 61 bits, raw
addresses must be scaled at every untagged boundary, heap pointers must be
8-byte aligned, the collector decodes `address * 8` integers as possible
pointers, and every typed boundary pays shifts and masks.

Native-word functions ([STRICT.md](../guide/STRICT.md)) already compute with
machine words where the types are concrete. Fat values remove the tag bits
from the dynamic representation itself.

## Representation

A value is 16 bytes: a 64-bit type word followed by a 64-bit payload.

| Type word | Name | Payload |
| --- | --- | --- |
| 0 | Nil | 0 |
| 1 | Bool | 0 or 1 |
| 2 | Int | signed 64-bit integer |
| 3 | Float | IEEE binary64 bits (no box) |
| 4 | Str | pointer to `{ length, bytes..., 0 }` |
| 5 | List | pointer to `{ length, capacity, elements }` |
| 6 | Map | pointer to the insertion-ordered map record |
| 7 | Closure | pointer to `{ code, environment, arity }` |
| 8 | Cell | pointer to one value (captured mutable local) |

Zeroed memory is nil, so fresh slots, globals and list capacity need no
initialization. Types 4 to 8 are heap references; no other payload is ever
treated as one. Payload pointers have no alignment requirement and Int and
`Ptr` payloads are full machine words, so `load64`, `addr` and C results
cross into dynamic code unchanged.

List elements, map keys and values, closure environments, cells and globals
are stored as 16-byte values.

## Collector

The collector stays a non-moving mark-sweep. Each allocation records its
kind in the existing allocation-identity byte map: bytes (strings, buffers;
never scanned), values (an array of 16-byte values; a payload is traced when
its type word is a heap type, and an Int payload is checked conservatively,
since a `Ptr` from `cstr` or `addr` may be the only reference to a heap
block) or words (runtime-internal pointer tables; scanned conservatively). Stacks and registers are still scanned
conservatively, accepting a word that equals an object start or the byte
pointer `addr` returns. The `address * 8` decoding disappears.

## Calling conventions

- Compiled functions receive a pointer to their argument values and the
  argument count, plus the closure environment, and return the payload in
  the first return register and the type word in the second.
- Runtime functions are written in the raw subset. Each value argument
  becomes two word parameters, type word first; a value result returns its
  payload and leaves its type word in the `RTAG` global, which the caller
  reads immediately after the call. Raw code calls compiled closures with
  `__fat_apply(closure, argv, argc)` and computes on Float bits with
  `__fbits(op, a, b)`.
- Native-word functions keep their machine-word ABI. Their tagged entry
  becomes a fat entry that checks the type words and needs no shifts.

## Migration

The new representation is built beside the old one behind
`--values fat`, starting with the full runtime on x86-64 Linux, so every
commit keeps the default build and the bootstrap fixpoint green. Progress is
measured with the existing feature fixtures and their recorded outputs
(`compiler/mayc/tests/legacy_behavior.json`). Then the core runtime and the
ARM64 and RISC-V backends follow, the default changes, the compiler
bootstraps itself on fat values, and the tagged runtime is deleted.

Observable changes once fat values are the default: `Int` is 64-bit
everywhere, so values between 2^60 and 2^63 no longer fault; `value_tag`
keeps reporting the 3-bit tag numbers during the migration, for library
compatibility; a `List<Any>` uses 16 bytes per element. Until the compiler
itself runs on fat values, source integer literals stay within ±2^60.

## Core runtime and portable backends

The core runtime (every target, no collector, FFI or operating-system
libraries) and the ARM64 and RISC-V backends still use tagged values. They
move to fat values in four steps, each green on its own:

1. **Split the fat runtime by host.** `runtime/fat.may` keeps what every
   target shares: errors, strings, lists, maps, closures, operators,
   numbers, collections, closure calls and fibers. A host file supplies the
   heap, output, exit and fiber stacks: `runtime/fat_linux.may` (the
   collector, mmap, files, processes, time and externs) for the full
   runtime, `runtime/fat_core.may` (chunks from `__host_alloc` kept until
   exit, `__host_write`, `__host_exit`, arenas and the `core_heap_*`
   functions) for the core runtime. Both load the same library
   (`prelude.may`, `native.may`, `math.may`), so the core runtime stops
   carrying its own copies in `core.may` and `corelib.may`; a reachable
   function that needs an operating-system primitive is reported as needing
   the full runtime.
2. **x86-64 core targets** (`x86_64-windows`, and `--runtime core` on
   x86_64-linux and NodeOS) compile with the fat x86-64 backend; its
   `exit` and syscall builtins go through the host primitives.
3. **ARM64 and RISC-V.** `backend/raw.may` gains a fat lowering for dynamic
   code: every temporary and local has a 16-byte frame slot, an expression
   leaves its payload in logical register 0 and its type word in a new
   logical register, and runtime calls pass two argument registers per
   value. The raw subset's `__fbits` and `__fat_apply` builtins get
   portable implementations, since the runtime uses them.
4. **Remove tagged values.** Fat values become the only representation:
   `runtime.may`, `core.may`, `corelib.may`, the tagged x86-64 code
   generator paths, `--values` and `MAYC_VALUES` go away, and the raw
   subset no longer scales addresses.

## Ledger

| Step | State |
| --- | --- |
| Design and ABI | this document |
| Fat runtime and x86-64 backend (first behind `--values fat`) | done (`runtime/fat.may` with `runtime/fat_linux.may`, `backend/x86_64_fat.may`); Int arithmetic, comparisons and list indexing inline, other operators call the runtime |
| Feature fixtures passing with `--values fat` | 46 of 46 (`compiler/mayc/tests/fat_values.py`); `bitwise.may` differs only where Int no longer overflows |
| Prelude, native library, math and stdlib | loaded; floats are unboxed, `math.may` bit helpers are intrinsics |
| Fibers, handlers, debug traces | working |
| Typed externs and native-word entries | working; native code calls externs through their fat entry |
| Self-hosting on fat values | the compiler built with `--values fat` emits byte-identical output and rebuilds itself identically (`fat_values.py`) |
| Default on x86_64-linux, bootstrap fixpoint | done; integer literals follow the target (±2^63 fat, ±2^60 tagged) |
| NodeOS | done: the full runtime is fat by default; `exec` and `system` fall back to the personality's spawn extension; the compiler runs and rebuilds itself on NodeOS |
| Runtime split by host (step 1) | done: `runtime/fat.may` makes no syscalls; `runtime/fat_linux.may` is the full runtime's host |
| x86-64 core runtime (step 2) | done on x86_64-linux, x86_64-windows and NodeOS (`runtime/fat_core.may`, `runtime/fat_corelib.may`); the core runtime loads `prelude.may` and `native.may`, so its programs print what the full runtime prints, including identity list equality and `kind: message` faults (`core_runtime.py`) |
| ARM64, RISC-V (step 3) | done on arm64-linux, riscv64-linux and arm64-macos (`backend/raw_fat.may`): 16-byte frame slots, the payload and type word in logical registers 0 and 1, compiled functions take an argument pointer and count and pad missing parameters with nil, runtime calls pass two words per value; `__fbits` and `__fat_apply` have portable implementations, and ARM64/RISC-V frames and offsets beyond 12 bits are supported. Every portable program and compatible feature fixture prints the same on all five targets. Native-word functions are not used there yet |
| Fat default everywhere, tagged runtime removed (step 4) | done: fat values became the default for every runtime and target, then `runtime.may`, `runtime/core.may`, `runtime/corelib.may`, `--values` and `MAYC_VALUES` were removed, along with the tagged dynamic lowering in `backend/raw.may` and `backend/x86_64.may` (about 1,900 lines; the compiler is 3.19 MB). The LLVM backend was removed instead of ported. Removing tagged values found a collector gap: a `Ptr` held only in a heap value was not traced (`gc_stress.py`). Left for later: native-word functions on ARM64/RISC-V, dead native-word extern paths (`word_foreign` now always declines) and the `FAT_VALUES` flag, which now means "has a runtime" |
| Fat code size | temporaries defined once and read before the next boundary share reused frame slots, hot slots first with 8-bit displacements; a temporary read only by the next instruction is never stored; direct calls zero their argument area only when arguments are missing. The compiler's code shrank from 5.0 MB to 3.9 MB (tagged: 2.4 MB), which fits NodeOS's 4 MiB image copy |
| Fat performance | in progress. Int `/` and `%` run inline (`idiv`; divisors 0 and -1 take the runtime path); closure calls check the type word inline, reuse one scratch pair per function and zero only missing parameters; binary-operator and index slow paths are shared stubs; runtime trampolines return `RTAG` in RDX. Float `+ - * /` and comparisons run in one shared stub per operator (SSE; a zero divisor and other types continue to `rt_binary`), so a 20M-iteration Float loop takes 405 ms instead of 2.2 s (tagged: 8.0 s). The compiler's code is 3.65 MB before the LLVM backend's removal, 3.45 MB now. Micro-benchmarks against tagged: Int loop 416/365 ms, Float 652/3328, closures 128/281, lists 403/489, maps 384/375 |
| String library | `index_of`, `replace`, `to_lower` and `to_upper` in `native.may` scan bytes instead of re-indexing code points, for both representations; `stress.may` fell from 7.1 s to 0.7 s (tagged 5.3 s to 0.4 s) |
| Range loops | `for` over an Int-bounded range counts instead of building the list, which with 16-byte values exhausted the heap at 20M elements; a 20M-iteration loop takes 169 ms (tagged: 1397 ms before, 144 ms now) |
| Next | register-allocated temporaries for fat code |
