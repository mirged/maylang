# The Native Garbage Collector

This document describes the archived Rust native runtime. For the self-hosted
mayc runtime, its size-bin allocator and the portable core's process-lifetime
heap, see [the mayc runtime documentation](../toolchain/mayc/README.md).

Maylang has no interpreter: every program is compiled to x86-64 machine code
and runs on a small hand-written runtime, including a garbage collector. This
document describes that collector.

## Object header

Every heap allocation is preceded by a 32-byte header:

```text
[0]  size      : total block size in bytes (8-aligned, >= 32)
[8]  meta      : (MAGIC << 16) | (free << 9) | (mark << 8) | kind
[16] next_all  : intrusive list of live (allocated) blocks
[24] next_free : free-list link (coalesced)
```

`MAGIC` is a 48-bit constant; validity checks reject words that merely *look*
like heap pointers. `kind` tells the tracer where an object's children are:

| kind      | payload                                  | traced children        |
|-----------|------------------------------------------|------------------------|
| `RAW`     | arbitrary bytes                          | none                   |
| `STR`     | `{ len, bytes }`                         | none                   |
| `FLOAT`   | `{ f64 }`                                | none                   |
| `ARRAY`   | tagged values                            | each element           |
| `LIST`    | `{ count, cap, data }` (also maps)       | the backing `ARRAY`    |
| `CELL`    | `{ value }` (captured variable)          | the value              |
| `CLOSURE` | `{ -1, code, nup, upvals... }`           | each upvalue cell      |

Allocations go through `rt_alloc` (raw) or a typed entry point
(`rt_alloc_str`, `rt_alloc_array`, `rt_alloc_list`, `rt_alloc_float`,
`rt_alloc_closure`, `rt_alloc_cell`), each of which tags the block with its
kind before returning.

## Allocator

The allocator is a first-fit free-list allocator over one contiguous heap:

* **Allocate:** scan the free list for a block at least as large as
  `payload + 32` (rounded up to 8 bytes). If it is much larger, split off the
  remainder and push it back. Otherwise hand the whole block out (its full size
  is kept so the physical heap walk stays consistent). If no free block fits,
  bump-allocate; if the bump pointer is exhausted, collect and retry.
* **Free (during sweep):** clear the block and set its `free` bit.
* **Coalesce:** after each collection the free list is rebuilt by walking the
  heap *physically* from `heap_start` to `heap_ptr`. Every maximal run of
  adjacent free blocks becomes a single free block, so fragmentation from
  differently-sized allocations is reclaimed.
* **Rewind:** the bump pointer is moved back to the end of the highest live
  block, reclaiming the tail in one step.

The heap is one **demand-zero** anonymous `mmap` region reserved by `_start`
(1 GiB by default; `compile_with_heap` overrides it). It is not stored in the
executable and only touched pages consume physical memory, so the reservation
is cheap while the usable heap is far larger than the old fixed 128 MiB.

## Collection

A collection is a stop-the-world mark-sweep:

1. **Roots.** Scan the machine registers (saved on entry), the native stack
   from the collector's frame to the initial stack pointer, and the whole data
   segment. A word is a candidate root when its low three tag bits are a heap
   tag (`1`, `5`, `6`, `7`); the candidate object pointer (`word & ~7`) is
   validated against the heap bounds and the header magic. The stack and data
   segment are scanned **conservatively**, so roots do not need to be described
   to the collector.
2. **Trace.** A worklist (an 8 MiB mark-stack region) drains the marked blocks;
   each block is visited according to its `kind` and its children are marked.
   Tracing is precise: `LIST` marks its backing `ARRAY`, `CELL` marks its
   value, `CLOSURE` marks its upvalue cells, and `ARRAY` marks its elements.
3. **Sweep.** Rebuild the live list from the marked blocks, mark the rest free,
   coalesce adjacent free runs into a fresh free list, and rewind the bump
   pointer past the last live block.

A collection runs when the bump pointer is exhausted and no free block
satisfies the request. If a full collection still leaves the program without
space, the runtime exits with status `70` rather than thrashing.

## Generations

The collector is generational without moving objects. Every allocation starts
**young**; when the heap is exhausted the allocator first runs a **minor**
collection (phase 1) and only if that fails to make room a **major** collection
(phase 2), then gives up with an out-of-memory exit. A minor collection sweeps
only young blocks: unmarked young blocks are freed, marked young blocks are
**promoted** (an `OLD` bit is set) and kept, and the whole old generation is
left in place. Because a live object is reachable from the roots through live
objects, tracing from the roots still finds every live young object; old
garbage is only reclaimed by a major collection. No moving means tagged
pointers stay valid and no write barriers are required.

## Why conservative?

The language's calling convention stores every live temporary on the machine
stack (or in a frame slot) across calls, so a conservative scan of the stack,
registers and data segment finds all live values without needing stack maps or
write barriers. The trade-off is that a stale word that happens to look like a
heap pointer can keep a dead object alive until the next collection; this only
delays reclamation, it never frees a live object.

## Limitations

* The collector is **non-moving** (tagged pointers are stable), so it cannot
  compact interior fragmentation — it coalesces it instead.
* A live set larger than the heap is an out-of-memory error (`70`).
* `next_all` links every live block, so marking and sweeping cost
  `O(live set)` once the free list has been rebuilt.
