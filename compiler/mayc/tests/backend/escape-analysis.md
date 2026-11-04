# Escape analysis — issue #131, measured not merged

The [roadmap](../../../../docs/design/PERFORMANCE_ROADMAP.md#phase-4-ir-optimizer)
asks for "escape analysis: stack-allocate or scalar-replace records and lists
that do not escape their function (n-body's per-step temporaries)". Two
increments came out of it: a caller-side escape analysis that lands as a
report-only diagnostic, and a scalar replacement built on it that was
implemented, measured green, and then reverted because the workloads the item
names do not contain the shape it removes. This page and its raw samples are the
deliverable; the workspace stays committed with the analysis only.

## What the analysis can prove, and why the premise is wrong

A `struct` constructor is not inlined at its call sites. The parser emits it as
a generated function whose body is one `rt_struct_new(n)`, one `rt_struct_set`
per entry reading the parameters in declaration order, and a return of the new
record (`parser.may` `parse_struct`). Every record allocation therefore lives
inside a constructor function and is returned, so an *intraprocedural* escape
analysis of the allocation - the form the issue describes - has nothing to
prove: the record always escapes through the return. The useful question is the
caller's: does the record a constructor call returns escape the function that
called it?

The landed analysis answers exactly that, for the generated-constructor shape.
A call to it builds a fresh record that nothing can alias yet, so the caller's
IR decides the answer. When every use of the call result is a copy, a local
declaration or a typed fixed-slot field read (`E_GET` with a field index) in the
same straight-line block and after the call, the record provably does not
escape the caller. It runs only when `MAYC_ESCAPE_REPORT` is set, only on fat
functions, and never rewrites the IR, so `--no-opt` and `oracle.py` parity are
unaffected. Exception-region and raw/native functions are declined like the
other passes.

`MAYC_ESCAPE_REPORT=1 mayc prog.may -o /tmp/prog 2> report` prints one
`mayc-escape-fn:` line per function that calls a generated constructor and one
summary line:

```
mayc-escape: constructors=81 calls=172 candidates=0 reads=0 escaped=172 record_allocs=81 local_record_allocs=0
```

`candidates` are call results that provably stay in the caller; `reads` are
typed field reads a scalar replacement could take over; `record_allocs` counts
generated struct constructors and `local_record_allocs` the `rt_struct_new`
instructions outside them (only enum variant constructors, which the analysis
declines: a variant's tag entry is a string literal, not a parameter copy).

On the whole roadmap suite and the compiler image
([probes](escape-analysis/escape-analysis-probes.json)):

| Compile unit | constructors | constructor calls | non-escaping results | replaceable field reads |
| --- | ---: | ---: | ---: | ---: |
| fib, collatz, sieve, hashmap, strings, mandelbrot | 0 | 0 | 0 | 0 |
| n-body | 1 | 5 | 0 | 0 |
| binary trees | 1 | 2 | 0 | 0 |
| the compiler image (`mayc` compiling `compiler/mayc/main.may`) | 81 | 172 | 0 | 0 |
| microbenchmark `construct_read` (the shape) | 1 | 1 | **1** | **1** |

**n-body has no per-step record temporaries.** It constructs its five `Body`
records once, in the top-level `bodies` list literal; `advance` and `energy`
only read records out of that list and mutate their fields, so the five
constructor calls escape into the list before `advance` runs even once. The
analysis moves zero instructions there. Binary trees is the same: both `Node`
calls are returned into the tree.

In the compiler image none of the 172 constructor calls stays in its caller.
The results are stored into maps/lists, returned, or passed to another call -
the compiler is a data-structure builder by nature. The analysis is
deliberately conservative about what it cannot follow (a mutable binding, a
temp with definitions in two branches, a read crossing a block), and those
cases decline the whole site; after that, zero sites remain. That is the
structural result this item needed: **a scalar replacement of non-escaping
records cannot pay on the current suite or the compiler, because neither
contains a non-escaping record.**

## The rewrite — implemented, measured, reverted

The rewrite the analysis enables is the safe form the task describes: delete
the constructor call (allocation, header writes and slot writes), the copies
that only carried the reference and the typed field reads, and replace each
read with the call argument the constructor copied into that field slot. It
keeps evaluation order and faults: the arguments were already evaluated before
the call and stay; a typed field read of a record is total (`fat_field_get`
falls back to the cache probe and then `rt_field_get`, never faults); the
allocation's only failure mode is the runtime's out-of-memory exit
(`rt_alloc_kind`), not a catchable fault; and the runtime exposes no final
state or identity of an unreachable record. Every rewritten position updates
both the quad's arg fields and its payload operands.

Validation on the build with the rewrite enabled: `oracle.py` 67 passed, 0
failed (every behaviour fixture compiled with and without `--no-opt` printed
the same output); the two microbenchmarks and six extra probe programs
(multiple fields, `Float` fields, nested constructors, compound reads) printed
the same output with and without `--no-opt`.

### Measurements

Intel i5-13500H, Linux 6.12, the full runtime, identical sidecar hashes on both
sides. The host was shared (load average 3.7–3.5), so child CPU time
(`user+sys`) of whole-process runs is the metric and the runs are interleaved:
each round runs both compilers, alternating the order, 9 rounds after one
warm-up; every child was pinned with `taskset -c 4`. "Paired" is the median of
the per-round before-minus-after difference, which cancels load drift; positive
means the candidate was faster. Every program printed identical output on both
sides.

Compilers: before `a4b53e88cff830e51a31126bd21446ef86968455595e82021f1014a7df5dadac`
(analysis only), after `8a28a94ea3686eaee11078a88953d8bf13f813d8aaa2b817c33f4d8ea115ec35`
(the same build with the rewrite enabled). Harness:
[run.py](escape-analysis/run.py), raw samples
[escape-rewrite-performance.json](escape-analysis/escape-rewrite-performance.json).

| Workload | before, ms | after, ms | change | paired | peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| `construct_read` — the shape | 759.9 | **11.9** | **-98.4%** | **-98.4%** | 254 → 18.6 MiB |
| `construct_escape` — control | 10.9 | 10.8 | -1.3% | +1.3% | 40 MiB |
| n-body | 86.1 | 85.9 | -0.2% | +0.1% | 18.6 MiB |
| binary trees | 914.3 | 912.0 | -0.2% | +0.2% | 236 MiB |
| compiler self-compile | 2779.0 | 2800.2 | +0.8% | -1.5% | 488 MiB |

The rewrite is a large win where the shape exists: -98.4% CPU and -93% peak RSS
on `construct_read` (20M iterations, one `Pair` constructed and one field read
per iteration). The control, the suite and the compiler self-compile are inside
the host's spread; the sign of the side and paired medians disagrees for each of
them. Two more facts settle it:

- The compiler images the before and after compilers produce from
  `compiler/mayc/main.may` are **byte-identical**
  (`sha256 8a28a94ea3686eaee11078a88953d8bf13f813d8aaa2b817c33f4d8ea115ec35`,
  3,199,344 bytes): the rewrite emits no different instruction anywhere in the
  compiler image. This is the measurement artefact of the zero counts above.
- The only applications are the hand-written microbenchmark and its variants;
  no file in the suite or the compiler has a constructor result that stays in
  its caller.

Decision: per the item's bar (n-body and the compiler self-compile must pay) the
rewrite does not pay, so its code was reverted. The analysis that identifies its
sites lands below, and the two microbenchmarks plus the harness stay in the tree
as the decision set for a future attempt (`inlining/` was kept the same way
after the inliner revert). An opt-in form, or an inliner that exposes the shape
in real code, is where the -98% would become reachable: inlining a constructor
body into a loop is this same transform with the call removed first.

## Landed: the report-only analysis and its cost

The analysis itself is output-identical and changes no IR, so behaviour is
unchanged by construction; `verify.py` (including `oracle.py`) and the
bootstrap fixpoint run on the committed build. A normal compile pays one
`env("MAYC_ESCAPE_REPORT")` lookup - a second `/proc/self/environ` read, the
arena-size check already does one - and passes an empty constructor table, so
the analysis is skipped entirely.

Measured against the pristine `main@2def37e` compiler, 11 interleaved rounds on
CPU 4 (raw samples
[analysis-cost-performance.json](escape-analysis/analysis-cost-performance.json)):

| Compile | pristine, ms | analysis, ms | side | paired |
| --- | ---: | ---: | ---: | ---: |
| compiler self-compile | 2628.3 | 2648.0 | +0.75% | -0.95% |
| `examples/features.may` | 108.5 | 107.6 | -0.85% | +0.85% |

The side and paired medians disagree in sign for both, so the landed default
path is below this shared host's noise floor.

## Reproduce

- Counts: `MAYC_ESCAPE_REPORT=1 compiler/mayc/mayc_new <program>.may -o /tmp/x 2> report`;
  the suite and compiler-image table comes from
  [escape-analysis-probes.json](escape-analysis/escape-analysis-probes.json).
- Rewrite numbers: build the compiler with the rewrite enabled, then
  `python3 compiler/mayc/tests/backend/escape-analysis/run.py OLD_MAYC NEW_MAYC out.json --rounds 9 --self-compile --cpu 4`.
  The workloads are [construct_read.may](escape-analysis/construct_read.may)
  and [construct_escape.may](escape-analysis/construct_escape.may); n-body and
  binary trees are read from `xlang/may/`.
- The rewrite itself is not in the tree: a future attempt re-adds it behind the
  analysis's candidate test and reuses these two microbenchmarks plus n-body and
  the self-compile as the decision set.
