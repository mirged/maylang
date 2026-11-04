# Opt-in accessor/helper inliner — issue #131, default-off

The [roadmap](../../../../docs/design/PERFORMANCE_ROADMAP.md#phase-4-ir-optimizer)
inlining item was tried twice and never merged: a general leaf inliner was
behaviour-clean but bought no suite movement while slowing the compiler
(self-compile +8.5-16.3%, image +2.4%), so the first attempt was reverted and
the second kept the item open "for an opt-in or accessor-only form". This is
that form: the pass is behind a new default-off `--inline` flag, and it only
clones function bodies that are guaranteed small, straight-line and effect-free
at the body level - the accessor and one-expression-helper shapes that measured
-35% and -54% in the earlier microbenchmarks.

## What is inlined

A callee is inlinable when its whole body is straight-line, at most 24
instructions, ends in one `IR_RETURN`, and contains only parameter reads,
`IR_COPY`, literals, field and element reads, arithmetic (`E_BIN`/`E_UN`/
`E_POW`), range construction and `nil` (`src/ir_inline.may`). Calls, runtime
calls, stores, local declarations, closures, captures and every control transfer
disqualify it. A body reading a global (anything that is not a parameter) is
declined because the name could resolve differently in the caller, as are
closure bodies and functions with captured or boxed parameters.

Cloning reproduces each instruction at the call site (both the quad's arg fields
and the payload operands; `E_UN`/`E_POW` keep operands only in the payload),
maps callee temp slots to fresh caller slots one-to-one (so the lowering's
snapshot copies keep their semantics), substitutes parameter reads with the
call's argument values and turns the return into a copy of the result slot.
Evaluation order is unchanged - the arguments were evaluated before the call and
stay - and every fault the body could raise (division, overflow, the
`E_UN`/`E_POW` runtime paths) is raised by the same instruction at the same
point. `--no-opt`, `--raw` and `--debug` skip the pass; the caller must not have
an exception region and must not shadow the callee name with a local, parameter
or global. The inliner runs before `ir_opt_program`, so the normal propagation
and DCE passes clean up the copies it introduces.

Default path unchanged: with the flag off, the compiler builds byte-identical
executables for all eight cross-language benchmarks compared with the previous
commit's compiler (`sha256` of each output equal). `--inline` is documented in
`--help` and in the compiler README.

## Measurements

Intel i5-13500H, Linux 6.12, full runtime. Child CPU time (`user+sys`) of
whole-process runs, interleaved: each round runs every command once per side,
alternating the order, 25 rounds after one warm-up; every child was pinned with
`taskset -c 4`. Both sides are the **same compiler binary**
`567b252aa2ae9372f95e3fe94dd932edae3aa16d4463796675f2c8da0d684ce1`; "default"
compiles without `--inline`, "inline" with it, which isolates the pass. "Paired"
is the median per-round default-minus-inline difference (positive = inline
faster). Every run workload printed identical output on both sides.

Harness: [inlining/run.py](inlining/run.py); raw samples
[fat-inlining-performance.json](inlining/fat-inlining-performance.json). Host
load average 4.6/3.7/3.1.

| Workload | default, ms | `--inline`, ms | change | paired | inline faster in | minima |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| field accessor in a hot loop | 45.2 | **27.5** | **-39.2%** | +38.7% | **25/25** | 44 / 27 |
| one-expression helper in a hot loop | 24.9 | **6.7** | **-73.0%** | +73.3% | **25/25** | 24 / 6 |
| constructor wrapper in a hot loop | 599.6 | 602.3 | +0.5% | +0.1% | 13/25 | 561 / 561 |
| fib | 56.6 | 56.8 | +0.4% | -0.0% | 12/25 | 55 / 55 |
| collatz | 42.8 | 43.3 | +1.1% | -0.3% | 10/25 | 42 / 42 |
| sieve | 193.4 | 190.7 | -1.4% | -0.3% | 11/25 | 180 / 181 |
| hashmap | 89.5 | 89.5 | -0.1% | -0.0% | 12/25 | 84 / 83 |
| strings | 45.6 | 45.4 | -0.3% | -0.6% | 11/25 | 42 / 42 |
| mandelbrot | 44.6 | 44.8 | +0.5% | -0.1% | 12/25 | 44 / 44 |
| n-body | 76.0 | 76.2 | +0.2% | +0.0% | 13/25 | 74 / 74 |
| binary trees | 867.9 | 871.8 | +0.4% | +1.1% | 17/25 | 815 / 815 |
| compiler self-compile | 2676.2 | 2835.7 | **+6.0%** | -4.2% | 6/25 | 2597 / 2705 |
| `features.may` compile | 110.1 | 109.1 | -0.9% | -0.9% | 7/25 | 101 / 103 |

What the compiler reports with `MAYC_INLINE_REPORT=1` explains the table:

- **The two accessor/helper microbenchmarks inline one call each (4 and 3
  instructions) in every round, and all 25 paired samples improve** - this is
  the shape the flag exists for.
- **The eight suite programs have no inlinable callee at all** ("callees=0"), so
  their `--inline` executables are byte-identical to the default ones; the
  table's movement is measurement noise. The suite calls builtins, runtime
  helpers and recursive/constructor functions, exactly as the earlier reports
  found.
- The constructor-wrapper microbenchmark is not inlined (its body is a
  constructor call, which the shape excludes) and is flat.
- `features.may` reports "callees=1 sites=0": nothing inlines, so its -0.9% is
  noise with byte-identical output.
- **The compiler self-compile is the only real cost: 4 prelude helpers inline at
  62 sites (385 instructions), making it 6.0% slower (6/25 rounds faster, paired
  median -4.2%, a 4% worse minimum).** That is the accepted trade of an opt-in flag rather than the
  default: a user who asks for the transform pays code size and compile time for
  the call sites it makes cheap. The compiler's own build does not pass the flag,
  so the shipped compiler is unaffected.

Decision: land as an opt-in flag. The roadmap workloads contain none of the
shape, so this cannot move the suite - the same structural limit as the
escape-analysis item - but the transform is a large win where the shape exists,
the default path is byte-identical, and the flag is the form the roadmap asked
to keep open. The general default-on inliner remains rejected on the earlier
measurements; this pass does not claim it.

## Validation

- `tests/oracle.py` now compiles every behaviour fixture with `--inline` in
  addition to the default and `--no-opt` builds, and requires identical exit
  status, stdout and stderr; `verify.py` runs it.
- New fixture `tests/inline_opt.may` covers accessor and one-expression-helper
  calls in a function body, argument evaluation order with effects, an
  arithmetic fault inside a cloned body reaching the caller's `may` handler, and
  a list read past the end keeping its `nil` behaviour.
- The eight suite programs and the microbenchmarks printed identical output on
  both sides in the measurement harness.

## Reproduce

```
sh compiler/rust/build.sh
python3 compiler/mayc/tests/backend/inlining/run.py compiler/mayc/build/bin/mayc_new \
    out.json --rounds 25 --throughput --cpu 4
MAYC_INLINE_REPORT=1 compiler/mayc/mayc_new --inline prog.may -o /tmp/prog 2> report
```

The report line is `mayc-inline: callees=<n> sites=<n> instructions=<n>`; it is
only produced when the flag is on, so the default compile pays nothing for it.
