# Standard-library contracts

The active compiler is self-hosted `mayc`; its runtime is written in Maylang.
The archived Rust runtime is not the contract for current programs. The
[generated API inventory](../docs/reference/STDLIB.md) and [JSON inventory](../docs/reference/inventory.json) list source
signatures, public declarations and runtime/platform restrictions. Many APIs
retain `Any` annotations: callers must supply the documented value shapes.
An `Any` parameter is not a guarantee that arbitrary inputs are accepted.

## Runtime and platform

Ordinary modules target the full runtime on Linux x86-64. Pure functions have
no filesystem dependency, but may still use floats, maps or closures that core
rejects. The portable core's supported library is inventoried separately and
tested on all five direct targets. The full LLVM backend supports ordinary
modules and Linux I/O/networking, excluding fibers and typed extern calls.
Raw mode does not inject a standard library. See the
[target capability matrix](../compiler/mayc/README.md#cross-compilation).

`io`, `net`, environment/process primitives and raw syscall wrappers depend on
the full Linux runtime. `path` manipulates strings lexically and performs no
filesystem I/O, symlink resolution, permission checks or filesystem validation.
The active full-runtime sidecar is `compiler/mayc/native.may`. `stdlib/native.may`
is a byte-identical mirror for the language server and API docs; `make check`
fails if they differ.

## Values, numbers and text

- Integers have the tagged range -2^60 through 2^60-1. Overflow and integer
  division by zero raise catchable arithmetic errors in full mode and exit 70
  in core. Division truncates toward zero and remainder follows the dividend.
  Fixed-width annotations add checked boundaries, not full-width storage;
  Int64/UInt64 remain subject to the tagged range. Float32 rounds at annotated
  boundaries; other floating arithmetic uses binary64. See
  [numeric contracts](../docs/guide/STRICT.md).
- Text is UTF-8. Length, characters and ordinary substring indexing count
  Unicode code points, not grapheme clusters. Combining sequences can occupy
  several characters. Native case conversion is ASCII-only. String search and
  comparison use their existing runtime representations; no Unicode
  normalization or locale collation is performed. Raw pointers address bytes.
- Lists, maps and records are mutable references. Passing them does not copy
  storage; aliases see mutation. Full-runtime list/map equality uses identity;
  core list equality is structural. Strings compare by value. Use explicit
  element comparisons for portable collection equality.
- Error recovery uses `may { ... } otherwise { ... }`; `err.kind` and
  `err.message` describe failures. Typed Result helpers preserve their generic
  payloads; `unwrap` raises on Err and `unwrap_or` supplies a fallback. Failures
  inside callbacks propagate unless the helper explicitly catches them.
  I/O helpers return their documented Result/fallback or raise; low-level raw
  pointer misuse is not a recoverable shape-checking interface.

## Collections and algorithms

Stacks mutate on push/pop; empty pop/peek return nil. Queues mutate on
enqueue/dequeue, return nil when empty, release dequeued references and compact
their private backing storage. Do not depend on `items`/`head` layout or retain
aliases to that internal storage. Set add mutates; set remove, union,
intersection and difference return a new set. Removing an absent member keeps
the other members. Map key contracts depend on the native key representation;
string and integer keys have dedicated runtime coverage.

Sort/merge/iteration helpers return results as described by their source docs;
an already sorted singleton may share input storage. Callbacks may mutate
captured values. `take` clamps negative counts to zero; `drop` does likewise.
`chunk` and `windows` require positive sizes even for empty input, and raise
`chunk size must be positive` / `windows width must be positive` otherwise.
Oversized windows return an empty list; a final chunk may be smaller. Binary
search returns -1 on a miss. Empty `min_by`/`max_by` return nil. These operations
do not make a deep copy of nested values.

## String and path edges

`words` splits ASCII space, tab, carriage return and newline, dropping empty
pieces. Other Unicode whitespace is preserved. `count_occurrences` counts
non-overlapping matches and returns zero for an empty needle. `pad_left` and
`pad_right` append whole padding strings until the requested code-point width
is reached; multi-character padding can overshoot. Empty padding raises only
when more characters are needed. `truncate` appends the whole ellipsis, which
can itself be wider than the requested width.

Paths normalize slash/backslash separators, remove `.` and collapse lexical
`..` segments without walking above an absolute root. Empty paths normalize
to `.`. Joining an absolute right operand replaces the base. Drive-root paths
are recognized lexically; drive labels and other components are case-sensitive,
UNC/device paths have no special contract. Extensions omit the dot, ignore
leading-dot-only names and use the last suffix. Relative paths use `.` for the
same path and require matching roots; different drives or mixed relative/
absolute inputs raise `relative paths must have the same root`. Filesystem
existence and OS-specific reserved names are not checked.

## Experimental ML

All `ml/` APIs are experimental. Model and tensor shapes, parameter counts and
numeric assumptions are part of their inputs; this is not a BLAS/GPU runtime.
Training/inference mutate model caches where documented. Fixed inference
validates dimensions, scales, weights and row widths, uses integer softsign,
and returns a new output list; its parameters remain caller-owned mutable data.
See [ML module contracts](ml/README.md).

`examples/ml_xor.may`, `examples/stdlib_tour.may` and
`examples/stdlib_expanded.may` are compiled and run by compiler verification.
The focused [library suite](../compiler/mayc/tests/stdlib_contracts.py) runs
typed Result/I/O and [boundary cases](../compiler/mayc/tests/library/boundaries.may)
on native and LLVM, including successful fixed inference and invalid parameter
counts. Numeric, map, file and network suites cover the corresponding runtime
primitives. The [core suite](../compiler/mayc/tests/core_runtime.py) covers the
portable library and [arena lifetimes](../docs/internals/CORE_MEMORY.md). These tests are
contracts for exercised boundaries, not exhaustive validation of every `Any`
input or every experimental ML algorithm.
