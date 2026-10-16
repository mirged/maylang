# RAW literal rematerialization — issue #76, third pass

RAW x86-64 compilation now rematerializes integer literals with a single
IR definition. These values need no physical register, spill home, or GC root,
even when used across a label. A literal with additional definitions, such as
a non-SSA loop index, retains the existing allocation and private-home rules.
Other architectures and dynamic arithmetic use the original allocator entry
point, which does not rematerialize literals.

The x86 emitter selects signed 8-/32-bit immediate add, subtract, compare,
and multiply instructions when their sign extension preserves the full raw
64-bit value. Larger constants are loaded into `r11`. This preserves `rcx`,
which holds the original dividend during reciprocal remainder reconstruction.
Raw literals are also loaded directly into the requested scratch register for
syscalls, stores, and hardware division fallbacks.

Unused IR nil values and result stores are omitted in raw code. Effectful
operations and potentially trapping loads/divisions still execute, including
when their results have no readers. No copy propagation across mutable locals,
calls, aliases, or control-flow joins is introduced by this pass.

`raw_codegen.py` checks immediate selection, full-width arithmetic, the large
literal scratch fallback, signed quotient/remainder boundaries, pointer stores,
branch behavior, side effects, and all six workload checksums. Allocator tests
verify that a literal crossing a label has neither a register nor a stack home,
while a loop-carried value with multiple definitions remains pinned. Existing
backend, allocator/forced-GC, core, LLVM, and bootstrap-convergence checks pass.
Unicorn is unavailable, so cross-architecture execution is skipped.

The pinned, interleaved 50-run comparison against the original compiler and
`f920ca2` is recorded in [raw-literal-performance.json](raw-literal-performance.json).
See [raw-constant-division.md](raw-constant-division.md) for runner commands;
substitute the saved `f920ca2` compiler as the second baseline.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW | 46.109 ms | 0.854 ms |
| Reciprocal pass (`f920ca2`) | 32.850 ms | 0.464 ms |
| Literal pass | 30.843 ms | 0.438 ms |
| GCC `-O3 -march=native` | 18.937 ms | 0.360 ms |
| GCC, also `-fno-tree-vectorize` | 18.511 ms | 0.315 ms |

Five-run median user counters fall from 532,792,167 to 423,309,618
instructions and from 145,712,958 to 137,551,217 cycles relative to the
reciprocal pass. Median runtime is 6.1% lower in this comparison. Static
instructions fall from 2,361 to 1,906. All six checksums match every time.
These are whole-suite measurements, with the same pinned/non-isolated host
and timing/counter limitations documented in the earlier reports.
