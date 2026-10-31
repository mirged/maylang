# Register-allocated fat code — issue #96

Dynamic (fat) code on x86-64 kept every IR temporary and local in a 16-byte
frame slot. An expression left its value in RDX (type word) and RAX
(payload), and the next instruction usually reloaded it from memory. A
temporary skipped its store only when its one reader came right after it.
Loops stored and reloaded both words around every operation, and every
comparison built a `Bool` and then tested it. Float arithmetic called a
shared stub per operator.

## Changes

All of the changes are in `src/backend/x86_64_fat.may`, apart from one
runtime line and one intrinsic.

- **Exact reader counts.** `lsra_operands` counts operands conservatively.
  An operation whose payload names its operands also carries them in
  `arg1`/`arg2`, so every binary operand was counted twice and its store was
  never skipped. `fat_exact_uses` counts what fat code actually reads.
- **Dead copies.** An `IR_COPY` whose target nothing reads, such as the value
  of an `if` statement, emits nothing and no longer counts as a reader of
  its source (`fat_plan_dead_copies`). A result nothing reads is not stored.
- **Forwarded temporaries.** Some temporaries emit no code where they are
  defined (`fat_plan_forwarding`, `fat_forward`). A reader loads the value
  from its source, directly into the registers it needs (`fat_materialize`):
  - a constant defined once: a literal, `nil`, `true` or `false`;
  - a single read of a local or global variable that nothing can change
    before the temporary's last reader. In between, there is no assignment
    or declaration of that name, and no call, runtime call or closure
    (`fat_variable_stable`).
- **Compare and branch.** A comparison whose only reader is the branch that
  follows it compares and jumps (`fat_branch_compare`). Dead copies in
  between are skipped.
- **Immediates.** A right operand that is an Int constant fitting a
  sign-extended imm32 is used as an immediate for comparisons, `+`, `-`
  and `*`. Its type check is dropped (`fat_binary_immediate`). `/` and `%`
  by a constant power of two (2 to 2^31) use shifts. A negative dividend
  is biased so that the result truncates toward zero and the remainder
  keeps the dividend's sign. A constant divisor other than 0 and -1 skips
  the divisor check before `idiv`.
- **Inline Float paths.** When either operand of `+ - * /` or a comparison
  is statically `Float`, the operation runs inline with SSE
  (`fat_float_inline`, `fat_float_jump`). The static type is only a layout
  hint: both type words are still checked, and other operands, or a zero
  divisor of either sign, take `rt_binary`. NaN compares unordered, so only
  `!=` holds.
- **Out-of-line slow paths.** Slow paths (`rt_binary`, the Float stub, the
  generic branch) are emitted after the function (`fat_emit_deferred`).
  Fast paths fall through instead of jumping over them.
- **Register homes for locals.** Up to two locals per function live in
  callee-saved register pairs, RBX/R12 and R13/R14, holding the type word
  and the payload (`fat_plan_homes`, `fat_declare`, `fat_load_pair`). A
  candidate must meet all of these:
  - declared once, as a parameter or one `let`, so that no shadowing local
    shares the pair;
  - not captured by a closure;
  - used inside a loop.

  Candidates are ranked by uses, weighted 8× per loop level, with ties
  broken by first use, so every bootstrap stage chooses alike. The
  prologue saves the pairs below the frame's slots, and the epilogue
  restores them. A function containing a handler gets no homes: a fault
  restores callee-saved registers to their values at the handler's start,
  which would undo assignments made in the protected body. Callers stay
  correct through faults because `x86_handler_begin` already saves and
  restores RBX and R12–R15, and the fiber switch saves them as well.
- **Collector roots.** `rt_gc` marks RBX and R12–R15 (`__callee_saved(k)`,
  a new raw intrinsic) before scanning the stack. A function between
  compiled code and the collector either leaves those registers alone or
  saves them in its stack frame, which the scan covers. In practice the raw
  runtime functions on the allocation path (`rt_alloc_kind`, `rt_gc`) save
  the registers they use in their frames, so the scan already found every
  register value. An instrumented collector run over the fixture,
  `stress.may` and a self-compile with a 1 MiB heap found no register that
  was the only root. The marking keeps homes correct without depending on
  how the runtime's own code allocates registers.

Fat code also got smaller: the compiler binary, which is fat code, went
from 3.02 MB to 2.42 MB.

## Measurements

[`fat-registers-performance.json`](fat-registers-performance.json) holds the
raw samples, taken with [`fat_registers/run.py`](fat_registers/run.py)
(`--rounds 7 --self-compile`) on an Intel i5-13500H under Linux 6.12.
Seven interleaved rounds ran after a warm-up and an output check. "Before"
is `main` at `697a107`. The machine was running other jobs, at load average
3.3–3.8, so absolute times are inflated. Interleaving affects both sides
alike. The values are median CPU times. Every workload printed the same
output on both sides, and peak RSS was unchanged.

| Workload | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| `int_loop`: Collatz steps for seeds up to 300 000 in a fat function | 760 ms | 263 ms | 2.9× |
| `collatz_top`: the same at top level (the xlang benchmark) | 731 ms | 259 ms | 2.8× |
| `float_loop`: Mandelbrot, 600×600, 100 iterations, in a function | 953 ms | 306 ms | 3.1× |
| `nbody`: 200 000 steps (the xlang benchmark) | 558 ms | 285 ms | 2.0× |
| `list_loop`: List<Int> reads and writes, 30M elements | 784 ms | 415 ms | 1.9× |
| `closures`: 20M calls through composed closures | 828 ms | 569 ms | 1.5× |
| `map_loop`: 8M Int-key map updates | 780 ms | 717 ms | 1.09× |
| `stress`: `compiler/mayc/tests/stress.may` | 460 ms | 430 ms | 1.07× |
| `self_compile`: mayc compiling `compiler/mayc/main.may` | 5 966 ms | 5 589 ms | 1.07× |

Self-compilation is dominated by allocation and collection (`rt_fit`,
`rt_candidate`, `rt_gc`), and its samples varied from 5.0 to 7.5 s under
this load. A separate run of 12 interleaved pairs, timing only the two
compilers, gave a median of 5 428 ms before and 3 999 ms after, with the new
compiler faster in all 12 pairs. The compiler's own code runs faster
(`name_eq`, `e8`, `glob_find`), and the new planning passes allocate little.
A first version used string keys for each slot access and an operand list
per instruction, and self-compiled slower; that was fixed before these
measurements.

`map_loop` and `closures` spend most of their time in runtime calls (map
hashing, closure calls), which this change does not touch. In `int_loop`
and `float_loop`, what remains is mostly type-word checks and moves between
the register pairs and the operand registers. Using static types to drop
those checks is the next item of roadmap phase 3.

## Validation

- `compiler/mayc/tests/fat_registers.may` is a new feature fixture. Its
  expected output was produced by the `697a107` compiler, so it is an
  oracle against unoptimized code. It covers:
  - the six comparisons with immediates, as values and as branches;
  - `+ - *` with immediates, including overflow faults;
  - `/` and `%` by 2, 4, 8, 1024 and 2^31 on positive, negative and extreme
    dividends, and by 3 and 1;
  - division by 0 and -1;
  - `Any` operands of other types, which take the runtime's paths and
    faults;
  - Float arithmetic, comparisons and branches with NaN and -0.0;
  - Float division by zero of either sign, and mixed Int/Float operands;
  - evaluation order between variable reads and calls that assign them;
  - `if` values;
  - register homes, with:
    - shadowing inside a loop;
    - swapped tail-call arguments;
    - a handler in the same function;
    - a callee catching a fault raised below it;
    - captured locals;
    - collections with heap values in homes;
    - maps;
    - fibers;
    - top-level loops.
- The new compiler produces identical output to the old one on every
  workload above.
- With the rebuilt compiler, all of these pass:
  - `make check`;
  - `make test-compiler`: 125 passed, including `raw_codegen.py`,
    `backends.py` and `regalloc.py`;
  - `make test-compliance`: 65 passed;
  - `make test-tools`, `make test-docs`, `compiler/mayc/tests/gc.py` and
    `make test-limits`;
  - `make test-bootstrap`: stage 2 equals stage 3.

## Limits and follow-ups

- Only two locals per function get homes, and only callee-saved registers
  are used. Temporaries that live across a loop iteration (multiply
  defined, or pinned) still use frame slots.
- Type words are still checked on every operation. With strict types they
  are usually known, which would allow single-word homes (five per function)
  and no checks (phase 3, "use static types").
- A function containing a handler gets no homes.
- The register marking in `rt_gc` would also let non-leaf raw runtime
  functions keep heap pointers in callee-saved registers. Optimizing them
  (the `x86_leaf_block` restriction from #99) also needs the collector to
  accept interior pointers, which address folding produces.
