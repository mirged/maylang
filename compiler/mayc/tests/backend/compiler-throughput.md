# Compiler throughput — issue #101

Roadmap phase 7 ("Self-compile time and memory tracked per phase"). The
compiler is a Maylang program, so phases 1–5 speed it up too; this page
records a baseline and how to re-measure it, so a regression in compile
throughput is visible next to the runtime numbers.

## Method

`compiler/mayc/tests/build_benchmark.py` builds a program with the compiler
under test and times the whole `mayc` process — startup, frontend, IR,
emission and writing — with no artifact cache, one program at a time. It
records the median of N samples, the compiled image size, the compiler's
SHA-256 and the sidecar hashes, so two reports can only be compared when the
compiler and the `native.may`/`prelude.may` pair are identified.

```
python3 compiler/mayc/tests/build_benchmark.py \
    --compiler compiler/mayc/mayc_new --samples 3 --report /tmp/build.json
```

Machine: Intel i5-13500H, Linux 6.12, machine otherwise idle.

## Baseline (`perf/top-level-main`, after phases 0–3, the runtime audit,
specialized list storage and the live-set collection threshold)

| Workload | Median | Samples | Image |
| --- | --- | --- | --- |
| `hello.may` (one `print`) | 126 ms | 121, 131, 126 | 103 KiB |
| `features.may` (every frontend feature) | 158 ms | 158, 159, 155 | 212 KiB |
| the compiler itself (`main.may`, 8.5k lines plus sidecars) | 2434 ms | 2434 | 2.5 MiB |

The self-compile figure is one sample: a rebuild takes minutes and the harness
records `compiler_rebuild_samples`, so treat it as an order of magnitude, not
a median. The two small programs are medians of three.

The collection threshold moves these numbers more than any other recent
change, because a compiler's live set is large: with a first threshold of one
eighth of the nominal heap, `hello.may` took 206 ms and peak RSS fell to 56
MiB, while the fixed 256 MiB start of 0.15 was 134 ms and 89 MiB. The
committed policy (half the nominal heap, then `2 * live + margin` after every
sweep) lands within noise of the old time at 126 ms.

## What to watch

- A pass added to the frontend or IR shows up first in the `main.may`
  rebuild; keep it under a few percent per phase, and record the change in
  the same commit that adds the pass.
- `--time` prints the stage timings (`parse`, `types`, `resolve`, `ir`,
  `emit`, `package`) for a single compile and is the quick check while
  iterating.
- Static image size is recorded because inlining and specialization trade
  binary size for speed; the roadmap sets no size budget while only
  x86-64 Linux is in scope.

## Reproducing

```
make build                                    # or sh compiler/rust/build.sh
python3 compiler/mayc/tests/build_benchmark.py \
    --compiler compiler/mayc/mayc_new --samples 5 --report /tmp/throughput.json
```

`make check` does not run this; the CI performance job publishes the same
JSON beside the navigation, diagnostic, limits and cross-language reports.
