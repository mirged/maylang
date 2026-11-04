# MOSAIC M1 — trace simulation and the research gate

Status: **gate failed.** Measured with the [trace simulator](../gc_sim/README.md)
on the [GC workloads](../gc_workloads/README.md). Per the
[roadmap](../../../../docs/design/MOSAIC_GC.md), the collector work (M3-M7)
is not started, and M2 takes the conventional path.

## Result

The table gives each policy's work relative to mark-sweep marking (higher is
better) and dead bytes retained over live bytes (the gate allows 0.10). The
oracle groups objects by their real death collection, so it is an upper bound
that no predictor can reach.

| Workload | collections | MS marked | window | site | learned | learned+fx | oracle |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| selfhost | 7 | 4,193,814 | 0.54x / 2.89 | 0.64x / 1.92 | 0.54x / 2.92 | 0.30x / 1.03 | 2.86x / 0.00 |
| maylsp | 12 | 2,570,837 | 0.12x / 33.96 | 0.21x / 18.49 | 0.14x / 26.35 | 0.07x / 5.94 | 2.75x / 0.00 |
| hashmap (small heap) | 7 | 769,298 | 1.91x / 0.29 | 3.66x / 0.00 | 3.20x / 0.09 | 3.15x / 0.09 | 3.82x / 0.00 |
| strings (small heap) | 7 | 1,066,100 | 1.18x / 1.00 | 2.93x / 0.17 | 2.41x / 0.44 | 1.56x / 0.14 | 3.53x / 0.00 |
| cross_mutation (adversarial) | 4 | 622,628 | 0.09x / 10.75 | 0.10x / 9.60 | 0.09x / 10.40 | 0.05x / 7.91 | 0.77x / 0.00 |

Earlier runs, whose sites were misattributed (the site and learned columns
are not valid; window, oracle and MS do not depend on sites), gave the
following window / oracle / MS figures:

| Workload | window | oracle |
| --- | --- | --- |
| trees | 0.30x / 6.03 | 3.80x / 0.00 |
| random_graph (adversarial) | 0.56x / 0.61 | 1.07x / 0.00 |
| cache_mix (adversarial) | 0.03x / 39.9 | 1.23x / 0.00 |

These three were not rerun with the corrected attribution.

## Gate

The roadmap requires learned cohorts to beat the best static policy by 2x in
work on at least four real workloads, with retained dead bytes at most 10% of
live bytes and segment edges below a tenth of object edges. No workload
passes: learned+fx is 0.3-0.9x of the best static policy, and its dead/live
ratio is 0.09-5.9. The segment-edge condition holds on the real workloads
(E_C/E 0.001-0.19), so the cohort graph is small. Retention is the problem.

## Why

- **Nepotism dominates.** A segment kept by one live object keeps its dead
  members, and their old pointers keep further segments. On the self-compile
  and maylsp, every implementable policy retains 1-34x the live bytes, and
  scans more objects than mark-sweep marks.
- **The idea itself is sound.** Grouping by real death time does 2.8-3.8x
  less work than marking on every real workload, with no dead retention. The
  gap is prediction: allocation site plus survival history does not predict
  death time well enough here. In trees, for example, the long-lived tree and
  the temporary trees come from the same constructor.
- **Fracturing helps retention but not work.** Fracturing cuts dead/live
  roughly 2-3x, but its local traces cost more than they save.

## Method and limits

- Traces from a hooked runtime copy (`gc_sim/trace.py`), one run per workload
  at the default policy (hashmap and strings under the small-heap policy so
  that they collect). Every policy's reclaims were checked against the real
  collector's live set, and none freed a live object. A `--segment 16`
  self-check reproduces mark-sweep exactly.
- Sites come from a rebuilt stack chain, not compiler site IDs. Unresolved
  signatures form one unknown site: about 1% of the self-compile's signatures
  (where the intern table also filled), 5% of maylsp's, and more in the small
  programs. Better site IDs (`--gc-sites`) would sharpen `site` and `learned`,
  but cannot beat the oracle, and the retention gap to it is large.
- The learned classes and the fracture decision use exact survival counts,
  which is optimistic. Cost units (objects scanned plus segment-graph steps
  against objects marked) ignore the sweep: mark-sweep also visits every heap
  block per collection, about 2.5x the marked objects on the self-compile.
- Raw summaries: [selfhost](mosaic-m1/selfhost.json), [maylsp](mosaic-m1/maylsp.json), [hashmap](mosaic-m1/hashmap.json), [strings](mosaic-m1/strings.json), [cross_mutation](mosaic-m1/cross_mutation.json).
