# Fused RAW addresses and memory-loop registers — issue #79

Two separately measured steps target the memory-heavy kernels.

## Step 1: address fusion

Before allocation, each RAW load/store pointer built from single-use
additions, products by 1, 2, 4 or 8, imm32 literals and local snapshots is
planned as one `[base + index*scale + displacement]` operand. The access then
lists only the surviving temporaries as its operands, so linear scan extends
their intervals to it. Absorbed instructions lose their definitions and emit
nothing. A store value that only snapshots a local is read at the access too.
Bases and indexes come from registers in place; frame homes and literals
load into `rax`/`rcx` (`rdx` for store indexes, with the value in `rcx`).

Fusion requires:

- a single reader for every absorbed value and an imm32 displacement sum;
- no CFG boundary between the absorbed instructions and the access, within 16
  instructions;
- no write or redeclaration of a snapshotted local before the access, so the
  address uses the value the program read;
- an unshadowed intrinsic name (no local, global or function named `load8`).

Memory accesses keep their order, widths and faults; only pure arithmetic
moves. Subtraction, unsupported scales and other pointer shapes keep the
existing lowering.

## Step 2: registers in memory loops

Dedicated local registers previously excluded every function with a call,
including RAW loads and stores. They are now allowed when the only non-scalar
operations are unshadowed `load8`–`load64` and `store8`–`store64`:

- Maylang has no address-of operator for locals, so no defined pointer can
  name a local's frame slot. The only stack-address source, `__sp`, is a
  call and still excludes the function, as do `syscall` and all other calls.
- The intrinsics clobber `rax`, `rcx` and `rdx` only, never RBX or r12–r15.
- Promotion changes where locals live, not the order of memory accesses or
  their faults.

These call-free bodies also allocate temporaries in the volatile r8–r10, which
no scalar or memory lowering uses there; they are not saved or restored. The
planner ranks locals before fusion absorbs their reads, so fused uses still
count toward promotion.

The automaton's neighbour sum previously reloaded `front` and each index from
the frame:

```asm
mov    rax,QWORD PTR [rbp-0x98]
add    rax,QWORD PTR [rbp-0xb8]
movzx  eax,BYTE PTR [rax]
mov    r15,rax
mov    rax,QWORD PTR [rbp-0x98]
add    rax,QWORD PTR [rbp-0xa8]
movzx  eax,BYTE PTR [rax]
```

`front`, `back`, `i`, `width` and `round` now live in registers:

```asm
mov    rcx,QWORD PTR [rbp-0xb8]
movzx  eax,BYTE PTR [r12+rcx*1]
mov    r10,rax
movzx  eax,BYTE PTR [r12+rbx*1]
...
mov    BYTE PTR [r14+rbx*1],cl
```

## Measurements

[Complete report](raw-addressing-performance.json), 2026-10-17 UTC, Intel
Core i5-13500H, GCC 14.2.0, pinned performance CPU 2. Each executable has 100
interleaved samples, 10 warmups and five hardware-counter samples. Every run
matches all six checksums. The baseline is the merged #77 compiler at
`c3d3ea8`; fusion only is `9aed3bd`; both steps are `02f5b41`.

| Executable | Median end-to-end | Standard deviation |
|---|---:|---:|
| Baseline (`c3d3ea8`) | 21.649 ms | 0.285 ms |
| Fusion only (`9aed3bd`) | 21.713 ms | 0.320 ms |
| Fusion and memory-loop registers | 21.199 ms | 0.376 ms |
| GCC `-O3 -march=native` | 18.028 ms | 0.275 ms |
| GCC, also `-fno-tree-vectorize` | 17.521 ms | 0.310 ms |

Median per workload (standard deviation in parentheses):

| Workload | Baseline | Fusion only | Both steps | Change | GCC |
|---|---:|---:|---:|---:|---:|
| PRNG | 2.800 (0.060) | 2.805 (0.077) | 2.803 (0.082) | +0.1% | 2.800 |
| Collatz | 4.012 (0.101) | 4.466 (0.126) | 4.445 (0.251) | +10.8% | 3.510 |
| Byte histogram | 0.538 (0.037) | 0.504 (0.046) | 0.431 (0.042) | −19.9% | 0.212 |
| Cellular automaton | 1.760 (0.084) | 1.452 (0.067) | 1.080 (0.064) | −38.6% | 0.464 |
| Pointer chase | 3.924 (0.152) | 3.904 (0.132) | 3.900 (0.124) | −0.6% | 3.913 |
| Random walk | 6.981 (0.146) | 7.001 (0.142) | 6.924 (0.149) | −0.8% | 5.351 |

Fusion alone improves the automaton 17.5% and the histogram 6.3%; registers
roughly double those gains. Pointer chase, the regression control, stays at
parity with GCC.

### Collatz layout sensitivity

Collatz contains no memory operation, and its instructions are byte-for-byte
identical in all three compilers. Smaller memory functions earlier in the
image move its inner loop from `0x4019a5` to `0x40198d`. Padding a cold
function in the same benchmark source places the unchanged loop at six
addresses. Median of 20 interleaved runs:

| Inner-loop address | Collatz |
|---|---:|
| `…a5` (baseline image) | 4.005 ms |
| `…8d` (this branch) | 4.458 ms |
| `…c5` | 4.114 ms |
| `…fd` | 4.466 ms |
| `…35` | 4.369 ms |
| `…65` (same offset modulo 64 as the baseline) | 3.985 ms |

The 10.8% difference is therefore loop placement, not code quality. The RAW
backend aligns neither functions nor loop heads, so any size change upstream
can move a hot loop; that deserves a separate change measured across all
workloads.

### Counters

Five-run median performance-core user-mode counters:

| Counter | Baseline | Fusion only | Both steps | Change |
|---|---:|---:|---:|---:|
| Instructions | 181,575,219 | 168,507,940 | 151,143,063 | −16.8% |
| Cycles | 96,121,708 | 96,863,084 | 93,618,366 | −2.6% |
| Branches | 26,329,921 | 26,327,419 | 26,364,246 | +0.1% |
| Branch misses | 1,220,788 | 1,247,586 | 1,250,228 | +2.4% |

Static instructions fall from 1,164 to 1,124 with fusion and to 1,084 with
both steps. Every timing sample, counter coverage, compiler/executable/source
hash and host detail is retained in the JSON. Reproduce with
`raw_performance.py` as in the [divisibility report](raw-divisibility.md),
passing `--baseline-compiler` twice with saved `c3d3ea8` and `9aed3bd`
compilers.

### Considered and not kept

Weighting each local visit by 8× per loop-nesting level, so short-lived
in-loop locals such as the histogram's `byte` and `slot` qualify, changed the
histogram from 0.425 to 0.410 ms and left the other kernels flat in a 15-run
trial. That broader promotion rule is not included.

With the branch-free diamonds from #78 also applied, a separate 100-run
measurement records 15.991 ms versus 21.693 ms for the baseline (−26.3%;
0.89× GCC's 18.042 ms), with all checksums matching.

## Correctness coverage

`raw_codegen.py` decodes 4,698 `[base + index*scale + displacement]`
encodings with objdump as an independent oracle: nine bases, eight indexes
(including none), four scales, nine displacements at the imm8/imm32
boundaries, and 32- and 64-bit operands. That covers RBP/R13 bases without a
displacement and RSP/R12-style SIB forms.

It also generates 120 loops with two to four mixed-width loads and stores
through ten address shapes (scaled, swapped, nested, negative and ±4096
displacements, plus unfused subtraction) and checks 120 calls against a
byte-array model, together with fixed checks for:

- assignment inside an address's store value;
- partial-width store and load overlap;
- a near-imm32 fused displacement and a sum that must not fuse;
- a faulting load after an observable write, which still faults after it.

92 of the generated functions use scaled indexes. Generated call-free
functions must use RBX, and functions with calls must not use r8–r10.
Replacing the scale with 1 makes the oracle fail.

IR tests check the planned `[base + index*8 + 16]` operand, absorbed
definitions and operand lists. They also check rejection after a write to a
snapshotted local, a label, a window over 16 instructions, a non-imm32
displacement, a shadowing local and a second pointer reader. Removing the
snapshot write check makes them fail. Planner tests cover memory-intrinsic
promotion, shadowed intrinsics, syscalls, r8–r10 temporaries and parameter
names.

The broad verifier passes 115/115, including RAW workload checksums, ABI,
allocator/GC roots and cross-format backend checks. Compliance (69), LLVM
behavior (41), Rust tests and source-bootstrap convergence pass, as do all 34
native-target fixtures emitted locally and their x86-64 Linux execution.
Cross-architecture execution needs emulators that are not installed here and
runs in CI.
