# Lists, strings and join — issue #99

Issue #99 found three workloads where the full runtime was slower than
CPython and used several times its memory: a 10M-element sieve, a string-key
map (fixed by #97), and building 300 000 strings and joining them. This
change addresses the remaining two and the causes behind them.

## Changes

- **`join` copies once.** `native.may` concatenated pairwise in log₂(n)
  rounds, copying O(n log n) bytes and allocating a list and intermediate
  strings per round. `join` on a List now calls `__join_list`, and the fat
  backend compiles that call as the runtime's `rt_join`:
  - it takes each element's display text (the same text as `str`) and keeps
    the texts in a scanned scratch block;
  - it allocates the total length once and copies each part and separator
    once.

  The `__join_list` body in `native.may` is portable Maylang (one allocation
  through `repeat`, then word-at-a-time `__native_copy_bytes`), because the
  source bootstrap compiles `native.may` with its own C runtime. A string
  receiver (`join("abc", "-")`) is copied into a List first, as before.
- **List growth in place.** When a list buffer is full and is the newest heap
  block, `rt_list_add` now extends it with `rt_grow_in_place`
  (`runtime/fat_linux.may`) instead of allocating twice the size, copying and
  abandoning the old buffer. That is the common case in a `push` loop. A
  buffer that is not the newest block still moves.

  Growing live data past the collection threshold raises the threshold, with
  headroom of the grown block's size or 64 MiB, whichever is larger. A
  collection right afterwards would find the block live. Without the
  headroom, the next small allocation (`print` at the end of the program)
  forced a full collection that marked all 10M elements.
- **Inline list stores.** `xs[i] = v` on a List with an in-range `Int` index
  is now stored inline (`fat_index_set`), matching the existing inline read.
  Everything else (maps, out-of-range or negative indices, non-Int indices)
  still calls `rt_index_set`, which reports the same errors.
- **Optimized leaf runtime functions.** In a dynamic program,
  `src/backend/x86_64.may` compiled every raw runtime function without local
  registers, address folding or the other RAW optimizations. The concern is
  real: a heap pointer held only in a register across a call that allocates
  would be invisible to the conservative collector. A function that makes no
  calls cannot trigger a collection while it runs, though. Leaf functions
  (`x86_leaf_block`) are now optimized as in RAW programs. A leaf contains
  only local computation, control flow, the memory intrinsics, `__fbits`,
  `__sp`, `ptr` and `syscall`. This covers `rt_copy`, `rt_zero`,
  `rt_str_eq`, `utf8_cplen`, the map hash functions and native-word helpers.
  In `rt_copy`, for example, the loop now keeps its pointers and index in
  registers with indexed addressing, instead of reloading every local from
  the frame.
- **Smaller fixes.**
  - `rt_int_text` counts digits and writes them backwards into the result,
    instead of formatting into a 32-byte heap scratch block first.
  - `utf8_cplen` (`len` of a string) counts eight ASCII bytes at a time.

## Measurements

[`lists-strings-performance.json`](lists-strings-performance.json) holds the
raw samples, taken with [`lists_strings/run.py`](lists_strings/run.py)
(`--rounds 7 --self-compile`) on an Intel i5-13500H under Linux 6.12. Runs
used the full runtime and default flags: seven interleaved rounds after a
warm-up and an output check, at load average 1.2–2.0. "Before" is `main` at
`76ed650`, which includes #97 and #98. The values are median CPU time and
the highest peak RSS over the samples. Every workload printed the same
output on both sides.

| Workload | Before | After | Peak RSS before → after |
| --- | ---: | ---: | --- |
| `sieve`: 10M `List<Bool>`, issue #99 | 1 085 ms | 613 ms | 420 → 160 MiB |
| `strings`: 300k `"item-" + str(i) + ";"`, then `join` | 277 ms | 90 ms | 262 → 66 MiB |
| `push_10m`: 10M `push(flags, true)` | 445 ms | 218 ms | 420 → 160 MiB |
| `join_300k`: `join` of 300k five-character strings | 150 ms | 17 ms | 144 → 18 MiB |
| `build_300k`: the string-building loop of `strings` | 123 ms | 84 ms | 76 → 60 MiB |
| `self_compile`: mayc compiling `compiler/mayc/main.may` | 4 054 ms | 3 510 ms | 384 → 386 MiB |

Against the issue's CPython figures, which were measured on a quiet machine,
so the comparison is approximate:
- The sieve now runs in 613 ms against CPython's 675 ms.
- The strings workload is close, at 90 ms against 82 ms.
- Peak memory is still higher (160 against 84 MiB, and 66 against 32 MiB).
  Every list element is a 16-byte fat value, and 10M of them are 160 MB live.
  Smaller elements need the specialized list storage in roadmap phase 2.

In the sieve, most of the remaining time is in the program's own loop code
(fat temporaries in memory, #96), not in the runtime. In `build_300k`,
about 85 ns per iteration remains: allocation, two concatenations and
`str(i)` through runtime calls.

## Validation

- `compiler/mayc/tests/lists_strings.may` is a new feature fixture. It covers:
  - `join` over strings, non-strings, Floats, nested values, empty lists and
    strings, a UTF-8 separator, a non-string separator and a string receiver;
  - a 20 000-part join;
  - in-place growth (100 000 pushes) and moving growth (pushes interleaved
    with allocations);
  - inline stores, and the runtime's errors for out-of-range, negative and
    non-Int indices;
  - `str` of 0, ±7, ±10⁶ and both Int extremes;
  - `len` across the 8-byte ASCII boundaries and of mixed UTF-8.

  Its expected output came from the `76ed650` compiler and matches byte for
  byte.
- The C bootstrap was checked separately: `join` and `substring` give the
  same text there (its `len` counts bytes, as it always has).
- With the rebuilt compiler, all of these pass: `make check`,
  `make test-compiler` (124 passed, including the raw code generation,
  backend and regalloc harnesses), `make test-compliance` (65 passed),
  `make test-tools`, `make test-docs`, `compiler/mayc/tests/gc.py`,
  `make test-limits` and `make test-bootstrap` (stage 2 = stage 3).

## Limits and follow-ups

- Non-leaf runtime functions (allocation, maps, concatenation, `rt_join`
  itself) are still compiled without local registers in dynamic programs.
  Optimizing them needs registers holding heap pointers to be spilled or
  scanned at calls, which is the precise-roots work in roadmap phase 5.
- During this work, a new host function first reused the name of an
  existing runtime function (`rt_extend`). mayc accepted the duplicate
  without an error and silently replaced the list-spread helper, so spreads
  crashed. The suite caught it, but duplicate runtime names should be
  rejected at compile time.
- List growth that is not at the top of the heap still leaves the old buffer
  to the collector.
