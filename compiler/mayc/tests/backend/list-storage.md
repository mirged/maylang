# Specialized list element storage — issue #101

Roadmap phase 2 ("Specialized list storage for homogeneous element types").
The design is in [LIST_STORAGE.md](../../../../docs/design/LIST_STORAGE.md);
this page records what it changes and what it measures.

## What changed

- A list header grows to 32 bytes and gains an element kind: fat values
  (16 bytes), `Int` words (8), `Float` bits (8) or `Bool` bytes (1).
  Allocation kinds are `3` (precise values), `1` (scanned words) and `2`
  (never scanned) respectively.
- `runtime/fat.may` reads and writes every list through
  `rt_element_tag`, `rt_element` and `rt_list_put`, so display, `join`,
  `pop`, `to_map`, `map`, `filter`, `reduce`, `any`, `all` and `in` work on
  any kind. `rt_list_reserve` grows in whole 16-byte units, and
  `rt_list_widen` converts a specialized list back to fat values when a value
  of another type arrives through an `Any` alias.
- `src/ir.may` creates a specialized list for a literal or comprehension whose
  element type is `Int` (`Int8`…`UInt64`), `Float` (`Float32`, `Float64`) or
  `Bool`, and for a list binding annotated with one of those
  (`strict.may st_list_element`). Nothing else specializes.
- `src/backend/x86_64_fat.may` reads any kind inline: it checks the header's
  kind word and picks a 16-, 8- or 1-byte load with the matching tag.
  A store into a specialized list goes through the runtime, which converts or
  widens; a store into a fat list stays the old inline pair of writes.

## Measurements

Whole-process `fork`/`wait4` runs, peak RSS from `ru_maxrss`, Intel
i5-13500H, Linux 6.12, `mayc 0.15.0` from this branch at default flags.
Baseline is the same source tree before this change (`HEAD` = `a7af3c1`,
whose binaries are also what `xlang-baseline.md` measured).

| Workload | before | after |
| --- | --- | --- |
| sieve, 10M `List<Bool>` (whole process) | 308 ms, 152 MiB | 263–287 ms, 14–16 MiB |
| 4M `push(flags: List<Bool>, true)` | 52 ms, 61 MiB | 46 ms, 5 MiB |
| 4M `push(xs: List<Int>, i)` | 49 ms, 61 MiB | 40 ms, 31 MiB |
| 64k pushes of an interned `Str` (`List<Str>`, fat) | unchanged | 11 ms |

The sieve now allocates ten million flags in 10 MiB instead of 160 MiB, which
is below CPython's 85 MiB for the same workload, and its stores no longer
write 16 bytes per flag. Its time is dominated by the 10M `push` calls and
the runtime store path, not by memory traffic.

Reading an element of a specialized list is inline for every kind, so
`flags[i]` in a loop costs one kind check, one scaled load and one
immediate. `flags[j] = false` calls `rt_index_set`, which checks the kind and
stores one byte.

## Limits

- The store path for specialized lists is a runtime call: attempting an
  inline typed store with a widening fallback was measurably faster on the
  sieve (about 25 ms) but unstable in the compiler's own workload, so it is
  not merged. It needs a separate design for keeping the index live across
  the widening call.
- `List<Str>`, `List<Any>` and lists whose element type is joined from mixed
  values keep fat values; so do `keys`/`values`/`range` results.
- `Map` storage, struct slots and closure environments are untouched.

## Reproducing

```
MAYC=$PWD/compiler/mayc/mayc_new
$MAYC compiler/mayc/tests/backend/xlang/may/sieve.may -o /tmp/sieve
python3 - <<'PY'
import os, time
t = time.time(); pid = os.fork()
if pid == 0: os.execv('/tmp/sieve', ['/tmp/sieve'])
_, _, ru = os.wait4(pid, 0)
print(round((time.time() - t) * 1000), 'ms', ru.ru_maxrss // 1024, 'MiB')
PY
```
