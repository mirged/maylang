# Core scratch arenas

Core runtime allocations normally live until process exit. Chunks are at least
1 MiB, with a 256 MiB total retained limit and exit status 70 on exhaustion.
Strings, lists and ordinary `alloc` still follow that lifetime. Applications
that construct unbounded numbers of those objects should use the full runtime.

For repeated raw-memory work, core provides an owned scratch arena on Linux
x86-64/ARM64/RISC-V64, macOS ARM64 and Windows x86-64:

| Function | Contract |
| --- | --- |
| `arena_new(bytes: Int) -> Ptr` | Allocate one process-lifetime arena. Capacity rounds up to eight bytes. Negative sizes or requests above 268,435,432 bytes exit 70. The normal retained-heap cap also applies. |
| `arena_alloc(arena: Ptr, bytes: Int) -> Ptr` | Reserve a span, rounding the consumed size up to eight bytes; return an eight-byte-aligned pointer. Negative sizes or capacity exhaustion print `arena capacity exceeded` and exit 70. Zero bytes consume no space. |
| `arena_reset(arena: Ptr) -> Nil` | Reset the cursor without mapping memory or clearing bytes. All previously returned spans become invalid. |
| `arena_used(arena: Ptr) -> Int` | Current consumed bytes, including alignment padding. |
| `arena_capacity(arena: Ptr) -> Int` | Rounded capacity in bytes. |
| `core_heap_retained() -> Int` | Total requested native chunk bytes, including arena storage and ordinary runtime allocations. |

An arena handle must come from `arena_new`; arbitrary, interior or stale handles
have undefined behavior, like other raw pointer operations. Keep the handle for
the arena's entire lifetime. An arena owns its spans; callers must stop using
all pointers into it before reset. This includes pointers copied into globals,
lists, other arenas or outside storage. A reset may make a future allocation
reuse the same address, so stale accesses can corrupt new data. The compiler
does not enforce these ownership rules. There is no individual free, implicit
reset, collection, nested checkpoint or cross-thread synchronization.

Arena memory contains raw bytes. It cannot supply backing storage for managed
`Str` or `List` values through this API. Resetting one arena does not invalidate
another arena or ordinary runtime allocations. Reset reclaims usable arena
capacity; it does not return pages to the OS or lower the retained-heap counter.
Repeatedly creating new arenas consumes the normal process-lifetime heap cap.

```may
let scratch: Ptr = arena_new(4096);
mut batch: Int = 0;
while batch < 10000 {
    let data: Ptr = arena_alloc(scratch, 256);
    store64(data, batch);
    // Consume data before resetting. Do not retain data outside this iteration.
    arena_reset(scratch);
    batch += 1;
}
```

Compile with `--runtime core`. These APIs are not provided by the full or raw
runtime. A zero-capacity arena is valid but admits only zero-byte allocations.
New spans are not initialized; never assume reset zeroes their previous bytes.

## Allocation growth measurement

[`tests/backend/arena.may`](../../compiler/mayc/tests/backend/arena.may) performs
1,024 rounds of 1 MiB scratch allocation, totaling 1 GiB of cumulative requests.
Each round validates bytes and the cursor, then resets the arena. The retained
counter stays exactly 1,052,672 bytes: the 1 MiB payload plus metadata rounded
to native allocation pages. A separate ordinary allocation remains intact.
The test uses a `while` loop so loop setup does not allocate a range list.

The [core suite](../../compiler/mayc/tests/core_runtime.py) executes the test
natively on Linux x86-64 and through Unicorn on all five targets, including
negative sizes, capacity exhaustion and the ordinary retained-heap limit.
The [native host suite](NATIVE_TARGETS.md) repeats the workload on Windows and
Apple Silicon. This is a measurement of requested chunk bytes, not RSS or exact OS mappings:
OS page/allocation-granularity rounding, resident-page accounting and other OS overhead are outside the counter. The 256 MiB cap applies to requested chunk bytes.
