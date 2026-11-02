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
| fib(35), recursive `Int` function | 60 | 14 | 18 | 50 | 81 | 659 | 4.3x | 0.09x |
| Collatz, seeds 1..300000, top level | 84 | 41 | 35 | 81 | 242 | 1836 | 2.0x | 0.05x |
| sieve, 10M `List<Bool>` | 308 | 25 | 24 | 65 | 214 | 414 | 12.3x | 0.74x |
| map, 200k `Str` inserts + 400k lookups | 107 | 56 | 57 | 103 | 124 | 100 | 1.9x | 1.08x |
| strings, 300k `"item-" + str(i) + ";"` + `join` | 55 | 22 | 24 | 67 | 60 | 45 | 2.5x | 1.23x |
| Mandelbrot 600×600, 100 iterations | 44 | 35 | 35 | 56 | 57 | 771 | 1.3x | 0.06x |
| n-body, 5 bodies × 200k steps (`struct`) | 96 | 9 | 13 | 40 | 36 | 473 | 10.4x | 0.20x |
| binary trees, depth 16 (`struct`) | 1670 | 149 | 179 | 127 | 161 | 1967 | 11.2x | 0.85x |

## Peak RSS

MiB, as reported for the whole process.

| Benchmark | Maylang | C | Rust | Java | Node | CPython |
| --- | --- | --- | --- | --- | --- | --- |
| fib | 14 | 14 | 14 | 41 | 50 | 14 |
| collatz | 14 | 14 | 14 | 41 | 50 | 14 |
| sieve | 152 | 14 | 14 | 51 | 127 | 85 |
| map | 64 | 16 | 18 | 106 | 85 | 33 |
| strings | 61 | 16 | 21 | 73 | 93 | 33 |
| mandelbrot | 14 | 14 | 14 | 41 | 51 | 14 |
| n-body | 14 | 14 | 14 | 42 | 53 | 14 |
| binary trees | 287 | 14 | 14 | 150 | 89 | 21 |

## Against the roadmap baseline

The roadmap's baseline table was measured on `233909e`, before phases 1 to 3.
Rerunning today's suite on the same machine:

| Benchmark | `233909e`, ms | now, ms |
| --- | --- | --- |
| fib | 123 | 60 |
| collatz | 619 | 84 |
| sieve | 1094 | 308 |
| map | 274 | 107 |
| strings | 283 | 55 |
| mandelbrot | 803 | 44 |
| n-body | 6226 | 96 |
| binary trees | 19965 | 1670 |

Every goal the roadmap set for phases 1 to 3 holds: Maylang beats CPython on
seven of the eight benchmarks (map is 1.08× CPython), Mandelbrot is within 2×
of C, and fib is within 1.3× of Java. The suite median is 3.4× C; the two
outliers that set it are the collection-heavy ones (sieve, binary trees) and
n-body, all of which wait on Phase 2 and Phase 5 rather than on code
generation.

## What is left

- **sieve, 12.3× C.** `List<Bool>` stores a 16-byte fat value per element and
  the store is a runtime check plus a 16-byte write; sieve also touches 152 MiB
  of pages against C's 14. Specialized element storage (Phase 2) is the fix.
- **binary trees, 11.2× C.** Every node is a map allocation with fat slots and
  a string-keyed field cache; C's node is two pointers. Peak RSS is 287 MiB
  against CPython's 21, so allocation and collection (Phase 5) matter as much
  as field access.
- **n-body, 10.4× C.** Each structure field read is an inline-cached map probe
  (`struct-fields.md`), and each `Float` operation still moves through the
  runtime for the general case.
- **fib, 4.3× C.** The function compiles to native words, so the gap is call
  overhead: arguments travel in a vector on the stack and every call rechecks
  the count and the callee. Direct calls with register arguments (Phase 3) and
  inlining (Phase 4) address it.
- **map and strings** are close to the JITs already (1.9× and 2.5× C) and
  slower than CPython only where CPython's `str`-interning and dict shortcuts
  are hard to beat with a general hash table.

## Reproducing

```
make bench-xlang                       # prints both tables
python3 compiler/mayc/tests/backend/xlang.py --bench sieve trees --runs 10
python3 compiler/mayc/tests/backend/xlang.py --json /tmp/x.json --report /tmp/x.md
```

Binaries are built under `compiler/mayc/tests/backend/build/`, which git
ignores. The suite is not a CI gate; timings on a shared runner are not
comparable and correctness is covered by `make test-compiler`.
