# Struct fixed slots — issue #134

A record (a struct or an enum variant) used to be built from a 40-byte map
header and a separately allocated entry array, and every field went through
`rt_map_set`, which hashes or scans the field name. It is now one block:
a 48-byte map header (the 40-byte map header plus eight bytes of padding so
the entries start on the payload's 16-byte value grid) followed by the
entries in declaration order. A constructor fills the slots directly, and a
field read on a statically known struct loads its slot by offset behind a
layout guard.

## Changes

**One allocation, no hashing** (`runtime/fat.may`). `rt_struct_new(n)`
allocates `48 + 32n` bytes as one block, with count = n, capacity = 2n value
words, entries pointer = `p + 48`, and no hash table. `rt_struct_set` writes
one entry's four words at its slot. The parser marks a struct or enum
constructor's `E_MAP` as a record; IR lowering emits `rt_struct_new` plus one
`rt_struct_set` per entry instead of `rt_map_new_sized` plus `rt_map_set`.
The slot count is the entry count, not the parameter count: a declaration may
add string-keyed entries (`struct Vec { x, y, "+": vadd }`), and those take
slots in declaration order too. A declaration whose keys are not unique (for
example an enum payload field named `tag`) keeps the map path, because
repeated keys there update the first entry in place and stay one entry.

**Collector kind 4** (`runtime/fat_linux.may`). A values block traces its
16-byte pairs only, so a record's header words were never traced. That was
harmless while the entries stayed in the block, but a dynamic field write
moves them into a second block and stores its pointer in the header; nothing
marked that block, the sweep freed it and the record's next access read freed
memory. That is the undiagnosed defect behind the reverted prototype's
size- and collection-timing-dependent compiler crash: the compiler's own
parser regrows AST records after construction (`enumTag`, `enumFields`,
`behaviorContract`, ...), so it needed a grown record whose moved entries the
sweeper happened to reclaim. A record block's first 48 bytes are now scanned
as words (so the entries pointer and the hash table pointer are roots) and its
entries from `p + 48` as values.

**Guarded slot reads** (`src/strict.may`, `src/ir.may`,
`src/backend/x86_64_fat.may`). The strict checker records a struct field's
0-based entry slot on the `E_GET`/`S_SETPROP` node, IR carries it, and the fat
backend emits a direct load or store of the slot. The fast path runs only when
the value is a map, its entries pointer is the block plus 48, and the slot
holds the site's key object. A grown record, a record compacted by `remove`,
an `Any` receiver and any other map fail a check and take the old field-cache
probe, so the generated code never assumes a layout the runtime did not
build. Everything is skipped under `--no-opt`.

## Observation and stability

The record keeps the map header, the interned key objects and the entry order,
so `keys`, `len`, `has`, `to_map`, indexing, identity equality, display, JSON,
`remove`, `merge` and mutation through an `Any` alias behave as before.
`record_layout.may` pins that surface, including operator entries, enum
tag/payload order, growth past the hash threshold, `remove`, typed receivers
with compound assignment, and a struct-typed enum payload bound by `match`.
`record_dup_keys.may` pins the duplicate-key fallback; both fixtures are in the
oracle suite, so optimized and `--no-opt` output must stay identical.

`gc.py` builds a record through the new runtime path, forces growth and a
collection, and checks with `rt_candidate` that the moved entries block and
the hash table survived; forced back to a plain values block the probe fails
on the swept hash table (exit 88). `runtime_maps.py` runs the same shape in
source form on a reduced heap so real collections happen. The compiler built
with the record layout passes its own bootstrap fixpoint twice (stage 2 =
stage 3) and self-compiles; repeated runs are stable, with no size- or
timing-dependent failure.

## Measurements

Raw samples: [`struct-slots-performance.json`](struct-slots-performance.json)
(all workloads, 7 interleaved rounds) and
[`struct-slots-reads-performance.json`](struct-slots-reads-performance.json)
(the read-bound workloads, 31 rounds). Before is a compiler built from
`e0f0932` with its own runtime sidecars
(`artifacts/baseline/struct134`, compiler sha `b2a42ba3…`, runtime
`77200ff5…`); after is `e7c15f5` (compiler `3b274d50…`, runtime `1a4c10aa…`).
The workloads are the struct-field ones in `../struct_fields/` plus
`record_gc.may`, which builds batches of short-lived records over a live tree.
Every round runs every binary once, alternating the order; medians are of the
child's user+system CPU time and every workload's output is identical before
and after.

The machine was shared (16 cores, load average 7-8.5 while measuring), which
makes the short rows bimodal. Both the median and the fastest sample are given:
on a shared machine the minimum is the least-contended estimate of compute
cost.

| Workload | Median before | Median after | Min before | Min after | Δ min |
| --- | ---: | ---: | ---: | ---: | ---: |
| `trees`: binary trees, depth 16 | 2698.9 ms | 1483.5 ms | 2233.4 ms | 1314.6 ms | -41% |
| `construct`: 2M two-field constructions | 255.1 ms | 165.9 ms | 231.5 ms | 124.9 ms | -46% |
| `record_gc`: grown records over a live tree | 862.5 ms | 664.2 ms | 679.9 ms | 397.7 ms | -42% |
| `self_compile`: mayc compiling its own source | 3645.2 ms | 3044.7 ms | 3204.6 ms | 2659.6 ms | -17% |
| `nbody`: 5 bodies x 200 000 steps | 165.1 ms | 191.5 ms | 116.4 ms | 105.9 ms | -9% |
| `read_field2`: 5M typed field reads | 22.4 ms | 13.3 ms | 13.3 ms | 11.7 ms | -12% |
| `read_local`: 5M local adds (loop floor) | 6.5 ms | 6.5 ms | 4.8 ms | 4.5 ms | noise |

The focused 31-round run puts the read-bound rows closer: `read_field2`
21.9 → 19.9 ms median, 11.71 → 11.28 ms minimum, and `nbody` 139.4 → 116.2 ms
median, 110.7 → 101.5 ms minimum; the unchanged control `read_local` moves
6.53 → 6.02 ms median in the same run, which is the size of the drift on this
machine. The one-allocation constructor is the large, unambiguous win
(binary trees, construction and record churn are 1.7-1.9x faster); the guarded
slot read adds a few percent on read-bound code, because the existing
per-site cache probe was already cheap.

Peak resident set (median of the 7-round run, from `wait4` `ru_maxrss`; the
full runtime's heap reservation puts a ~18 MiB floor under the small
workloads): binary trees 258 → 240 MiB, construction 159 → 150 MiB,
self-compile 465 → 445 MiB, record churn unchanged at 184 MiB. The heap
threshold policy, not the record size, sets the peak; records now stop
allocating the separate entry arrays, which is where the smaller peaks come
from.

Reproduce with:

```sh
python3 compiler/mayc/tests/backend/struct_slots/run.py \
    /path/to/artifacts/baseline/struct134/mayc_new compiler/mayc/mayc_new \
    /tmp/struct-slots.json --rounds 7 --self-compile
python3 compiler/mayc/tests/backend/struct_slots/run.py \
    /path/to/artifacts/baseline/struct134/mayc_new compiler/mayc/mayc_new \
    /tmp/struct-slots-reads.json --rounds 31 \
    --workload read_field2 --workload read_local --workload nbody
```

## Limits

- Enum payload reads are not optimized yet: `match` probes the payload map per
  arm through `rt_map_get`. The record layout already covers enum values (the
  tag entry first, then the payload), so reading a payload by offset is the
  next step and is tracked in the design note.
- The slot read still pays the layout and key checks, which is what makes it
  safe for grown, compacted and foreign records. Removing them needs a record
  descriptor on the header, a larger design than this change.
- A record that grows keeps its moved entries block and any hash table; nothing
  shrinks it back.
- Timing on this machine is noisy; the raw samples and the control row are the
  guide. The constructor win is far outside the noise, the slot-read win is
  not.
