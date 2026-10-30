# Fat values

Status: fat values are the default with the full runtime on x86_64-linux
and x86_64-nodeos; the core runtime still uses the 3-bit tagged encoding
in
[`runtime.may`](../../compiler/mayc/runtime.may), which `--values tagged`
also selects ([#92](https://github.com/mirged/maylang/issues/92)). The
ledger at the end records what works.

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
never scanned), values (an array of 16-byte values; a payload is traced only
when its type word is a heap type) or words (runtime-internal pointer
tables; scanned conservatively). Stacks and registers are still scanned
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

## Ledger

| Step | State |
| --- | --- |
| Design and ABI | this document |
| `--values fat` flag, fat runtime and x86-64 backend | working (`runtime/fat.may`, `backend/x86_64_fat.may`); Int arithmetic, comparisons and list indexing inline, other operators call the runtime |
| Feature fixtures passing with `--values fat` | 45 of 45 (`compiler/mayc/tests/fat_values.py`); `bitwise.may` differs only where Int no longer overflows |
| Prelude, native library, math and stdlib | loaded; floats are unboxed, `math.may` bit helpers are intrinsics |
| Fibers, handlers, debug traces | working |
| Typed externs and native-word entries | working; native code calls externs through their fat entry |
| Self-hosting on fat values | the compiler built with `--values fat` emits byte-identical output and rebuilds itself identically (`fat_values.py`) |
| Default on x86_64-linux, bootstrap fixpoint | done; integer literals follow the target (±2^63 fat, ±2^60 tagged) |
| NodeOS | done: the full runtime is fat by default; `exec` and `system` fall back to the personality's spawn extension; the compiler runs and rebuilds itself on NodeOS |
| Core runtime, ARM64, RISC-V on fat values; tagged runtime removed | not started; the LLVM backend was removed instead of ported |
| Fat code size | temporaries defined once and read before the next boundary share reused frame slots, hot slots first with 8-bit displacements; a temporary read only by the next instruction is never stored; direct calls zero their argument area only when arguments are missing. The compiler's code shrank from 5.0 MB to 3.9 MB (tagged: 2.4 MB), which fits NodeOS's 4 MiB image copy |
| Fat performance | in progress. Int `/` and `%` run inline (`idiv`; divisors 0 and -1 take the runtime path); closure calls check the type word inline, reuse one scratch pair per function and zero only missing parameters; binary-operator and index slow paths are shared stubs; runtime trampolines return `RTAG` in RDX. The compiler's code is 3.65 MB. Micro-benchmarks against tagged: Int loop 416/365 ms, Float 652/3328, closures 128/281, lists 403/489, maps 384/375 |
| String library | `index_of`, `replace`, `to_lower` and `to_upper` in `native.may` scan bytes instead of re-indexing code points, for both representations; `stress.may` fell from 7.1 s to 0.7 s (tagged 5.3 s to 0.4 s) |
| Next | register-allocated temporaries for fat code, inline Float arithmetic |
