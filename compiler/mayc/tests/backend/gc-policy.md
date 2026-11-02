# GC floor and margin overrides — issue #135

The collection threshold is derived from a nominal heap size
([GC.md](../../../../docs/internals/GC.md)): the first threshold floor is half of
it (`GCMIN`), and every sweep adds a margin of one sixteenth of it, capped at
8 MiB (`GCMARGIN`), above the live set and the allocation frontier. At the
default 256 MiB nominal heap that is a 128 MiB floor and an 8 MiB margin. The
[stack-maps design note](../../../../docs/design/STACK_MAPS.md) measured that on
binary trees these two numbers, not conservative retention, set the peak RSS:
the post-sweep frontier grew by exactly `GCMARGIN` every collection because
collections trigger mid-construction while the newest blocks are live, so a
workload with ~1 MiB of true live data still peaked at 226 MiB. This change
turns those two constants into `MAYC_GC_MIN` and `MAYC_GC_MARGIN` environment
overrides so the lever can be measured and used without generating a special
runtime, with the default behavior byte-for-byte unchanged.

## Mechanism

`runtime/fat_linux.may`, in `rt_init`, after the derived values are computed:

- `MAYC_GC_MIN` (bytes, decimal) replaces `GCMIN`, the floor of the next
  threshold and the first threshold.
- `MAYC_GC_MARGIN` (bytes, decimal) replaces `GCMARGIN`, the room kept above
  `2 * live` and above the allocation frontier.
- Values are read from `/proc/self/environ` by `rt_env_num` (the same probe the
  statistics flag uses; it maps its own page and never touches the heap). A
  value is accepted only in `[65536, reserve / 2]` and only when it is a plain
  decimal number of at most 15 digits; anything else leaves the derived value.
  The range rules out a zero margin, which would collect on every allocation.
- When either variable is unset the policy is exactly the previous policy: the
  same `sz / 2`/`sz / 16` derivation, the same floors and 8 MiB cap. The cost is
  two extra startup reads of `/proc/self/environ` (`MAYC_GC_STATS` does the
  same) and no runtime test on the allocation or collection path.

`MAYC_GC_STATS=1` continues to report `live`, `peak`, `threshold` and the
resident high-water mark, so a tuned run is still observable.

## Measurement

Method: `compiler/mayc/tests/stack_retention.py --xlang --compare --runs 10
--env MAYC_GC_MIN=8388608 --env MAYC_GC_MARGIN=524288`. The harness builds each
cross-language workload once against an instrumented copy of the runtime (the
nominal heap stays 256 MiB; a sweep meter records live bytes, post-sweep
frontier and threshold), then alternates base and tuned environments on the
same binary — so time and RSS are compared under the same machine load — and
requires identical program output for both. Times are total wall time from the
child's `wait4`, peak RSS is `ru_maxrss`, collections are counted from the
sweep meter. Default-behavior check: the compiler of the previous tip
`40ae868` and this change compiled the same trees and hashmap binaries; both
report identical `GC collections=11 allocated=1885689824 live=41945632
peak=218103712 threshold=226492320` for trees (and the same for hashmap), i.e.
the override machinery does not change the default policy.

### All eight workloads, default vs tuned (8 MiB floor / 512 KiB margin)

Ten interleaved runs each; time is the median, peak RSS the maximum.

| Workload | time base | time tuned | ratio | peak RSS base | peak RSS tuned | ratio | collections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| fib | 0.106 s | 0.106 s | 1.00x | 11.3 MiB | 11.3 MiB | 1.00x | 0 -> 0 |
| collatz | 0.097 s | 0.097 s | 1.00x | 11.3 MiB | 11.3 MiB | 1.00x | 0 -> 0 |
| sieve | 0.219 s | 0.227 s | 1.04x | 12.5 MiB | 11.3 MiB | 0.91x | 0 -> 0 |
| hashmap | 0.123 s | 0.168 s | 1.37x | 65.3 MiB | 46.0 MiB | 0.70x | 0 -> 7 |
| strings | 0.076 s | 0.196 s | 2.58x | 60.6 MiB | 38.4 MiB | 0.63x | 0 -> 7 |
| mandelbrot | 0.064 s | 0.068 s | 1.06x | 11.4 MiB | 11.4 MiB | 1.00x | 0 -> 0 |
| n-body | 0.096 s | 0.098 s | 1.02x | 11.4 MiB | 11.4 MiB | 1.00x | 0 -> 0 |
| binary trees | 1.185 s | 2.017 s | **1.70x** | 233.9 MiB | **95.0 MiB** | **0.41x** | 11 -> 60 |

Six of the eight workloads do not collect at the default heap and are
unaffected (their differences are inside the run-to-run spread; sieve's RSS
difference is one noisy sample). The three workloads that allocate more than
the tuned floor pay for it: binary trees loses 59% of its peak RSS for 70% more
time and 49 more collections; hashmap loses 30% for 37% more time; strings
loses 37% for 2.6x time (its 62 MB of short-lived strings now crosses seven
8 MiB floors, each collection scanning the roughly 60 MB the run has touched).

### Which knob does what

Five interleaved runs each; only the collecting workloads move.

| Workload | base RSS | margin only (512 KiB) | floor only (8 MiB) | both |
| --- | ---: | ---: | ---: | ---: |
| binary trees | 234.0 MiB | 152.1 MiB (0.65x), 11 -> 16 collections, 1.12x time | 200.3 MiB (0.86x), 11 -> 20, 1.13x time | 95.0 MiB (0.41x), 11 -> 60, 1.70x time |
| hashmap | 66.7 MiB | 65.1 MiB (unchanged, no collection) | 54.3 MiB (0.81x), 0 -> 3, 1.14x time | 46.0 MiB (0.70x), 0 -> 7, 1.37x time |
| strings | 61.4 MiB | 59.8 MiB (unchanged, no collection) | 42.9 MiB (0.70x), 0 -> 3, 1.90x time | 38.4 MiB (0.63x), 0 -> 7, 2.58x time |

The margin alone is the stronger single knob on trees (it sets the per-collection
frontier growth); the floor alone is what makes the smaller workloads collect at
all, which is where their peak RSS comes from.

### Frontier creep under both policies

`--workload trees trees_nolived --heaps 256` with the meter; the two runs
differ only in the environment.

| Run | collections | post-sweep frontier (MiB) | peak RSS |
| --- | ---: | --- | ---: |
| trees, default | 11 | 128, 136, 144, 152, 160, 168, 176, 184, 192, 200, 208 (+8 MiB per collection) | 233.9 MiB |
| trees, tuned | 60 | 8, 16.5, 33.5, then +0.5 per collection to 84.64 | 94.1 MiB |
| trees without the long-lived tree, default | 10 | 128, 136, ..., 200 (+8 MiB per collection) | 223.8 MiB |
| trees without the long-lived tree, tuned | 75 | 8, 8.5, ..., 54.5 (+0.5 per collection) | 60.1 MiB |

The default never rewinds below `128 MiB + N * 8 MiB` because each collection
triggers while the newest tree records are live; the tuned policy starts at
8 MiB and creeps by the 512 KiB margin instead, so peak RSS becomes
`floor + collections * margin + overhead` rather than
`floor + collections * 8 MiB + overhead`. That is the mechanism the stack-maps
note recorded, now reproducible with a flag.

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
  probe), `gc_stress.py` seeds 1/7/42 x 300 steps, `verify.py` (141 checks,
  including oracle and legacy output equality), `tests/compliance/run.py` and
  the bootstrap fixpoint (stage 2 = stage 3) pass with the runtime change.
- The previous tip and this change produce identical default GC statistics on
  trees and hashmap (see above), so defaults did not move.

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

# Runtime policy test.
python3 compiler/mayc/tests/limits.py --compiler compiler/mayc/mayc_new \
    --mode gc --gc-case gc_policy --heap-mib 4
```

Raw samples: [gc-policy-performance.json](gc-policy-performance.json),
[gc-policy-margin-only.json](gc-policy-margin-only.json),
[gc-policy-floor-only.json](gc-policy-floor-only.json),
[gc-policy-creep-default.json](gc-policy-creep-default.json),
[gc-policy-creep-tuned.json](gc-policy-creep-tuned.json).

Caveats: the timings use the instrumented runtime build the harness prepares
(the meter only runs at sweeps; the same binary is used for both arms) and the
peak RSS is `ru_maxrss` of the child, which includes the resident image; the
machine is shared, so the ratio between the two arms is the meaningful number,
not the absolute time. `reserve` is four times the nominal heap when the
reservation succeeds and the nominal heap otherwise, so the accepted override
range depends on that fallback.
