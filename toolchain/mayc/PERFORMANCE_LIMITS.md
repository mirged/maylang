# Measured GC and codegen limits — 2026-10-15

The [limits runner](tests/limits/README.md) exposed native signed constant
division/remainder as an optimization opportunity. The raw runtime already
used shifts, while full-runtime integer fast paths used `idiv` even for a
literal positive power of two. The native backend now shares the signed-bias
sequence across raw and tagged integers. Runtime fallbacks remain available
for floats, custom operators and invalid values.

## Measurement

Host: 13th Gen Intel(R) Core(TM) i5-13500H; Linux-6.12.111+deb13-amd64-x86_64-with-glibc2.41. Children pinned to CPU 0.
Baseline: source commit `189ff693d775d84eecfce2be4c7fc93ac638f311`.
Candidate: the working-tree x86 optimization in this change. Compiler
executables and matching sidecars were snapshotted before comparison.
No other agent test/stress jobs ran during this measurement; unrelated
host activity and frequency scaling were not controlled.

Each program ran 50,000,000 iterations with runtime seed 42, one warmup,
and 11 interleaved samples per compiler, reversing order each round.
Wall time covers process startup/execution; compilation is separate.
Every run matched the independent checksum.

| Kernel | Baseline median ms | Candidate median ms | Speedup | Direct `idiv` before → after |
| --- | ---: | ---: | ---: | ---: |
| arithmetic | 446.724 | 383.802 | 1.16× | 3 → 0 |
| branches | 837.278 | 746.267 | 1.12× | 6 → 1 |

Both images have 135,168-byte `.text` sections: alignment padding hides the
small instruction-count change. The arithmetic kernel grew from 311 to 313
instructions, while replacing three hardware divisions with shift/mask
sequences. Symbol-interval counts can include an adjacent call trampoline;
the complete binaries and disassembly remain the reference. This is a local
latency improvement for division-heavy kernels, not a general speed claim.

### Raw wall-time samples (ms)

- arithmetic, baseline-native: 446.102, 447.289, 447.178, 445.818, 446.927, 445.862, 454.164, 447.722, 446.714, 446.026, 446.724.
- arithmetic, current-native: 385.095, 383.802, 384.764, 383.856, 384.541, 383.431, 383.802, 382.984, 382.697, 383.177, 384.228.
- branches, baseline-native: 837.278, 831.998, 831.716, 832.318, 833.611, 831.105, 841.412, 840.401, 896.742, 955.053, 1083.526.
- branches, current-native: 746.267, 749.338, 739.291, 740.075, 741.111, 739.784, 742.655, 746.526, 750.984, 748.799, 777.422.

### Compiler and runtime identity

- baseline compiler SHA-256: `7d3cbc5b5fe2cf7c96f155a42bbfb0bfb88ff8b8e0f5a8af43b92f5ead3ba008`.
- Shared runtime.may SHA-256: `fdcefeea28becd0774646ac45fa3ae825bc3c891ac4a6b3cc8dc9257303ea452`.
- Shared native.may SHA-256: `2183522f220aa1b306c8fff017ddd153c8dc57a178b36ce119c8fbd94e3df35e`.
- Shared prelude.may SHA-256: `7b6ef9e2d60984601eef8c165441409abcc529fde7db32381ce23f611c90650e`.
- current compiler SHA-256: `902cf3545e0b99d595d687885f0535382eacb8612d6f0ad02cbd18d510a31d59`.

## Actual instruction selection

For signed integer division by eight, the fast path changes from `cqo` /
`idiv rcx` and quotient retagging to this sequence (operand/root setup omitted):

```asm
sar rax, 3      ; decode the tagged integer
mov rcx, rax
sar rcx, 63
and rcx, 7      ; bias negative dividends
add rax, rcx
sar rax, 3      ; truncate toward zero
shl rax, 3      ; restore the integer tag
```

Remainder masks the biased value and subtracts the bias, preserving the
dividend sign. Only positive literal powers up to 2^30 use this path;
negative, zero, non-power and larger divisors keep the general code.
Minimum/maximum tagged integers, negative nonmultiples, floats, custom `/`,
type errors, divide-by-zero and `MIN / -1` are covered by
[strength_reduction.py](tests/strength_reduction.py).

## Collector observations

The final native GC sweep passed 27 cases across 4, 16, 64 and 256 MiB
heaps with seeds 1, 42 and 2026, including injected payload corruption.
Separate calibration/production tests also filled the actual mark frontier.
Selected 256 MiB results (instrumented test runtime):

| Case | Allocation attempts | Requested MiB | Completed GCs | Peak RSS KiB | Observed outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| gc_churn | 131138 | 8223.69 | 37 | 296988 | passed |
| gc_fragmentation | 770 | 18.75 | 16 | 15848 | passed |
| gc_capacity | 4081 | 255.94 | 1 | 296984 | expected-capacity |
| gc_objects | 932873 | 1076.34 | 4 | 297116 | passed |

The real 1,048,576-slot mark frontier and 131,072-slot root registry both
terminated with their exact exhaustion diagnostic and exit 70. Heap
exhaustion likewise produced the expected diagnostic; it was not counted
as a corruption-free unlimited allocation run. GC time counters cover
completed collections. Conservative roots and fragmentation affect precise
allocation counts. These results do not resolve the older sustained-GC
report [#2](https://github.com/mirged/maylang/issues/2).

## Reproduce and continue

Use the [baseline snapshot and comparison instructions](tests/limits/README.md#compare-before-and-after-a-compiler-change),
with `--iterations 50000000 --samples 11 --cpu N`, choosing an allowed CPU.
Open `REPORT.md`, `report.json`, the retained `.may` source, and each
`hot-functions.asm` / `program.ll`. LLVM comments map numbered functions
back to source names. The `llvm-o3` variant also retains Clang's optimized IR
as `program.optimized.ll` and disassembles the actual linked binary.

The wider validation also ran seven codegen cases through native, LLVM -O1
and LLVM -O3, then increased call pressure to 64 arguments and call-graph
depth to 512. All checksums matched. Compiler verification passed 103
checks; LLVM/reachability and source bootstrap convergence passed.

An additional native sweep passed 256 live call arguments. Before the
[#59](https://github.com/mirged/maylang/issues/59) retention fix, 4,096 reachable
functions plus 4,096 dead functions, the 548,759-byte graph source exhausted
the compiler's heap: exit 70, `out of memory`, after the resolve timing and
before the IR timing. Peak RSS was 307,380 KiB. The unmodified baseline
also failed with the same diagnostic and stage boundary (300,640 KiB RSS).
This was an existing compiler capacity limit, separate from the expected
runtime capacity tests. The runner correctly retained these failures as
incomplete reports.

### Compiler heap retention fix (#59)

The parser retained all lexer tokens in `TOKS` after the AST had copied their
source spans. The type/name passes also retained completed lookup tables;
frontend roots kept unused bodies alive after the emission snapshot existed.
Releasing each at its ownership boundary allows the exact graph to compile
using the unchanged 256 MiB heap. Symbol strings remain rooted, as do AST
nodes referenced by IR payloads and the backend's own function snapshot.

Token release alone compiled the graph in 63,397.9 ms, with 58,586 ms in
packaging. Releasing the remaining phase roots reduced packaging to 18,985 ms.
ELF symbol-table construction still concatenated the entire accumulated string
table twice per symbol. A bounded byte sink removes that quadratic allocation
and copying. The final experiment compiled in 5,495.9 ms, including 93 ms in
packaging, with peak RSS 313,320 KiB. RSS includes source/output mappings and
GC metadata in addition to the 256 MiB heap. These are diagnostic runs, not a
controlled cross-machine performance comparison.

The final native image was byte-identical to the phase-release image; all
warmups/samples matched the independent graph checksum, and dead markers were
absent. The normal CI profile now includes this 548,759-byte graph and retains
its exact commands, stage timings and resource data.

Next useful inspection targets are register spills and repeated argument
reloads in wide calls, repeated collection contracts, and LLVM volatile
root stores. The LLVM runtime deliberately keeps stack roots alive for GC
and exception unwinding; any reduction needs the forced-GC and aliasing
regressions to stay valid.
