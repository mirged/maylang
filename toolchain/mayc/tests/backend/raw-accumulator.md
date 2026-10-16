# RAW accumulator forwarding — issue #76, fourth pass

The x86 emitter tracks the last IR result still in `rax` and can use it for
the next instruction's first operand. The fact is consumed once: later operand
loads in the same instruction cannot assume that arithmetic, calls, untagging,
or scratch-register work left `rax` intact. Omitted literal/nil/dead-copy
instructions do not invalidate the fact because they emit no machine code.

Only explicitly recognized lowerings may consume this fact. Labels, joins,
user calls, syscalls, and other lowerings invalidate it. Pointer load/store
intrinsics are recognized only when the name resolves to the intrinsic rather
than a local, global, or function binding. Platform host primitives are excluded;
Windows `__host_write`, for example, calls GetStdHandle before reading its first
IR operand.

In freestanding code, a temporary's store can also be omitted when it has one
definition and its only reader is the next emitted instruction's first operand.
The allocator's conservative operand-visit counts reject an instruction that
reads the same value again, even as its second operand. A label or other emitted
instruction blocks this optimization. This store omission is disabled in dynamic
mode, preserving all call-root synchronization and existing GC homes.

This does not relax register allocation or the private homes of multi-definition
values. Other readers, calls, control-flow edges, and multiple definitions retain
normal temporary stores and loads. The new fact only eliminates movement along
a proven straight-line producer/consumer edge.

`raw_codegen.py` checks that a small immediate arithmetic chain stays in `rax`
without temporary register stores or reloads. Existing execution checks cover
loops, reused values, spill pressure, nested calls, syscalls, pointer stores,
short-circuit control flow, and signed arithmetic. Encoder/IR tests reject a
second reader and a label between producer and consumer. Raw, core,
allocator/forced-GC, LLVM, and bootstrap-convergence checks pass. Cross-ISA
execution remains skipped because Unicorn is unavailable.

The pinned, interleaved 50-run report is
[raw-accumulator-performance.json](raw-accumulator-performance.json), comparing
the original compiler with `280d64a` and this pass. The runner command is the
same as in [the reciprocal report](raw-constant-division.md), with `280d64a`
as the second saved compiler.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW | 45.156 ms | 1.375 ms |
| Literal pass (`280d64a`) | 30.583 ms | 0.846 ms |
| Accumulator pass | 28.399 ms | 1.390 ms |
| GCC `-O3 -march=native` | 18.745 ms | 0.472 ms |
| GCC, also `-fno-tree-vectorize` | 18.500 ms | 0.669 ms |

Relative to the literal pass, median runtime falls 7.1%; five-run median
instructions fall from 425,501,620 to 288,508,696 and cycles from 134,568,402
to 128,248,166. Static instructions fall from 1,906 to 1,543. This run had
more timing dispersion than the preceding report; every sample and PMU
runtime/coverage is retained. The host was pinned, not isolated, and no
machine-specific timing threshold is used. All six workload checksums match.
