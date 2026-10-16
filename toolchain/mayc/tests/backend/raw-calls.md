# Direct x86-64 arguments — issue #76, seventh pass

Statically resolved source and IR runtime calls now load the first six integer
arguments directly into rdi/rsi/rdx/rcx/r8/r9 and call the existing register ABI
body. Only overflow arguments are pushed, in reverse order, with 16-byte call
alignment. Forward references and recursion share a lazily allocated body label;
explicit reachability retains its owning source function. Missing parameters
still receive raw zero or tagged nil, and extra argument expressions retain
their effects because IR lowering evaluates them before the call.

Linux syscalls load rax/rdi/rsi/rdx/r10/r8/r9 directly. Tagged runtime calls
untag each value in its destination register and tag the result as before.
The operand loader handles literals, register temporaries and frame spills for
both low and extended destinations. Temporary allocation continues to exclude
argument registers, so one destination load cannot overwrite another argument's
source. GC root synchronization still happens before ordinary calls.

Function entry stores incoming argument registers directly into parameter
slots. Dynamically sized closure calls retain the vector adapter, but no longer
copy every evaluated argument through a second set of local slots. The adapter
loads its final argument registers directly from the frame. Runtime helpers
emitted within operations keep this adapter because the scratch stack may have
an arbitrary alignment at those call sites.

Regressions execute raw and tagged calls with zero through ten arguments,
recursion, omitted parameters and extra-argument effects. Disassembly checks
require direct body entry and exactly the required overflow pushes. Existing
seven-register mmap calls, evaluation-order checks, forced-GC call pressure,
exception unwinding, cross-target ABI preservation and six workload checksums
also pass. LLVM behavior and bootstrap convergence were checked separately.

The [50-run pinned report](raw-call-performance.json) compares the original
compiler, `113ec54`, and this pass. The six kernels have few hot function calls;
this pass reduces static instructions from 1,470 to 1,291 without a demonstrated
runtime improvement in those kernels.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Original RAW | 43.414 ms | 0.465 ms |
| Range pass (`113ec54`) | 26.615 ms | 0.629 ms |
| Direct arguments | 26.937 ms | 0.663 ms |
| GCC `-O3 -march=native` | 17.684 ms | 0.304 ms |
| GCC, also `-fno-tree-vectorize` | 17.140 ms | 0.272 ms |

The difference between the two recent compiler medians is smaller than the
observed dispersion. Every workload checksum matched; samples, source hashes,
compiler hashes, PMU coverage and host details are retained in the report.
The complete compiler verification suite passed 115 checks with zero failures.
