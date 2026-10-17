# Cascading raw dead expressions — issue #76, ninth pass

Before allocating freestanding x86-64 raw temporaries, scan backward to remove
single-definition results that have no consumers and cannot trap. This includes
integer/string literals, copies, raw Boolean conversion, unary operations,
addition/subtraction/multiplication and comparisons. Removing an instruction
reduces its operand counts, allowing an entire unused expression tree to vanish.
The analysis uses the allocator's actual operand visits, including duplicated
payload references, and preserves instruction positions and CFG boundaries.

Calls, explicit memory loads/stores and division/remainder still execute. Their
arguments and effects remain ordered. Multiple-definition slots are left
conservative. Unread unboxed local/global variable loads are omitted during
emission; unknown names and boxed reads keep their existing handling. This pass
applies only to freestanding raw programs; tagged runtime functions are unchanged.

For this regression function:

```may
fun unused(a: Any) -> Any {
    (a + 3) * (a - 7);
    not a;
    a < 8;
    return 17;
}
```

The register ABI body shrinks from 32 instructions / 145 bytes at `89e4449` to
10 instructions / 35 bytes. Its frame falls from 64 to 16 bytes, and three
callee-save register saves/restores disappear. These are static code-size
measurements, not runtime latency claims.

Regressions execute nested effectful calls in discarded arithmetic and require
nested divide-by-zero and invalid-load expressions to retain their original
signals. They also check cascading operand counts, trapping division and the
multiple-definition guard. Focused raw codegen checks include all six original
workload checksums, full-width signed division oracles, call arities and compact
address relocations. Cross-target ABI, allocator/forced-GC checks and bootstrap
convergence pass. The separate IR-inspection memory investigation remains outside
this pass, as requested.
