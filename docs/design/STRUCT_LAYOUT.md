# Struct slots and enum payloads

Status: implemented (roadmap phase 2, #134). Steps 1-4 are merged on
`perf/inline-paths` and measured in
[struct-slots.md](../../compiler/mayc/tests/backend/struct-slots.md) and
[enum-payloads.md](../../compiler/mayc/tests/backend/enum-payloads.md).

Records are maps. A `struct` declaration generates a constructor function whose
body is an `E_MAP` literal, and `Point(3, 4)` therefore allocates a 40-byte map
header, an entry array, a hash table once the record is large enough, and
inserts each field through `rt_map_put`, which hashes the field name. A typed
read `p.x` is already one probe against the site's cached entry (#98,
[struct-fields.md](../../compiler/mayc/tests/backend/struct-fields.md)), but
construction still pays for hashing and the record still costs 32 bytes per
field plus the hash table.

The struct-bound workloads are the two slowest in the suite: n-body at 8.6x C
and binary trees at 12.3x C, with binary trees peaking at 252 MiB against
CPython's 21 (measured 2026-11-02, [xlang-baseline.md](../../compiler/mayc/tests/backend/xlang-baseline.md)).

Specialized list storage ([LIST_STORAGE.md](LIST_STORAGE.md)) is the model: a
kind word in the header, runtime accessors that read it, and a compiler that
specializes only where the static type is known.

## Current record

A map value (type word 6) points at a 40-byte header:

| Offset | Field |
| --- | --- |
| 0 | entry count |
| 8 | entry capacity, in 16-byte-value words (two per entry) |
| 16 | entries pointer |
| 24 | hash table pointer, or 0 |
| 32 | hash table capacity, or 0 |

An entry is 32 bytes: key type word, key payload, value type word, value
payload. Entries keep insertion order; the hash table maps a hash slot to
`entry index + 1`. `rt_map_find` uses the hash table when capacity is nonzero
and otherwise scans the entries linearly, and `rt_map_put` builds the hash
table once a map reaches eight entries, so a record with no hash table already
behaves like any other map.

Field reads are compiled to a probe against the site's cached entry: the site's
data word holds the address of the entry it last matched, and the fast path
checks the key object and that the entry lies inside the count
(`fat_field_probe`).

## Proposal: a record with fixed slots

**One allocation, no hash table.** A record stays type word 6 and keeps the
map header shape, but its entries live in the same block:

```
48-byte header (count = fields, capacity = 2 * fields, entries = p + 48,
                hash table = 0, hash capacity = 0)
48 + 32 * i: entry i, in declaration order
```

The eight bytes after the 40-byte map header are padding: the collector scans a
values block on a 16-byte grid from its payload, so the entries must start on a
16-byte boundary or their type words fall between the scan pairs and nothing in
the record is traced. `rt_struct_new(n)` allocates `48 + 32 * n` bytes as one
precise-values block and stores the count and the entries pointer. The constructor then writes each
entry's key object, key type, value type and value, in declaration order, with
no hashing and no `rt_map_put`.

Because the header is a map header and the key objects are the same interned
strings the field sites use, everything that observes a record keeps working
unchanged:

- `p.x`, `keys(p)`, `p["x"]`, `len(p)`, `to_map(p)`, `==`, `str(p)` and
  `json_stringify(p)` read the entries in insertion order, which is declaration
  order today.
- `m["extra"] = v` through an `Any` alias appends an entry: `rt_map_put` sees
  no matching key, grows the entry array (the new block is no longer adjacent
  to the header, which is fine because `[16]` is a pointer), and builds a hash
  table once the record exceeds seven entries. A record that grows behaves
  exactly like today's map.
- The collector sees a record block (allocation kind 4): the first 48 bytes
  are scanned as words, so the entries pointer and the hash table pointer are
  traced, and the entries from `p + 48` are traced as values on the block's
  16-byte grid. A plain values block would trace the entries but not the
  header, and a record that moved its entries out on growth would then lose
  them (see [Prototype findings](#prototype-findings)).

**Offsets for typed reads.** Each field gets a slot from the strict checker
when the receiver's static type is the struct. The backend replaces the probe
with a guarded direct read or write of `[receiver + 48 + 32 * i + 24]` (value
type word at `+16`): the value must be a map, its entries pointer must equal
the block plus 48, and slot `i` must hold the site's key object. Anything else
-- an `Any` receiver, a record that grew its entries out, one compacted by
`remove`, or a foreign map -- keeps the existing field-cache probe, so
behaviour is unchanged either way. This mirrors specialized list storage: the
fast layout is chosen only where the compiler knows the type and the runtime
still proves the layout.

**Why not a bare header plus values?** Dropping the keys would halve a record's
size and make every read an offset load, but it changes the observable surface:
`keys`, `to_map`, display order, `p["x"]`, and equality between a record and a
map would all need a type descriptor and new runtime paths, and a record could
no longer be passed anywhere a map is expected without conversion. That is a
separate design with a larger blast radius; the fixed-slot map record gets the
allocation and hashing win without touching observation. Bare slots can be a
later step on top of this one, with the descriptor work done then.

## Enum variants

An enum value is also a map: the variant tag is an entry with the key `tag`
(`ok` for `Result`), and payload fields follow. The same fixed-slot record
covers enums: the constructor writes the tag entry first and payload entries in
declaration order, and `rt_struct_new` allocates them once. A variant pattern
proves the tag, so `match` reads the tag (slot 0) and the payload bindings
(slot `i + 1`) through the same guarded slot read as a struct field; the tag
comparison itself stays a value comparison through `rt_eq`. `Result` patterns
keep the runtime probe because `Ok`/`Err` are prelude maps, not records. The
guard compares the slot key against the site's key object, which is why
synthesized literals are interned by text: a match field name and the
constructor's entry key are then the same object.

## Code generation

Implemented as follows:

1. `parser.may` marks a struct or enum constructor's `E_MAP` as a record, and
   keeps the map path (no mark) for a declaration with repeated or keyless
   entries, because the map path updates a repeated key in place and keeps one
   entry.
2. `strict.may` stores the field's 0-based entry slot on the `E_GET` /
   `S_SETPROP` node as `fieldIndex` (1-based in the IR payload, 0 = unknown).
   The slot comes from the constructor's entry order, so a string-keyed entry
   before a field shifts that field's slot. It is not part of the type, so no
   contract is attached and no boundary rewrite happens.
3. `ir.may` carries the slot in the `E_GET`/`S_SETPROP` payload next to the
   existing `cache` word, and lowers a record constructor to `rt_struct_new` +
   one `rt_struct_set` per entry instead of `rt_map_new_sized` + `rt_map_set`.
4. `x86_64_fat.may` emits the guarded offset load/store; a failed guard falls
   back to `fat_field_get`/`fat_field_set`'s cache probe. The fallback still
   needs the cache word, so the typed path does not shrink the data section.
5. `ir.may` lowers a variant-pattern arm's tag and payload reads to the same
   guarded slot read (`ir_slot_read`), and `ir_opt.may` names those reads by
   their interned key text for CSE. Synthesized literals are interned by text
   so the guard's key object is the constructor's. `Result` patterns keep
   `rt_map_get`.
6. Done (#135): the constructor's `rt_struct_new` header writes and its
   `rt_struct_set` slot writes are emitted as one generated block when the size
   reaches the backend as a compile-time constant. The allocation itself stays
   a runtime call, so the block, the zeros the allocator leaves and the
   collector are unchanged; every unproven shape keeps the runtime calls
   ([report](../../compiler/mayc/tests/backend/construction-inline.md)).

Every step is skipped under `--no-opt`, and the oracle test compares both
builds of every fixture, as it does for the existing fat passes.

## Risks to check

- **Equality and ordering.** Records are compared as maps, entry by entry; the
  fixed-slot record must keep the same order and the same result for `==`
  between a record and a hand-written map with the same keys.
- **Growth.** A field added through an `Any` alias must append, not disturb
  declaration-order entries, and must trigger the hash table exactly as today.
- **The collector.** Entries are values in one block, on the block's 16-byte
  value grid; the key objects are
  interned strings, never moved, so the field cache's remembered entry address
  stays valid across collections.
- **Field cache invalidation.** A cached entry pointer is checked against the
  count, so an entry array that moves on growth simply misses and re-probes.
  The guarded slot read has the same fallback; the compaction half of that
  guard is defensive, because `remove` returns a copy and never compacts a
  record in place.
- **`to_map`, display and JSON** must not assume a hash table exists.

## Migration

1. Done: `rt_struct_new`/`rt_struct_set` and the record collector kind, with a
   raw record probe in `compiler/mayc/tests/gc.py` (`c7f46ae`).
2. Done: struct and enum constructors build the fixed-slot record
   (`715f115`), with duplicate-key declarations kept on the map path
   (`66f474c`).
3. Done: field slots on the IR and the guarded offset read/write
   (`e7c15f5`), measured below and in
   [struct-slots.md](../../compiler/mayc/tests/backend/struct-slots.md).
4. Done: enum payload reads by slot in `match` (`0e80998`), with the tag read
   included and `Result` patterns left on the runtime probe; measured in
   [enum-payloads.md](../../compiler/mayc/tests/backend/enum-payloads.md).

Expected win: one allocation and no hashing per record, so binary trees should
lose the entry-array and hash-table allocations entirely (the record becomes a
single 48 + 32n byte block) and n-body's per-step temporaries shrink. Peak RSS
should follow the record size, not the collector threshold.

## Measurements

Measured on `perf/struct-134` against a compiler built from the base commit
`e0f0932` with its own runtime sidecars. The workloads are the struct-field
ones plus a record-churn workload; seven interleaved rounds after a warm-up,
identical output on both sides. The table gives the least-contended (minimum)
user+system CPU sample because the machine was shared; medians, wall time,
peak RSS and the raw samples are in
[struct-slots.md](../../compiler/mayc/tests/backend/struct-slots.md).

| Workload | Before | After | Change |
| --- | ---: | ---: | ---: |
| `trees`: binary trees, depth 16 | 2233 ms | 1315 ms | 1.70x faster |
| `construct`: 2M two-field constructions | 231 ms | 125 ms | 1.85x faster |
| `record_gc`: grown records over a live tree | 680 ms | 398 ms | 1.71x faster |
| `read_field2`: 5M typed field reads | 13.3 ms | 11.7 ms | 1.14x faster |
| `nbody`: 5 bodies x 200 000 steps | 116.4 ms | 105.9 ms | 1.10x faster |
| `self_compile`: mayc compiling its own source | 3205 ms | 2660 ms | 1.20x faster |

The typed slot read is what `read_field2` and n-body gain; binary trees and the
construction/self-compile rows are dominated by the one-allocation constructor.

Step 4 was measured on top of the integrated base `62c3c45` (5 interleaved
rounds, medians of user+system CPU time, identical output, same runtime on both
sides):

| Workload | Before | After | Change |
| --- | ---: | ---: | ---: |
| `eval_tree`: recursive enum evaluator, 20 000 evaluations | 7007 ms | 1369 ms | 5.12x faster |
| `match_loop`: 3-arm matches over a 900-value typed list | 610 ms | 164 ms | 3.71x faster |
| `control`: Int arithmetic loop | 74.1 ms | 72.7 ms | noise |

Before, every arm test cost one `rt_map_get` call for the tag plus one per
payload binding; now the tag and payload words load behind the layout guard and
only the tag comparison still calls `rt_eq`.

## Limits

- Only the full fat runtime and Linux x86-64 are in scope
  ([LINUX_X86_64_FOCUS.md](LINUX_X86_64_FOCUS.md)).
- Records that grow past seven entries get a hash table like any map, and keep
  it; nothing shrinks it back.
- Bare slots without keys remain out of scope until the descriptor work above
  is designed.
- `match` still compares the tag by value (`rt_eq`) and keeps `Result` patterns
  on the map probe; comparing tags by pointer needs its own guard because a
  dynamically built tag string must keep matching by value.

## Prototype findings

A prototype of steps 1 and 2 (`rt_struct_new`/`rt_struct_put`, the struct
literal marked in the parser, and the `E_MAP` lowering using them) was built
and then reverted, not merged. Its behaviour checks passed — structs through
every map operation, a 300 000-record GC stress, a ten-field record grown past
the hash threshold, key order, `to_map`, display, equality and mutation through
an `Any` alias all matched the `--no-opt` map path — but the compiler built
with it crashed while compiling large inputs, in a size- and collection-timing
dependent way (the same input passed at 1 770 and 1 773 top-level statements and
segfaulted at 1 755, 1 765 and 1 775). Two findings should save the next
attempt the same time:

- **The entry grid must sit on the payload's 16-byte value grid.** The
  collector scans a values block in 16-byte pairs from its payload, so entries
  at `p + 40` leave every type word between the pairs and nothing in the record
  is traced; the first prototype segfaulted that way. Entries start at
  `p + 48`.
- **The slot count is the entry count, not the parameter count.** A struct
  declaration may add string-keyed entries (`struct Vec { x, y, "+": vadd }`),
  and sizing the record by `len(parr)` writes past its block.

### Diagnosis

The remaining crash was the record header never being traced. A values block
traces its 16-byte pairs and nothing else, so for a record whose entries are in
the block the header words were never marked. That was harmless until the
record grew: a dynamic field write moves the entries into a second, separate
values block and stores its pointer in the header, and nothing marked that
block. The next sweep freed it, and the record's next lookup or field write
read freed memory. The compiler regrows its own AST records constantly (the
parser adds `enumTag`, `enumFields`, `behaviorContract` and other fields to a
`FuncDecl` after construction), which is why the failure depended on input size
and collection timing: it needed a grown record whose moved entries block the
sweeper happened to reclaim.

The fix is the fourth allocation kind: a record block's first 48 bytes are
scanned as words (so the entries pointer and the hash table pointer are roots)
and the entries from `p + 48` as values. `compiler/mayc/tests/gc.py` builds a
record through the new runtime path, forces growth and a collection, and checks
with `rt_candidate` that the moved entries block and the hash table survived;
forced back to a plain values block, the probe fails on the swept hash table
(exit 88). `compiler/mayc/tests/runtime_maps.py` runs the same shape in source
form on a reduced heap so real collections happen, and the compiler's own
bootstrap fixpoint (stage 2 = stage 3) passed twice with the layout in place.

A second defect the prototype's behaviour checks did catch: the fixed layout
must fall back to the map path for duplicate entry keys. A variant with a
payload field named `tag` repeats the tag entry; the map path updates the first
entry in place and keeps one entry, while slot writes keep two. The parser now
detects repeated or keyless entries and keeps `rt_map_new_sized`;
`compiler/mayc/tests/record_dup_keys.may` pins both a duplicate variant and an
ordinary one, optimized and `--no-opt`.
