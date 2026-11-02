# GC floor and margin overrides — issue #135

Status: merged but default-off experiment. `MAYC_GC_MIN` and
`MAYC_GC_MARGIN` tune the collection floor and margin for one run; with both
unset the runtime is exactly the previous policy and the default code layout is
unchanged. The instruments are the two environment variables and the
[stack_retention.py](../stack_retention.py) tool (`--env`, `--xlang`,
`--compare`, `--pair`).

The collection threshold is derived from a nominal heap size
([GC.md](../../../../docs/internals/GC.md)): the first threshold floor is half
of it (`GCMIN`), and every sweep adds a margin of one sixteenth of it, capped at
8 MiB (`GCMARGIN`), above the live set and the allocation frontier. At the
default 256 MiB nominal heap that is a 128 MiB floor and an 8 MiB margin. The
[stack-maps design note](../../../../docs/design/STACK_MAPS.md) measured that
on binary trees these two numbers, not conservative retention, set the peak
RSS: the post-sweep frontier grew by exactly `GCMARGIN` every collection
because collections trigger mid-construction while the newest blocks are live,
so a workload with ~1 MiB of true live data still peaked at 226 MiB. The
overrides expose that lever without rebuilding the runtime.

## Mechanism

`runtime/fat_linux.may`: `rt_init` still derives `GCMIN` and `GCMARGIN` from the
nominal heap exactly as before. It already calls `rt_gc_stats_flag()` once near
its end (`MAYC_GC_STATS`); that same probe now also reads the environment and,
for each entry, calls `rt_gc_policy_entry`, which applies:

- `MAYC_GC_MIN` (decimal bytes): replaces `GCMIN` and moves the first
  `HEAPEND` to `HEAP + GCMIN`.
- `MAYC_GC_MARGIN` (decimal bytes): replaces `GCMARGIN`.

A value is accepted only in `[65536, reserve / 2]` and only when it is a plain
decimal number of at most 15 digits; anything else keeps the derived value, so
a typo cannot disable collection and a zero margin cannot livelock it. The
probe maps its own page and never touches the heap. When the variables are
unset the behavior is exactly the previous policy and the checks are two
syscall-free string comparisons per environment entry at start-up; there is no
test on the allocation or collection path.

`MAYC_GC_STATS=1` continues to report `live`, `peak`, `threshold` and the
resident high-water mark, so a tuned run is still observable, and the same
single read of `/proc/self/environ` drives both settings.

### Why the overrides live in the statistics probe

The first implementation put the environment reads inline in `rt_init`. That
changed the size and layout of the runtime code emitted before user functions
and cost fib 4-5% CPU in the integration audit: the function was correct but
the added bytes shifted the native fib function's alignment. The fix keeps
`rt_init`'s code shape and size unchanged and moves all new code into the
existing start-up probe and three helpers (`rt_gc_policy_entry`, `rt_env_name`,
`rt_env_digits`) that the runtime emits after the code every program depends
on; the only bytes that differ in user code are the call displacements inside
`rt_init` to functions that now live later in the image, so the native fib
function itself is byte-identical. A paired audit on a
pinned CPU (`--pair`, 120 samples per side, interleaved, CPU time from `wait4`):

| Executables (same compiler, only runtime sidecars differ) | fib CPU | wins A/B |
| --- | ---: | --- |
| pre-override runtime (40ae868) vs round-3 integration runtime | 0.0573 -> 0.0595 s (**+3.81%**) | 119/1 |
| pre-override runtime vs this change | 0.0566 -> 0.0566 s (**+0.17%**) | 58/62 |
| round-3 runtime vs this change | 0.0586 -> 0.0563 s (**-3.98%**) | 0/120 |

All eight roadmap workloads against the pre-override runtime (60 interleaved
samples per side on one pinned CPU; fib 120): collatz +0.05%, sieve +0.05%,
n-body -0.12%, trees +0.46%, strings -0.81%, mandelbrot -1.73%, hashmap -1.88%,
fib +0.17%. Nothing regresses and nothing improves by more than 2%; the small
deltas are binary-layout effects, not policy effects (the default policy is
identical, see below). Raw samples: [gc-policy-layout.json](gc-policy-layout.json).

Default-behavior check: a compiler from the previous tip and this change report
identical default GC statistics on trees and hashmap (trees: 11 collections,
1,885,689,824 allocated, 41,945,632 live, 218,103,712 peak, 226,492,320
threshold), and every `verify.py` fixture output matches.

## Measurement

Method: `compiler/mayc/tests/stack_retention.py --xlang --compare --runs 10
--env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288`. The harness builds each
cross-language workload once against an instrumented copy of the runtime (the
nominal heap stays 256 MiB; a sweep meter records live bytes, post-sweep
frontier and threshold), then alternates base and tuned environments on the
same binary — so time and RSS are compared under the same machine load — and
requires identical program output for both. Times are total wall time from the
child's `wait4`, peak RSS is `ru_maxrss`, collections are counted from the
sweep meter. All numbers below were re-generated with the final runtime.

### All eight workloads, default vs tuned (8 MiB floor / 512 KiB margin)

Ten interleaved runs each; time is the median, peak RSS the maximum.

| Workload | time base | time tuned | ratio | peak RSS base | peak RSS tuned | ratio | collections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fib | 0.056 s | 0.056 s | 1.00x | 11.8 MiB | 11.8 MiB | 1.00x | 0 -> 0 |
| collatz | 0.044 s | 0.046 s | 1.04x | 11.9 MiB | 11.8 MiB | 0.99x | 0 -> 0 |
| sieve | 0.194 s | 0.201 s | 1.04x | 11.9 MiB | 11.8 MiB | 0.99x | 0 -> 0 |
| hashmap | 0.096 s | 0.131 s | 1.36x | 64.4 MiB | 45.0 MiB | 0.70x | 0 -> 7 |
| strings | 0.055 s | 0.143 s | 2.60x | 59.8 MiB | 37.4 MiB | 0.63x | 0 -> 7 |
| mandelbrot | 0.046 s | 0.047 s | 1.02x | 11.9 MiB | 12.0 MiB | 1.01x | 0 -> 0 |
| n-body | 0.076 s | 0.076 s | 1.00x | 11.9 MiB | 11.9 MiB | 0.99x | 0 -> 0 |
| binary trees | 0.856 s | 1.498 s | **1.75x** | 233.9 MiB | **95.0 MiB** | **0.41x** | 11 -> 60 |

Six of the eight workloads do not collect at the default heap and are
unaffected (their differences are inside the run-to-run spread). The three
workloads that allocate more than the tuned floor pay for it: binary trees loses
59% of its peak RSS for 75% more time and 49 more collections; hashmap loses
30% for 36% more time; strings loses 37% for 2.6x time (its 62 MB of
short-lived strings now crosses seven 8 MiB floors, each collection scanning
the roughly 60 MB the run has touched).

### Which knob does what

Five interleaved runs each; only the collecting workloads move.

| Workload | base RSS | margin only (512 KiB) | floor only (8 MiB) | both |
| --- | ---: | ---: | ---: | ---: |
| binary trees | 233.8 MiB | 151.2 MiB (0.65x), 11 -> 16 collections, 1.09x time | 200.0 MiB (0.86x), 11 -> 20, 1.11x time | 95.0 MiB (0.41x), 11 -> 60, 1.75x time |
| hashmap | 64.3 MiB | 65.1 MiB (unchanged, no collection) | 53.5 MiB (0.82x), 0 -> 3, 1.12x time | 45.0 MiB (0.70x), 0 -> 7, 1.36x time |
| strings | 60.6 MiB | 59.6 MiB (unchanged, no collection) | 42.3 MiB (0.70x), 0 -> 3, 1.98x time | 37.4 MiB (0.63x), 0 -> 7, 2.60x time |

The margin alone is the stronger single knob on trees (it sets the per-collection
frontier growth); the floor alone is what makes the smaller workloads collect at
all, which is where their peak RSS comes from.

### Frontier creep under both policies

`--workload trees trees_nolived --heaps 256` with the meter; the two runs
differ only in the environment.

| Run | collections | post-sweep frontier (MiB) | peak RSS |
| --- | ---: | --- | ---: |
| trees, default | 11 | 128, 136, 144, 152, 160, 168, 176, 184, 192, 200, 208 (+8 MiB per collection) | 232.9 MiB |
| trees, tuned | 60 | 8, 16.5, 33.5, then +0.5 per collection to 84.64 | 94.0 MiB |
| trees without the long-lived tree, default | 10 | 128, 136, ..., 200 (+8 MiB per collection) | 223.8 MiB |
| trees without the long-lived tree, tuned | 75 | 8, 8.5, ..., 54.5 (+0.5 per collection) | 60.1 MiB |

The default never rewinds below `128 MiB + N * 8 MiB` because each collection
triggers while the newest tree records are live; the tuned policy starts at
8 MiB and creeps by the 512 KiB margin instead, so peak RSS becomes
`floor + collections * margin + overhead` rather than
`floor + collections * 8 MiB + overhead`.

## Using it

The overrides are an experiment and diagnostic tool, not a new default. The
defaults are unchanged and should stay that way until the threshold policy is
revisited with all workloads measured (the time cost above is large for the
string-heavy and tree-heavy cases). Good uses:

- RSS-sensitive runs: `MAYC_GC_MIN=8388608 MAYC_GC_MARGIN=524288 ./program`
  cuts binary trees' peak RSS by 59% and a hashmap/strings run by 30-37%.
- Measuring what precise stack maps and a moving collector would buy: the
  tuned threshold follows `2 * live + margin`, which is the quantity precise
  roots make meaningful ([STACK_MAPS.md](../../../../docs/design/STACK_MAPS.md)).
- Testing collector changes under a small heap without rebuilding sidecars.

`compiler/mayc/tests/limits.py --mode gc --gc-case gc_policy` pins the behavior:
on a 4 MiB test heap the default policy collects 3 times with a 2,626,656-byte
threshold, the tuned policy collects 5 times with a 2,240,816-byte threshold,
and invalid values (`abc`, `0`, or numbers above `reserve / 2`) leave the
default counts and threshold exactly.

## Tests

- `tests/limits/gc_policy.may` and the `gc_policy` case in `limits.py`: default
  versus tuned versus invalid overrides on a 4 MiB heap, with the heap
  invariants checked after the churn.
- `limits.py --self-test --runtime-gc-stats`, `gc.py` (including the record
  probe), `gc_stress.py` seeds 1/7/42 x 300 steps, `verify.py` (143 checks,
  including oracle and legacy output equality), `tests/compliance/run.py` and
  the bootstrap fixpoint (stage 2 = stage 3) pass with the runtime change.
- The previous tip and this change produce identical default GC statistics on
  trees and hashmap, and the paired layout audit above shows no workload
  regression beyond the run-to-run spread.

## Reproduction

```sh
sh compiler/rust/build.sh

# Headline table: ten interleaved base/tuned runs per workload.
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --xlang --compare --runs 10 \
    --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288 \
    --json /tmp/gc-policy-performance.json

# Lever decomposition (margin only, floor only).
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --xlang --compare --runs 5 --env MAYC_GC_MARGIN=524288 --json /tmp/margin.json
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --xlang --compare --runs 5 --env MAYC_GC_MIN=8388608 --json /tmp/floor.json

# Frontier creep traces.
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --workload trees trees_nolived --heaps 256 --json /tmp/creep-default.json
python3 compiler/mayc/tests/stack_retention.py --compiler compiler/mayc/mayc_new \
    --workload trees trees_nolived --heaps 256 \
    --env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288 --json /tmp/creep-tuned.json

# Default-off layout audit: same compiler, pre-override vs current runtime.
# (Build the two binaries by swapping the runtime/ sidecars of a copied
# compiler, then compare them on a pinned CPU with 60-120 samples per side.)
python3 compiler/mayc/tests/stack_retention.py \
    --pair /tmp/fib-pre-override /tmp/fib-current --pair-runs 120 --cpu 3

# Runtime policy test.
python3 compiler/mayc/tests/limits.py --compiler compiler/mayc/mayc_new \
    --mode gc --gc-case gc_policy --heap-mib 4
```

Raw samples: [gc-policy-performance.json](gc-policy-performance.json),
[gc-policy-margin-only.json](gc-policy-margin-only.json),
[gc-policy-floor-only.json](gc-policy-floor-only.json),
[gc-policy-creep-default.json](gc-policy-creep-default.json),
[gc-policy-creep-tuned.json](gc-policy-creep-tuned.json),
[gc-policy-layout.json](gc-policy-layout.json).

Caveats: the timings use the instrumented runtime build the harness prepares
(the meter only runs at sweeps; the same binary is used for both arms) and the
peak RSS is `ru_maxrss` of the child, which includes the resident image; the
machine is shared, so the ratio between the two arms is the meaningful number,
not the absolute time. `reserve` is four times the nominal heap when the
reservation succeeds and the nominal heap otherwise, so the accepted override
range depends on that fallback. The layout deltas above are measured on one
host; they show the size of the effect, not a property of the code to preserve.
