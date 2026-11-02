# IR propagation and DCE — issue #131

Phase 4 of the [performance roadmap](../../../../docs/design/PERFORMANCE_ROADMAP.md#phase-4-ir-optimizer)
starts with the passes the issue asks for first: constant/copy propagation and
dead code/dead store elimination beyond `sem_fold`, plus common subexpression
elimination for repeat field reads. The passes run on the shared IR
(`compiler/mayc/src/ir.may`) but only for fat-value code; raw and native-word
functions keep the raw backend's own passes. `--no-opt` skips the module
entirely and `oracle.py` compiles every behaviour fixture both ways.

Done in this increment: propagation (copy, and value numbering for repeated
reads), dead code, dead stores and block-local CSE. Not attempted here, and
still open in [#131](https://github.com/mirged/maylang/issues/131): inlining
(tried and measured as not paying, see the roadmap), loop-invariant code
motion, check elimination, escape analysis, monomorphization and the
raw-backend ports. There is no cross-block value numbering or CSE yet.

## What changed

New module `compiler/mayc/src/ir_opt.may`, called from `main.may` after
`ir_program` and before `backend_emit`, so it sees the snapshot the backends
consume. It declines a function that contains an exception region
(`IR_TRY_BEGIN`) or an operation it does not model, so a later lowering change
falls back to the previous code instead of being mis-analysed.

The fat backend already forwards constants, stable variable reads and proven
types (`fat_forward`, `fat_plan_types`) and fuses compare-and-branch
(`fat_fusable`). The pass removes work those cannot see:

- **Straight-line regions.** Blocks start at the first instruction, after a
  control transfer, and at a label a branch or jump names. Labels are not
  boundaries by themselves: the lowering emits a join label after every
  `E_GET`/`E_SAFEGET`, and a plain `E_GET` never branches to its own join
  label, so consecutive field reads stay in one region. (This was the first
  surprise: the earlier block model saw one field read per block, which is why
  the first version found no CSE opportunities.)
- **CSE of repeat loads.** Field reads `x.f` are keyed on a value number for
  `x` and the field name; element reads `xs[i]` on value numbers for `xs` and
  `i`. Two `E_VAR` reads of the same binding share a value number until the
  binding is redefined or a call can rebind a global or boxed local. A load's
  duplicate is replaced only when every reader is later in the same region, so
  the earlier definition still dominates them. A store to the same field drops
  that field's entries and a list element store drops all element entries; a
  call, indirect call, runtime call or capture-cell store drops everything.
  The table is capped at 48 entries.
- **Copy propagation.** A single-definition `copy` whose readers are all later
  in the region, whose source is single-definition, is folded into its readers
  and dropped.
- **Dead stores.** A local declaration or assignment whose binding name is
  never read (no `E_VAR`, no call-through-variable, no closure capture) is
  removed. Initializer evaluation is not removed with it: calls, runtime calls
  and allocations stay, and arithmetic keeps its faults.
- **Overwritten dead definitions.** In a region, a discardable definition whose
  slot is written again before any reader is dead, because every path leaving
  the region passes through the later write. This is the snapshot copy the
  lowering emits before the conditional overwrite in `E_GET`/`E_SAFEGET` and in
  `if` results.
- **Dead code cascade.** Unused definitions of literals, `nil`, bool casts,
  copies and variable reads are dropped, cascading into their operands. The
  scan runs backwards because operands are defined earlier, so one pass is a
  fixpoint.
- **Dead labels.** Labels that no branch or jump names are dropped; they only
  put entries into the emitted label table and break the backends' held-slot
  and slot-sharing windows.
- **Smaller frames.** Surviving instruction positions are compacted and
  `block.temporaries` is trimmed to the highest surviving slot plus one.

All rewrites update both a quad's `arg1`/`arg2` fields and its payload
operands (the backend reads operations through the payload; `E_UN`/`E_POW`
keep operands only there). Nothing in the discardable set can fault or have an
effect: arithmetic (overflow and division faults), field/element reads
(nil/type faults), calls, runtime calls and stores all stay.

## Measurements

Intel i5-13500H, Linux 6.12, full runtime, identical `native.may`,
`prelude.may` and `runtime/` hashes on both sides. The host was shared with
parallel compiler work (load average 4.0–5.5), so the primary metric is child
CPU time (`user+sys`) of whole-process runs, sampled **interleaved**: every
round runs the baseline binary and the candidate binary in alternating order,
so load drift hits both sides. `fib` is a control: its own functions are
native-word code the pass does not touch, so any movement there is measurement
noise (0.8% here). 20 samples after 3 warm-ups per benchmark; the harness is
the xlang workload set. Every program printed identical output before timing.

| Benchmark | before min / median, ms | after min / median, ms | change (median) |
| --- | --- | --- | --- |
| fib (control) | 56.1 / 57.2 | 55.8 / 56.8 | -0.8% |
| collatz | 86.6 / 87.3 | 86.5 / 87.2 | -0.2% |
| sieve | 187.9 / 197.3 | 190.9 / 196.1 | -0.6% |
| hashmap | 100.0 / 104.4 | 100.9 / 106.4 | +1.9% |
| strings | 43.1 / 48.2 | 45.4 / 47.8 | -0.8% |
| mandelbrot | 45.4 / 46.7 | 45.1 / 46.7 | -0.1% |
| **n-body** | **107.8 / 113.6** | **90.0 / 94.8** | **-16.5%** |
| binary trees | 1795.5 / 1880.5 | 1790.0 / 1839.1 | -2.2% |

The win is n-body, the field-read-heavy benchmark: `advance` reads `b.mass`
and `c.mass` three times each per body pair and the dead snapshot copy is
removed from every field read. Its image is 2.9% smaller (142,904 → 138,808
bytes). Everything else is within the control's spread; hashmap's +1.9% median
(and +0.9% minimum) is not explained by the pass — the hashmap program's fat
functions have almost no repeated loads — and is treated as noise.

Compiler throughput (`features.may` over the same interleaved method, 20
samples; `main.may` self-compile 5 samples): features 152.1 → 150.7 ms CPU
(-0.9%), self-compile 2790.2 → 2740.4 ms CPU (-1.8%). The compiler's own image
drops 7.7% (3,236,592 → 2,986,736 bytes) because its own IR shrinks, which
covers the pass's cost. Measuring the first version of the pass with
per-block scratch arrays made self-compile 39% slower; reusing the arrays,
scanning backwards for the cascade and skipping passes with nothing to do
brought the cost down to this level. `--time` puts the pass inside the `ir`
stage.

Raw samples: [ir-passes-performance.json](ir-passes-performance.json)
(house format: per-command mean/stddev/median/min/max and every sample).

## Tests

- `compiler/mayc/tests/ir_opt.may` pins observable behaviour: repeated field
  reads, a same-field store between reads, a call that mutates the object, a
  store through a possibly aliasing parameter, a list element store and a call
  that changes a list, copy chains, dead locals with effectful and allocating
  initializers (the calls still run, the store does not), a discarded
  overflow (`Int` max + 1) and a discarded division by zero through
  `may { } otherwise { }` (faults preserved), a captured local, and a while
  loop. Its output is in `tests/legacy_behavior.json`.
- `tests/oracle.py` compiles every behaviour fixture, this one included, with
  and without `--no-opt` and requires identical exit status and output.
- Final validation on the committed build: `verify.py` 133 passed, 0 failed
  (132 before plus the new fixture); `raw_codegen.py`, `backends.py` and
  `oracle.py` (57 fixtures) pass; `compiler/rust/test.py` passes with
  byte-identical stage 2 and stage 3.

## Limits and follow-ups

- No cross-block value numbering, LICM or inlining: a repeated load is only
  reused inside one straight-line region. Binary trees would need dominates-
  based CSE for `node.left` across the `if`, worth about one probe per check
  call.
- Functions with `may`/`otherwise` regions are declined, as are raw and
  native-word functions (the latter already have the raw backend's DCE).
- The CSE share depends on what a field read costs. Under
  [#134](https://github.com/mirged/maylang/issues/134) typed struct reads
  become guarded slot loads, so the measured n-body win should be re-checked
  after that lands; the dead-copy, dead-label and dead-store parts do not
  depend on the field-layout representation.
- The pass is deliberately conservative about effects; a call drops every load
  entry even when it cannot reach the object. A future pass can add alias
  information rather than weakening this rule.
