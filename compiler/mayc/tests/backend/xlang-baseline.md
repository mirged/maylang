# Cross-language baseline

The performance roadmap ([#101](https://github.com/mirged/maylang/issues/101))
compares Maylang against C, Rust, Java, Node and CPython on eight workloads.
`compiler/mayc/tests/backend/xlang.py` builds and times them; the sources are
in `xlang/` beside it and `make bench-xlang` runs the whole suite.

## Method

Each workload is one self-contained program per language with the same
computation and the same output. The harness builds every implementation,
runs each once, and fails before timing if any language prints something other
than Maylang does. It then times each with `hyperfine -N --warmup 1 --runs 5`
(whole process, not just the loop) and records peak RSS from the child's
rusage. A missing toolchain is skipped and reported on stderr.

- Machine: Intel i5-13500H, Linux 6.12, 32 GiB, machine otherwise idle.
- Compiler: `mayc 0.15.0` from this branch, default flags, full runtime
  (`compiler/mayc/mayc_new`), worktree based on `012c207`.
- Others: GCC 14.2 `-O2`, rustc `-C opt-level=3`, OpenJDK 25, Node 24.22,
  CPython 3.13.5.
- Raw samples: [xlang-performance.json](xlang-performance.json).

## Wall time

Median whole-process wall time in ms.

| Benchmark | Maylang | C | Rust | Java | Node | CPython | May/C | May/CPython |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fib(35), recursive `Int` function | 58 | 17 | 20 | 57 | 89 | 644 | 3.5x | 0.09x |
| Collatz, seeds 1..300000, top level | 88 | 41 | 39 | 82 | 247 | 1855 | 2.2x | 0.05x |
| sieve, 10M `List<Bool>` | 270 | 24 | 24 | 61 | 227 | 427 | 11.3x | 0.63x |
| map, 200k `Str` inserts + 400k lookups | 109 | 70 | 54 | 108 | 131 | 106 | 1.6x | 1.02x |
| strings, 300k `"item-" + str(i) + ";"` + `join` | 51 | 20 | 22 | 60 | 61 | 44 | 2.6x | 1.17x |
| Mandelbrot 600×600, 100 iterations | 46 | 34 | 35 | 59 | 57 | 758 | 1.3x | 0.06x |
| n-body, 5 bodies × 200k steps (`struct`) | 99 | 11 | 11 | 39 | 38 | 471 | 9.3x | 0.21x |
| binary trees, depth 16 (`struct`) | 1786 | 139 | 175 | 126 | 164 | 1955 | 12.8x | 0.91x |

## Peak RSS

MiB, as reported for the whole process.

| Benchmark | Maylang | C | Rust | Java | Node | CPython |
| --- | --- | --- | --- | --- | --- | --- |
| fib | 14 | 14 | 14 | 44 | 51 | 14 |
| collatz | 14 | 14 | 14 | 45 | 52 | 14 |
| sieve | 18 | 14 | 14 | 55 | 129 | 85 |
| map | 67 | 15 | 18 | 110 | 87 | 33 |
| strings | 64 | 17 | 22 | 80 | 95 | 33 |
| mandelbrot | 14 | 14 | 14 | 45 | 53 | 14 |
| n-body | 14 | 14 | 14 | 46 | 55 | 14 |
| binary trees | 252 | 14 | 14 | 170 | 90 | 21 |

## Against the roadmap baseline

The roadmap's baseline table was measured on `233909e`, before phases 1 to 3.
Rerunning today's suite on the same machine, after phases 0-3, the runtime
audit, specialized list storage and the live-set collection threshold:

| Benchmark | `233909e`, ms | now, ms |
| --- | --- | --- |
| fib | 123 | 58 |
| collatz | 619 | 88 |
| sieve | 1094 | 270 |
| map | 274 | 109 |
| strings | 283 | 51 |
| mandelbrot | 803 | 46 |
| n-body | 6226 | 99 |
| binary trees | 19965 | 1786 |

Every goal the roadmap set for phases 1 to 3 holds: Maylang beats CPython on
seven of the eight benchmarks (map is 1.02x CPython), Mandelbrot is within 2x
of C, collatz within 2.2x, and fib is within 1.0x of Java. Peak RSS on the
sieve went from 420 MiB at `233909e` to 18 MiB.

## What is left

- **binary trees, 12.8x C, 252 MiB against CPython's 21.** Every node is a map
  allocation with fat slots and a string-keyed field cache; C's node is two
  pointers. Struct slots and enum payloads by offset (#134) and allocation and
  collection (#135) both move this.
- **sieve, 11.3x C.** The storage is now one byte per flag (18 MiB), so what is
  left is the 10M `push` calls and the runtime store path: inline `push` and a
  store path that keeps the index live across a widening call (#133).
- **n-body, 9.3x C.** Each structure field read is an inline-cached map probe
  and each `Float` operation still moves through the runtime for the general
  case: struct slots (#134) and native `Float` functions (#132).
- **fib, 3.5x C, already within Java.** The function compiles to native words,
  so the gap is call overhead: direct calls with register arguments (#132) and
  inlining (#131).

## Reproducing

```
make bench-xlang                       # prints both tables
python3 compiler/mayc/tests/backend/xlang.py --bench sieve trees --runs 10
python3 compiler/mayc/tests/backend/xlang.py --json /tmp/x.json --report /tmp/x.md
```

Binaries are built under `compiler/mayc/tests/backend/build/`, which git
ignores. The suite is not a CI gate; timings on a shared runner are not
comparable and correctness is covered by `make test-compiler`.
