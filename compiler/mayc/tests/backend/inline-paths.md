# Inline push and string equality — issue #133

Two calls that dominated list-building and string-comparison loops are
answered inline: `push` when the list has spare capacity, and `==`/`!=` on two
strings whose byte lengths differ. `len` of a list or map was already inline
(`9ae3ec2`).

## Changes

**`push`** (`fat_push_fast`, `src/backend/x86_64_fat.may`). The fast path is
entered from both the `push` builtin and the `rt_push` runtime instruction that
`E_LIST` and comprehensions lower to. It loads both operands with `fat_get`
*before* emitting any check, in the same stack layout the runtime call uses:
list words deepest, value words on top. That is the whole point of the shape.
An earlier attempt failed because it emitted code between a value's definition
and the `fat_get` that read it, which the held-slot path rewinds over. Here no
operand is read after any check has been emitted.

The check reads the list header, compares the count against the capacity and
the element kind against the value's type word:

| kind | storage | accepted value type |
| --- | --- | --- |
| 0 | 16-byte fat values | any |
| 1 | 8-byte words | Int |
| 2 | 8-byte words | Float |
| 3 | one byte | Bool |

A mismatch, a full list, or a receiver that is not a List (type word 5) jumps
to the slow path, which is exactly `rt_push` called with the four words already
on the stack, so growth, widening and the type fault are the runtime's.

**String equality** (`fat_str_length_shortcut`). When both operands are Str
(type word 4) and their byte lengths differ, the answer is `false` for `==`
and `true` for `!=`, without entering `rt_eq`. Equal lengths and other types
take the existing path. The shortcut runs after `fat_operands`, which leaves
the operands in R9/R8 and RDX/RAX, so nothing is reloaded.

**Coalesce.** The third bullet of the issue, skipping the nil test for a
present map value, is not implemented: `fat_index` inlines list indexing only,
so a map probe is still `rt_index_get` and there is no probe state at the
branch to reuse. The branch is also cheap next to the probe. Doing this needs
map probing inlined first, which is a different change.

Both fast paths are skipped under `--no-opt`.

## Measurements

Intel i5-13500H, Linux 6.12, full runtime, whole-process wall time, hyperfine
after two warm-ups, identical output. "before" is a compiler built from
`aa3352d` in a separate worktree; "after" is this change. Both were built from
source, the runtime sidecars are unchanged and shared.

| Benchmark | before, ms | after, ms | change |
| --- | --- | --- | --- |
| sieve, 10M `List<Bool>` pushes | 250.1 (10 runs) | 186.8 | **-25.3%** |
| strings, 300k concatenations + join | 60.3 (10 runs) | 59.3 | -1.7% |
| hashmap, 200k inserts + 400k lookups | 110.2 (20 runs) | 110.2 | 0% |

The string workload does not compare strings, so the equality shortcut does not
show there; a separate 20-run sample put strings at 60.1 to 57.6 ms, inside the
run-to-run spread. Hashmap is the control and does not move.

Peak RSS is unchanged: the fast path pushes the same 32 bytes per call and has
no allocation of its own.

Whole-suite medians after the change (5 runs): sieve 193 ms (10.7x -> 7.6x C),
strings 56 ms, everything else within the spread of the recorded baseline in
[xlang-baseline.md](xlang-baseline.md).

Raw samples: [inline-paths-performance.json](inline-paths-performance.json).

## Tests

- `tests/inline_push.may` exercises a growing Int list, the push result, a
  call-computed value, Float and Bool kinds, widening through an `Any` alias, a
  fat list containing nil, and string equality on length mismatches, equal
  lengths, equal content and cross-type operands. Its output is pinned in
  `tests/legacy_behavior.json`.
- `tests/oracle.py` compiles it with and without `--no-opt` and requires the
  same output; the whole fixture suite passes under both.
- `make test-compiler` (131 checks) and `make test-bootstrap` (source-only
  stage 2 = stage 3) pass with the change.
