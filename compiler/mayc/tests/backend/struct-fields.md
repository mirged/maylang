# Struct field access caches — issue #98

A struct is a map built by its constructor (`Point(3, 4)` is
`{"x": 3, "y": 4}`). Every field read or write called `rt_map_get` or
`rt_map_set`, which scanned the entries with `rt_str_eq` for maps under eight
entries and hashed the field name above that. A read cost about 50–65 ns, so
n-body and binary trees were 4× slower than CPython.

## Change

The representation is unchanged, so display, `keys()`, `has`, equality,
`remove`, JSON and `Any` access behave exactly as before. The change adds a
per-site inline cache:

- **Shared key objects.** The fat backend emits one read-only data object per
  distinct string literal text (`fat_key`). A struct constructor's keys, map
  literal keys and the field name of every `x.f` site therefore point to the
  same object.
- **A cache word per site.** IR lowering reserves a writable 8-byte word for
  each `E_GET` and `S_SETPROP` in dynamic code (`ir_field_cache`). Lowering
  runs before the size of writable data is fixed, and literals live in a
  read-only segment. The word holds the byte offset of the entry where the
  site last found its field. It starts at entry 0.
- **An inline check** (`fat_field_probe`). The cached entry is used only if
  all of these hold: the value is a map, the offset is below its entry count,
  and the entry's key is a `Str` whose payload is the site's key object. A
  read then loads the value's two words, and a write stores them. Because map
  keys are unique and the key object is that exact string, a match is
  correct for any map, whichever struct or literal built it.
- **A miss** calls `rt_field_get` or `rt_field_set`. These behave as
  `rt_map_get` and `rt_map_set` (`nil` for a missing field or a non-map, and
  a write appends a missing field) and refresh the cache word.

Maps whose keys were built at run time, such as JSON or `"na" + "me"`, never
match the pointer check and keep the old lookup cost plus a compare. A site
that alternates between layouts misses each time it changes layout. This
covers typed receivers, `Any` receivers and enum payload maps without help
from the type checker.

Two allocation changes go with it:

- Map literals and struct constructors with `n` keyed entries call
  `rt_map_new_sized`, which allocates the entry array at its final size.
  `rt_map_new` allocates a one-entry array but records capacity 0, so the
  first insert discarded it and allocated four entries. A two-field struct
  now takes two allocations instead of three, and 144 heap bytes instead of 256.
- `rt_str_eq` returns early when both strings are the same object, which
  constructors now hit for every key they compare.

## Measurements

[`struct-fields-performance.json`](struct-fields-performance.json) holds the
raw samples, taken with [`struct_fields/run.py`](struct_fields/run.py) on an
Intel i5-13500H under Linux 6.12. Runs used the full runtime and default
flags: five interleaved rounds after one warm-up and an output check. The
values are medians of user+system CPU time; wall time agrees within 1%.
"Before" is `main` at `63e5aad` with its own runtime. The machine was
running other work (load average 2.7–3.5).

| Workload | Before | After | Change |
| --- | ---: | ---: | --- |
| `read_local`: 5M `s += v` (loop floor) | 53.1 ms | 55.7 ms | noise |
| `read_list`: 5M `s += p[7]` | 72.0 ms | 71.7 ms | noise |
| `read_field2`: 5M reads of a 2-field struct | 378.1 ms | 66.0 ms | 5.7× faster |
| `read_field8`: 5M reads of the last of 8 fields | 314.8 ms | 63.6 ms | 4.9× faster |
| `construct`: 2M two-field struct constructions | 726.9 ms | 507.6 ms | 1.4× faster |
| `nbody`: 5 bodies × 200 000 steps | 6 442 ms | 582.6 ms | 11.1× faster |
| `trees`: binary trees, depth 16 | 29 446 ms | 5 878 ms | 5.0× faster |
| `self_compile`: mayc compiling `compiler/mayc/main.may` | 12 045 ms | 5 995 ms | 2.0× faster |

Without the loop floor, a field read costs about 2 ns (about 65 ns before),
and a list element read costs about 3.2 ns. That meets the issue's target of
"about as much as a list element read". Every workload printed the same
output on both sides. The compiler compiles itself in half the time because
its frontend works on maps and structs throughout.

n-body is now 2.6× faster than the CPython baseline of 1 510 ms in issue #98
(measured on a quiet machine, so that comparison is approximate). Binary
trees is still slower than CPython (4 429 ms). Field reads were not its main
cost. With a 131 071-node tree kept live, the same allocation loop takes
twice as long, so marking the live heap on every collection dominates. That
is the allocator and collector work in roadmap phase 5
([PERFORMANCE_ROADMAP.md](../../../../docs/design/PERFORMANCE_ROADMAP.md)).
A fixed-slot record layout, which would cut each record to one allocation,
is a separate step. It changes how records are observed.

Reproduce with:

```sh
# OLD_MAYC: a compiler built from 63e5aad, beside that revision's sidecars
python3 compiler/mayc/tests/backend/struct_fields/run.py \
    "$OLD_MAYC" compiler/mayc/mayc_new /tmp/struct-fields.json --rounds 5 --self-compile
```

## Validation

- `compiler/mayc/tests/field_cache.may` is a new feature fixture. It covers:
  - typed reads, writes and compound assignment;
  - a struct imported from `field_cache/geometry.may`;
  - one read site and one write site seeing the field at different
    entries, a map without it, a map with a run-time-built key, an `Int`
    and `nil`;
  - appending a missing field, `remove`, dynamic additions to a struct, and
    enum payloads through `match` and `Any`;
  - 1 000 structs read through one site.

  Its expected output came from the `63e5aad` compiler and matches byte for
  byte.
- With the rebuilt compiler, all of these pass: `make check`,
  `make test-compiler` (122 passed), `make test-compliance` (65 passed),
  `make test-tools`, `make test-docs` and `make test-bootstrap` (stage 2 =
  stage 3, so the compiler compiled by the cached field paths reproduces
  itself).

## Limits

- Records still take two allocations and 144 bytes for two fields, against
  48 for a fixed-slot layout. Peak RSS is unchanged (binary trees 290 MiB,
  n-body 11 MiB, before and after), because the heap's growth steps set it.
- A cache holds one layout per site. Sites that see many layouts, such as
  generic helpers over unrelated maps, pay a compare and a miss call on top
  of the old lookup.
- Each `x.f` site adds about 70 bytes of code (measured over 200 sites) and
  an 8-byte writable word.
