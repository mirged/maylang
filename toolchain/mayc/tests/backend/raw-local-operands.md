# RAW local memory operands — issue #76, fifth pass

When a local-variable read has a single definition and its sole reader is the
immediately following binary operation's right operand, freestanding x86-64
code reads the local slot directly as that operand. The temporary register/stack
copy is omitted. For example, two local reads followed by addition can now emit
`mov rax, [left]; add rax, [right]`.

This is a local scheduling rule, not variable propagation. No instruction may
intervene between the borrowed read and the arithmetic operation. Assignments,
stores, calls, and control-flow boundaries therefore prevent it. Globals, boxed
locals, dynamic mode, multiple readers, multiple definitions, and non-binary
consumers retain normal snapshot temporaries. The frame slot remains the same
slot selected by the original local lookup. Allocation/liveness and loop-carried
private homes are unchanged.

The existing accumulator rule recognizes the omitted right-hand read, so the
left value may also stay in `rax`. Signed division loads the borrowed right
operand into `rcx`; add/subtract/multiply/compare use a memory operand directly.
There is no memory access reordering across effects or potential arithmetic
traps.

Execution tests cover the direct memory operand and a global snapshot that
must retain its value across a mutating call. IR tests accept only the adjacent
single-reader case and reject a control-flow boundary or dynamic mode. The
full signed arithmetic oracle, six workload checksums, LLVM, and bootstrap
convergence pass. Unicorn 2.1.4 was installed in a temporary test directory;
raw backends, core-runtime behavior/errors, ABI/register preservation, allocator
pressure, and arena checks now execute successfully on all emulated targets.
Native macOS/Windows OS-loader execution is still outside this Linux host.

The pinned 50-run comparison against the original compiler and `ec50f55` is
recorded in [raw-local-performance.json](raw-local-performance.json).

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW | 45.732 ms | 0.790 ms |
| Accumulator pass (`ec50f55`) | 28.743 ms | 0.771 ms |
| Local memory operand pass | 28.021 ms | 0.698 ms |
| GCC `-O3 -march=native` | 18.788 ms | 0.483 ms |
| GCC, also `-fno-tree-vectorize` | 18.486 ms | 0.713 ms |

The new pass reduces median time 2.5% relative to the accumulator pass.
Five-run median instructions fall from 287,735,575 to 255,339,563 and cycles
from 126,358,584 to 124,869,688. Static instructions fall from 1,543 to 1,476.
All six checksums match. These are whole-suite results on a pinned but
non-isolated host; per-workload samples, dispersion, and counter coverage are
retained in the report, without machine-specific timing gates.
