# RAW code alignment — issue #83

The RAW x86-64 backend aligned neither function bodies nor loop heads, so a
size change anywhere earlier in the image moved hot loops and changed their
speed. In #81 the byte-identical Collatz loop measured 3.985–4.466 ms (12%)
depending only on its address.

RAW x86-64 code now:

- starts every function body on a 16-byte boundary. The padding follows the
  entry trampoline's `ret` and is never executed;
- pads every loop head, meaning a label that a later branch in the same body
  targets, to 16 bytes with the recommended single-instruction NOPs of one to
  nine bytes. Padding of 10–15 bytes uses two NOPs. Fall-through entry
  executes the padding once per loop entry, not per iteration.

```asm
4019a3:  nop    WORD PTR [rax+rax*1+0x0]   ; 9 bytes
4019ac:  nop    DWORD PTR [rax+0x0]        ; 4 bytes
4019b0:  cmp    rbx,0x1                    ; Collatz inner loop head
4019b4:  jle    4019e7
...
4019e2:  jmp    4019b0
```

Every x86-64 branch is rel32 and fixups are recorded after the padding, so no
encoding, relocation or label changes size. The code section starts on a page
in ELF and PE (Mach-O is ARM64-only), so offset alignment is address
alignment. Tagged/full-runtime and core-runtime code and the ARM64/RISC-V
backends are unchanged. `--no-code-align` restores the previous layout; its
output is byte-identical to the `main` compiler's.

## Layout-control experiment

[`raw_layout.py`](../raw_layout.py) inserts a cold function of K four-byte
statements before the kernels of `raw_performance.may`. Functions were
already 8-byte aligned, so K = 0, 2, …, 30 places every kernel at 16
placements spanning 128 bytes. With `--cycles`, each kernel runs alone in its
own executable under `perf stat -e cpu_core/cycles/u`. That removes frequency
drift and the other kernels from the measurement. Every compiler compiles every
placement, and all 672 executables run interleaved. Each placement's value is
the median of 11 runs pinned to performance CPU 2.

The variants are the same source with different constants. The table shows
the spread of the 16 placement medians as (max − min) / min:

| Variant | PRNG | Collatz | Histogram | Automaton | Pointer chase | Random walk |
|---|---:|---:|---:|---:|---:|---:|
| `main` (no alignment) | 1.3% | **5.5%** | 8.2% | 2.8% | **3.4%** | 1.6% |
| Functions 16 | 1.1% | 5.0% | 11.0% | 2.6% | 0.9% | 0.9% |
| Functions 16, loops 16, skip ≤ 7 | 1.7% | 4.7% | 9.0% | 2.2% | 0.9% | 1.0% |
| **Functions 16, loops 16 (kept)** | 1.4% | **2.3%** | 8.1% | 3.9% | **1.1%** | 1.0% |
| Functions 16, loops 32, skip ≤ 15 | 1.7% | 1.4% | 7.1% | 3.8% | 0.9% | 1.9% |
| Functions 16, loops 32 | 1.1% | 1.6% | 6.7% | 3.0% | 1.0% | 0.8% |
| Functions 32, loops 32 | 1.1% | 1.1% | 7.6% | 2.8% | 0.8% | 1.0% |

PRNG and random walk barely depend on layout, and their 1–2% spread is the
noise floor. The histogram takes about 3 million cycles, so process startup
and noise dominate its spread under every variant. The automaton stays within
noise.

Collatz is the clear signal. Without alignment, one placement, with its inner
loop at offset `0x35` modulo 64, runs 3.5% faster than the other fifteen
(17.22 against 17.76–18.17 million cycles). Function alignment alone
does not help, because the loop's offset within its function is not a multiple
of 16. Aligned loop heads bring the spread to 2.3%. With 16-byte loops, the
remaining difference is between heads at offset 0 or 32 and heads at 16 or 48
modulo 64 (about 1%). The 32-byte variants remove that too. Alignment does
not recover the fast unaligned placement; all aligned placements sit near the
unaligned median.

A wall-clock version of the experiment with all six kernels in one executable
(31 runs, [JSON](raw-code-alignment-layout-time.json)) points the same way:
Collatz spreads 8.6% without alignment and 5.1% with it. Its noise floor is
3–5%, which is why the cycle-count mode exists.

## Interleaved suites against `main`

[Core](raw-code-alignment-core-performance.json),
[extended](raw-code-alignment-extended-performance.json) and
[predictability](raw-code-alignment-predictability-performance.json) reports:
2026-10-19 UTC, Intel Core i5-13500H, GCC 14.2.0, pinned performance CPU 2,
100 interleaved samples after 10 warmups, five counter samples. Every run
matches every checksum. The baseline is `main` at `beb593c`. Workload
medians are in ms, with standard deviations in parentheses:

| Kernel | `main` | Loops 16 (kept) | Loops 32 | Loops 32, skip ≤ 15 | Functions 32, loops 32 |
|---|---:|---:|---:|---:|---:|
| PRNG | 2.806 (0.069) | 2.809 (0.075) | 2.816 (0.083) | 2.812 (0.082) | 2.816 (0.082) |
| Collatz | 3.344 (0.182) | 3.364 (0.086) | 3.351 (0.101) | 3.361 (0.100) | 3.352 (0.099) |
| Byte histogram | 0.383 (0.061) | 0.387 (0.050) | 0.381 (0.047) | 0.382 (0.042) | 0.386 (0.050) |
| Cellular automaton | 1.095 (0.087) | 1.090 (0.078) | 1.084 (0.085) | 1.080 (0.057) | 1.084 (0.060) |
| Pointer chase | 3.922 (0.132) | 3.907 (0.107) | 3.908 (0.135) | 3.922 (0.127) | 3.930 (0.120) |
| Random walk | 2.808 (0.082) | 2.809 (0.084) | 2.805 (0.098) | 2.816 (0.094) | 2.806 (0.088) |
| Core sum | 14.543 (0.382) | 14.491 (0.299) | 14.509 (0.382) | 14.613 (0.307) | 14.555 (0.285) |
| Extended sum | 39.816 (0.993) | 39.780 (1.924) | 39.892 (1.548) | 39.797 (1.560) | 39.780 (2.021) |
| Predictability sum | 97.181 (2.124) | 97.125 (1.648) | 97.218 (1.889) | 97.118 (1.977) | 97.199 (1.341) |

No kernel or suite median moves beyond its run-to-run deviation in any
variant. Kernels within ±1% include Collatz (+0.6%), pointer chase (−0.4%)
and the automaton (−0.5%). The extended suite's largest shifts are knapsack
(+4.2%, deviation 0.188 ms), sieve (−2.0%) and matrix multiply (+1.9%), all
within one standard deviation. Counter medians agree: core instructions are
163.7 M against 163.8 M and branch misses 31.7 k against 31.9 k. Every
sample is in the JSON.

The [predictability suite](raw_predictability.may) rebuilds the five #78
if-conversion loops (periodic branch, PRNG parity with two arms and with one
arm, running maximum, rare guard) as `raw_performance.py --suite
predictability`. The #78 sources were not committed, so absolute times differ
from that report. Per-loop medians are unchanged within 1.3% (periodic branch
5.296 → 5.366 ms, deviation 0.77–0.92 ms).

## Code size

| Program | `main` | This change | Change |
|---|---:|---:|---:|
| Core suite code | 4,787 B | 5,037 B | +250 B (+5.2%) |
| Extended suite code | 9,231 B | 9,661 B | +430 B (+4.7%) |
| Predictability code | 3,174 B | 3,309 B | +135 B (+4.3%) |
| Core static instructions | 1,058 | 1,100 | +42 (37 NOPs) |

Code bytes span `_start` through the last instruction. Executables are
page-padded, so file sizes are unchanged. The remaining static
instructions come from the existing 8-byte zero filler before entry trampolines,
which objdump decodes as `add`. The other variants cost +1.9% for
functions alone, +3.3% for 16-byte loops with a skip limit of 7, +3.5% for
32-byte loops with a skip limit of 15, +8.2% for 32-byte loops and +10.9% for
32-byte functions and loops (core suite).

## Choice

The supported benefit is predictability, not speed. With function and loop
alignment, the size of unrelated code no longer moves a loop's 16-byte offset,
and the Collatz and pointer-chase placement spreads fall to near the noise
floor. The kept variant is the cheapest one that guarantees every loop head is
16-byte aligned:

- a skip limit of 7 left Collatz at 4.7%;
- 32-byte loops with a skip limit of 15 leave 7 of 17 core and 17 of 37
  extended loop heads unaligned, so code before such a loop in the same
  function still moves it;
- unlimited 32-byte loops reduce the Collatz spread from 2.3% to 1.6%, close to
  noise, for roughly 60% more padding.

The settings are `X86_FUNCTION_ALIGN`, `X86_LOOP_ALIGN` and `X86_LOOP_SKIP` in
`backend/x86_64.may`.

## Correctness coverage

`x86_codegen.may` checks the bytes of each NOP length. It checks padding from
72 starting offsets for alignments 16 and 32 with skip limits 0, 7, 15 and 31,
and that alignments 0 and 1 are disabled. It also checks loop-head detection
(backward `IR_JUMP` and `IR_TRUE` targets; forward targets are excluded) and
patched forward and backward rel32 branches across padding. `raw_codegen.py`
decodes every padding length from 1 to 40 with objdump as an independent
oracle: each sequence is NOPs only, nine bytes at most per instruction.

It then compiles 16 variants of a program with nested loops, `continue`,
`break`, `while true` and a loop in the top-level code. A mix of four- and
seven-byte statements moves the loops by every amount from 0 to 15 bytes, so
every padding length is executed. For each variant, the program's exit status
is checked against a Python oracle. Every backward-branch target and direct
call target must be 16-byte aligned, which also holds for a PE build. With
`--no-code-align`, the program must produce the same result with no NOP in the
image.

## Reproduce

```sh
python3 compiler/mayc/tests/raw_layout.py --cycles --cpu 2 --runs 11 \
    --compiler off=/path/to/main/mayc_new --compiler aligned=compiler/mayc/mayc_new
python3 compiler/mayc/tests/raw_performance.py --suite core --compiler compiler/mayc/mayc_new \
    --baseline-compiler /path/to/main/mayc_new --baseline-revision beb593c \
    --runs 100 --warmup 10 --cpu 2 --perf --output report.json
```

Use `--suite extended` and `--suite predictability` for the other suites.
`NAME=PATH=--no-code-align` measures the current compiler without alignment.
Copy each baseline compiler together with its runtime sidecars.
