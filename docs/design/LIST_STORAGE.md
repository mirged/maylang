# List element storage

Status: implemented for the full fat runtime on Linux x86-64 (roadmap phase 2).

A list used to store one 16-byte fat value per element, whatever its type, so
a `List<Bool>` cost 16 bytes per flag and every store moved two words. The
sieve benchmark allocated 160 MiB for ten million flags and wrote 16 bytes per
assignment.

## Representation

A list is a 32-byte header:

| Offset | Field |
| --- | --- |
| 0 | length, in elements |
| 8 | capacity, in elements |
| 16 | buffer pointer |
| 24 | element kind |

The kind selects the buffer layout:

| Kind | Elements | Buffer | Collector kind |
| --- | --- | --- | --- |
| 0 | fat values | 16 bytes each | 3, precise values |
| 1 | `Int` (also `Ptr`) | 8-byte words | 1, scanned words |
| 2 | `Float` | 8-byte binary64 bits | 2, never scanned |
| 3 | `Bool` | single bytes | 2, never scanned |

`Int` words are scanned because an `Int` may hold a `Ptr` produced by `addr`
or `cstr`; the collector validates candidates anyway, so scanning costs time
and never changes reachability. `Float` bits and `Bool` bytes can never point
into the heap, so those buffers are never scanned.

## Where a kind comes from

The compiler picks a kind only where the element type is known and the value
is created:

- A list literal or comprehension whose static element type is `Int`,
  `Int8`…`UInt64`, `Float`/`Float32`/`Float64` or `Bool`
  (`ir.may ir_element_kind`).
- A list binding whose annotation names that element type
  (`strict.may st_list_element` records it on the literal; the annotation
  is *not* turned into a contract, because a `List` contract rewrites every
  element at each boundary).

Everything else — `List<Str>`, `List<Any>`, a list whose element type is
joined from mixed values, maps returned by `keys`/`values`, `range` — keeps
fat values, so the change is invisible where it does not apply.

## Widening

`Any` aliases can deliver a value of another type to a specialized list:
`push(anyRef, "text")` on a `List<Int>`. The runtime answers by widening the
list in place — `rt_list_widen` allocates a fat buffer, converts every
element with its tag, and sets kind 0 — and then stores the value. So the
observable result is exactly the fat list's: `[1, 2, 3, "text"]`.

`rt_list_put` is the single store primitive and reports whether the value
fits the kind; `rt_list_add`, `rt_index_set` and the widened path in the
generated store code all widen and retry once. Reads go through
`rt_element_tag`/`rt_element`, so display, `join`, `pop`, `to_map`, `map`,
`filter`, `reduce`, `any`, `all` and `in` read any kind.

Growth stays in 16-byte units: `rt_list_reserve` rounds the byte growth of
small elements up, because heap blocks are 16-aligned.

## Code generation

`fat_index` reads any kind inline: it checks the kind word and picks a
16-byte, 8-byte or 1-byte load, with the tag coming from the kind
(`2` Int, `3` Float, `1` Bool). `fat_index_set` stores inline when the value
type matches the kind and otherwise jumps to a widening path that calls
`rt_list_widen` and stores the already-evaluated value, so evaluation order
and effects are unchanged.

## Limits

- Nothing specializes `Map` storage, struct slots or closure environments;
  see the roadmap.
- A list created specialized and later widened keeps the fat layout for
  good, even if the offending value is popped.
- Only the full fat runtime has this layout. The core runtime and the other
  targets are frozen (`LINUX_X86_64_FOCUS.md`).
