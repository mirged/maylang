# Struct slots and enum payloads

Status: design note (roadmap phase 2, #134). No code yet.

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
- The collector sees a kind-3 block: every 16-byte value word is traced when
  its type word is a heap type, and an `Int` payload is still checked
  conservatively, as for any values block.

**Offsets for typed reads.** Each field gets an index at parse time. When the
receiver's static type is the struct, the compiler can replace the probe with
`mov rax, [receiver + 48 + 32 * i + 24]` (and the value type word at `+16`
when it is statically known), without any cache. The existing probe remains for
`Any` receivers and for records that may have grown, so behaviour is unchanged
either way. This mirrors specialized list storage: the fast layout is chosen
only where the compiler knows the type.

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
declaration order, `rt_struct_new` allocates them once, and `match` reads a
payload by the same offset rule once the arm's pattern proves the variant.
`match` currently probes `rt_map_get` per arm; that is the second half of this
change and lands after struct reads are measured.

## Code generation

1. `parser.may` records a field index per struct field and stores it on the
   `E_GET`/`S_SETPROP` node (not in the type, so no contract is attached and no
   boundary rewrite happens).
2. `ir.may` carries the index in the `E_GET`/`S_SETPROP` payload next to the
   existing `cache` word.
3. `x86_64_fat.may` emits the offset load/store when `fat_known_type` proves
   the receiver is the struct; otherwise it keeps `fat_field_get`/`fat_field_set`
   as they are. The typed path needs no cache word, so `ir_field_cache` is
   skipped for it and the data section does not grow.
4. `rt_struct_new` and a matching constructor lowering replace
   `rt_map_new_sized` + `rt_map_set` for struct and enum constructors only.

Every step is skipped under `--no-opt`, and the oracle test must compare both
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
- **`to_map`, display and JSON** must not assume a hash table exists.

## Migration

1. Add `rt_struct_new` and tests that build a record with it and observe it
   through every map operation (`keys`, `to_map`, indexing, `==`, display,
   JSON, a later `Any` insert).
2. Switch struct constructors to the new allocation; measure n-body and trees.
3. Add the field index and the typed offset read; measure again, and check the
   compiler's own image (`make test-bootstrap`, `build_benchmark.py`).
4. Extend the same path to enum variants and `match` payloads.

Expected win: one allocation and no hashing per record, so binary trees should
lose the entry-array and hash-table allocations entirely (the record becomes a
single 40 + 32n byte block) and n-body's per-step temporaries shrink. Peak RSS
should follow the record size, not the collector threshold.

## Limits

- Only the full fat runtime and Linux x86-64 are in scope
  ([LINUX_X86_64_FOCUS.md](LINUX_X86_64_FOCUS.md)).
- Records that grow past seven entries get a hash table like any map, and keep
  it; nothing shrinks it back.
- Bare slots without keys remain out of scope until the descriptor work above
  is designed.

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

The remaining crash was not diagnosed before the change was reverted: the
record's own reads, writes, growth and observation paths are all covered by the
checks above, so look next at `rt_remove` and `rt_merge_into` on a record, at
the sweep's treatment of a record whose entries moved out of the block on
growth, and at records that outlive construction with dynamically added fields.
A debugger build (or a `compiler/mayc/tests/gc_stress.py`-style reduction of the
compiler's own workload) is the way to pin it down.
