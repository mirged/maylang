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

## Inlining retry (round 2) — measured, not merged

The [roadmap](../../../../docs/design/PERFORMANCE_ROADMAP.md#phase-4-ir-optimizer)
records a first leaf inliner that was behaviour-clean but lost: binary trees
1.79 s → 1.86 s, everything else flat, because the call was small next to the
map insertion a constructor performed. Since then #132's register-argument
direct calls are in the base, so this increment retried the same shape to see
whether erasing the remaining call overhead pays. It does not pay on the suite,
so the code and its fixture were reverted; the evidence is recorded here.

### What was implemented (then reverted)

An IR inliner (`src/ir_inline.may`) ran before the propagation passes, skipped
under `--no-opt` and `--debug`. It cloned straight-line bodies (no branches, one
trailing return, no locals or parameter writes, at most 24 quads) of fat
functions into call sites with matching arity: parameter reads became the
argument values, so every argument is evaluated once at the original site; the
body runs in the caller's position, so evaluation order, effects and faults are
unchanged; the callee name must not be shadowed by a caller local, parameter or
global. Bodies that call through a parameter are excluded (that parameter name
would not resolve in the caller), as are the calls the backend lowers before
function resolution (`__math_high`, `__math_low`, `__math_bits`,
`__join_list`), raw/native functions, closures and captures, and callers with an
exception region. Budgets: 24 quads for a body, 220 inlined instructions per
caller, 3000 per program. The callee stays in the image.

Correctness was clean on that build: all eight xlang programs printed identical
output and `oracle.py` passed 62/62, with a new `tests/inline_opt.may` fixture
covering evaluation order, effects in arguments, inlined-body faults,
call-through-parameter, a local shadowing a function name, a captured local and
`--no-opt` parity. The fixture and its `legacy_behavior.json` entry were
reverted with the pass.

### Measurements

Integrated base `62c3c45` (candidate compiler sha `6be0410d`), child CPU time,
interleaved before/after, xlang workloads. Twenty paired runs; "paired median"
is the median of the per-round before/after difference, which cancels the host
load drift that made the side medians noisy (the machine was shared). A
15-pair run earlier the same evening moved the same benchmarks by at most 2%
either way.

| Benchmark | before / after, ms | paired median | image |
| --- | --- | --- | --- |
| fib (control, native-word) | 68.3 / 68.9 | -0.2% | 109,976 → 105,800 |
| collatz | 125.3 / 105.9 | -0.0% | 105,640 → 105,560 |
| sieve | 284.2 / 266.1 | -1.2% | 109,856 → 109,784 |
| hashmap | 134.8 / 137.0 | +3.1% | 109,872 → 109,800 |
| strings | 99.6 / 85.0 | -0.1% | 109,800 → 109,728 |
| mandelbrot | 49.3 / 49.1 | -0.0% | 109,736 → 109,656 |
| n-body | 89.0 / 87.4 | +0.3% | 142,944 → 142,872 |
| binary trees | 1319.9 / 1310.5 | -0.5% | 110,384 → 110,272 |

There is no suite movement beyond the spread. The only user function the suite
offers the inliner is trees' `Node` constructor (11 quads, inlined at both
sites in `make()`); the other programs call builtins, raw runtime helpers,
recursive functions or bodies that exceed the budget.

Inlining-shaped microbenchmarks
([sources](inlining/), 12 paired runs) show where the shape does pay:

| Microbenchmark | before / after, ms | change |
| --- | --- | --- |
| one-expression helper in a hot loop | 24.6 / 11.4 | **-53.6%** |
| struct field accessor in a hot loop | 44.2 / 28.9 | **-34.6%** |
| struct constructor wrapper in a hot loop | 793.9 / 774.2 | -2.5% |

Compile cost, same interleaved method: `features.may` +2.5% (earlier 15-pair run
+5.6%), the compiler compiling itself **+16.3%** (earlier run +10.0%), and the
compiler image the candidate produces **+2.4%** (3,019,048 → 3,091,944 bytes)
because library helpers are inlined into the compiler. This is the cost that
decides the result: a default-on inliner buys no suite movement and slows the
compiler.

### Refined negative

- What the calling convention fixed: constructor inlining no longer *regresses*.
  Binary trees is -0.5% (paired median; -2.6% by minimum) instead of the earlier
  +4%, and the constructor microbenchmark is -2.5%. Argument registers removed
  the argument-vector and padding work the old attempt paid for.
- What it did not fix: the suite has no hot small-call shape to erase. Helper
  and accessor calls are where a call still dominates (-53.6% and -34.6% on the
  microbenchmarks), but none of the eight workloads has one in a hot loop, and
  constructors stopped being call-bound: #134 makes a constructor body one
  allocation plus fixed-slot stores.
- Keep the inlining item open in #131 for a targeted form: an opt-in flag, or a
  pass that only inlines non-allocating accessor/helper calls (which is cheap),
  until a suite workload or the compiler itself has that shape. A default
  general-purpose inliner should not merge on this evidence.

Raw samples: [inlining-performance.json](inlining-performance.json) — suite,
compile and microbenchmark samples, compiler identities and image sizes.
