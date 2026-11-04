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

- Machine: Intel i5-13500H, Linux 6.12, 16 visible CPUs / 15 GiB, machine
  otherwise idle (every build and timed child ran with no other workload).
- Compiler: `mayc 0.15.0` from `f3c2dc1` — the perf round that added native
  Float loop bodies and a native Float main (#132), the collector pause work
  and frontier-bound default threshold (#135), the opt-in `--inline` inliner
  and the safepoint inventory (#131/#135) — default flags, full runtime
  (`compiler/mayc/mayc_new`).
- Others: GCC 14.2 `-O2`, rustc `-C opt-level=3`, OpenJDK 25, Node 24.22,
  CPython 3.13.5.
- Raw samples: [xlang-performance.json](xlang-performance.json).

## Wall time

Median whole-process wall time in ms.

| Benchmark | Maylang | C | Rust | Java | Node | CPython | May/C | May/CPython |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fib(35), recursive `Int` function | 57 | 16 | 19 | 57 | 81 | 657 | 3.7x | 0.09x |
| Collatz, seeds 1..300000, top level | 43 | 41 | 34 | 77 | 239 | 1827 | 1.1x | 0.02x |
| sieve, 10M `List<Bool>` | 194 | 24 | 30 | 65 | 245 | 415 | 7.9x | 0.47x |
| map, 200k `Str` inserts + 400k lookups | 88 | 59 | 54 | 108 | 132 | 142 | 1.5x | 0.62x |
| strings, 300k `"item-" + str(i) + ";"` + `join` | 51 | 20 | 23 | 61 | 64 | 45 | 2.5x | 1.12x |
| Mandelbrot 600×600, 100 iterations | 42 | 34 | 35 | 63 | 56 | 765 | 1.3x | 0.06x |
| n-body, 5 bodies × 200k steps (`struct`) | 76 | 11 | 8 | 38 | 45 | 474 | 7.1x | 0.16x |
| binary trees, depth 16 (`struct`) | 876 | 149 | 186 | 110 | 177 | 1949 | 5.9x | 0.45x |

## Peak RSS

MiB, as reported for the whole process.

| Benchmark | Maylang | C | Rust | Java | Node | CPython |
| --- | --- | --- | --- | --- | --- | --- |
| fib | 14 | 14 | 14 | 45 | 52 | 14 |
| collatz | 14 | 14 | 14 | 45 | 53 | 14 |
| sieve | 18 | 14 | 14 | 58 | 129 | 85 |
| map | 72 | 15 | 18 | 98 | 87 | 34 |
| strings | 66 | 17 | 23 | 81 | 94 | 33 |
| mandelbrot | 14 | 14 | 14 | 45 | 54 | 14 |
| n-body | 14 | 14 | 14 | 48 | 55 | 14 |
| binary trees | 146 | 14 | 14 | 168 | 91 | 21 |

## Against the roadmap baseline

The roadmap's baseline table was measured on `233909e`, before phases 1 to 3.
Rerunning today's suite on the same machine, after phases 0-5 of the roadmap
(runtime audit, specialized list storage, struct slots and enum payloads,
proven types and XMM Floats, native-word functions and main, the IR passes,
the live-set and frontier-bound collection threshold, and the Float codegen of
this round), gives:

| Benchmark | `233909e`, ms | now, ms |
| --- | --- | --- |
| fib | 123 | 57 |
| collatz | 619 | 43 |
| sieve | 1094 | 194 |
| map | 274 | 88 |
| strings | 283 | 51 |
| mandelbrot | 803 | 42 |
| n-body | 6226 | 76 |
| binary trees | 19965 | 876 |

The roadmap's phase goals now hold except the binary-trees one: Maylang beats
CPython on seven of the eight benchmarks (strings is 1.12x CPython, the one
remaining loss), Collatz is 1.1x C, Mandelbrot 1.3x C, map 1.5x C, and fib is
1.00x Java. Peak RSS on the sieve went from 420 MiB at `233909e` to 18 MiB,
and binary trees from 252 MiB after phases 1-3 to 146 MiB with the
frontier-bound collection threshold.

## What is left

- **binary trees, 5.9x C and 8.0x Java, 146 MiB against CPython's 21.** Every
  node is a map allocation with fat slots; C's node is two pointers. Struct
  slots and enum payloads by offset (#134) and the collector work (#135) took
  it from 19965 to 876 ms, and the phase-5 threshold plus the sealed-record
  mark path removed the frontier creep (252 to 146 MiB), but the remaining gap
  needs the allocation and collection architecture: precise stack maps plus a
  moving or generational collector for the RSS target
  ([STACK_MAPS.md](../../../../docs/design/STACK_MAPS.md)).
- **sieve, 7.9x C.** The storage is one byte per flag (18 MiB, better than
  CPython's 85), so what is left is the 10M `push` calls and the runtime store
  path: inline `push` landed, and a store path that keeps the index live
  across a widening call (#133) is the next step.
- **n-body, 7.1x C and 2.0x Java.** Each structure field read is an inline
  slot load and each `Float` operation in the general case still goes through
  the runtime: struct slots (#134) and native `Float` functions (#132) landed,
  but n-body's loops read struct fields from a list, so they stay tagged
  (native regions, [#137](https://github.com/mirged/maylang/issues/137)).
- **fib, 3.7x C, on a par with Java.** The function compiles to native words
  and direct calls with register arguments landed; what is left is the
  remaining call overhead and the opt-in inliner (#131).
- **strings, 1.12x CPython.** The only benchmark slower than CPython; the
  `str(i)` and `join` allocation paths (#99) are the remaining lever.

## Reproducing

```
make bench-xlang                       # prints both tables
python3 compiler/mayc/tests/backend/xlang.py --bench sieve trees --runs 10
python3 compiler/mayc/tests/backend/xlang.py --json /tmp/x.json --report /tmp/x.md
```

Binaries are built under `compiler/mayc/tests/backend/build/`, which git
ignores. The suite is not a CI gate; timings on a shared runner are not
comparable and correctness is covered by `make test-compiler`.
