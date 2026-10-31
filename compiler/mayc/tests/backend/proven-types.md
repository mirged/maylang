# Proven types in fat code

The register-allocated fat code from #96
([report](fat-registers.md)) still checked the type word of every
operand, and each local in a register home needed two registers: one for
the type word and one for the payload, so only two locals fit. This
change proves which values have a fixed type and uses that proof in two
ways: it drops their type checks, and it lets those locals keep only
their payload in a single register.

## Why not trust annotations

The checker's types are not enough. The language reference says dynamic
aliases can bypass them: a `List<Int>` can receive a `Str` through an
`Any` alias, and a function with an `Int` parameter can be called through
an `Any` value with a `Str` argument. A check that is dropped because of
an annotation would turn a runtime fault or a dynamic dispatch into a
misread payload. The proof therefore comes only from operations whose
result type the runtime guarantees (`rt_binary`, `rt_unary`, `rt_len`,
`rt_to_str`, `rt_to_f`).

## Changes

All of the changes are in `src/backend/x86_64_fat.may`.

- **`fat_plan_types`** is a forward analysis over each function's IR. It
  records the type word that each temporary holds whenever it is read:
  1 for Bool, 2 for Int, 3 for Float, 4 for Str, or -1 when unknown. These
  operations prove a type:
  - literals;
  - comparisons, which always give a Bool or fault;
  - `+ - * / % & | ^ << >>` on two Ints, which give an Int or fault;
  - `+ - * /` on two numbers of which one is a Float, which give a Float;
  - `not` (Bool), and unary `-` and `~` on a proven operand;
  - `len` (Int), `str` (Str) and `to_float` of an Int or Float (Float),
    when no local, global or function of that name hides the builtin;
  - reads of a variable whose every assignment is proven.

  A variable qualifies only when every read of its name reaches the same
  binding:
  - a local declared once that is not a parameter, is not captured, and
    has no global or function of the same name; or
  - a top-level global declared once that no function assigns.

  In both cases the variable must not be read before its declaration in
  code order, where an unset global would still be `nil`. The iteration
  starts optimistic and only ever lowers a type (unknown-yet, then a
  type, then -1), so it terminates. Names are resolved to integer ids in
  one pass first, so the iteration allocates nothing.
- **Checks.** `fat_known_type` returns proven types as well as forwarded
  constants, so Int and Float operations skip the checks of proven
  operands. An operation on two proven Ints emits no Float path and no
  runtime path for other types. A branch on a proven Bool tests only the
  payload.
- **Single-register homes.** Homes come from a pool of RBX and R12–R15.
  A local of a proven type keeps only its payload in one register and
  loads its type word as an immediate. Any other local still takes a
  pair. A function can now keep up to five hot locals in registers
  instead of two. `rt_gc` already marked all five registers.

## Measurements

[`proven-types-performance.json`](proven-types-performance.json) holds the
raw samples, taken with [`fat_registers/run.py`](fat_registers/run.py)
(`--rounds 9 --self-compile`) on an Intel i5-13500H under Linux 6.12, at a
load average of 1.4–2.4. "Before" is `main` at `19f5816`, "after" is
`d64f763`. The values are median CPU times. Every workload printed the
same output on both sides.

| Workload | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| `int_loop`: Collatz steps in a function | 210 ms | 184 ms | 1.14× |
| `collatz_top`: the same at top level | 218 ms | 189 ms | 1.16× |
| `float_loop`: Mandelbrot in a function | 234 ms | 230 ms | 1.02× |
| `map_loop`: Int-key map updates | 552 ms | 533 ms | 1.04× |
| `nbody` | 212 ms | 213 ms | 1.00× |
| `list_loop` | 325 ms | 324 ms | 1.00× |
| `closures` | 456 ms | 461 ms | 0.99× |
| `stress` | 320 ms | 323 ms | 0.99× |

The gain is limited to Int loops. Dropping a check removes a compare and
a branch that the CPU almost always predicts correctly. The Collatz gain
comes mostly from the single-register homes, which keep `n` and `steps`
in registers with no type-word moves. With the checks gone, the Collatz
loop's time goes to the unpredictable `n % 2` branch.

Mandelbrot keeps `zr`, `zi`, `k`, `tr` and `escaped` in registers but
does not speed up. Every Float operation still moves its operands from
general registers to XMM registers and its result back, which adds
latency to a chain of dependent multiplications. Keeping Floats in XMM
registers is the next step. n-body, list, map and closure loops spend
their time on field caches, element accesses and runtime calls, which
this change does not touch.

**Self-compilation** cannot be attributed in either direction. In this
run, mayc compiling `main.may` took 5 708 ms before and 3 559 ms after,
and every sample on each side fell within ±3%. An earlier run of the
same harness, with a first version of the analysis, gave 3 929 ms before
and 6 550 ms after. Peak RSS swapped along with the times (394 MiB
against 456 MiB). That points to the collector's heap growth, which
splits self-compilation into two modes, rather than to the generated
code.

The `--time` stage timings measure the analysis directly. The first
version built string keys for every instruction on every pass. Its emit
stage was about 350 ms (30%) slower than before over eight interleaved
pairs. The committed version resolves names once, and its emit stage
took a median of 2 217 ms against 2 121 ms before (+5%). The total stage
time was unchanged at 4 525 ms.

Binary sizes fall slightly. The Mandelbrot benchmark shrinks from 96 432
to 92 336 bytes, and the compiler from 2 415 992 to 2 383 632 bytes.

## Validation

- `compiler/mayc/tests/proven_types.may` is a new feature fixture. Its
  expected output was produced by the `19f5816` compiler, so it is an
  oracle against unproven code. It covers:
  - proven Int arithmetic and its faults: overflow, division by zero,
    shift range and negation of the minimum;
  - proven Float arithmetic, mixed Int/Float operands, Float division by
    zero of either sign, NaN and -0.0;
  - Bool branches;
  - bindings that must not qualify:
    - a global retyped by a function;
    - a local captured and retyped by a closure;
    - a local named like a function;
    - annotated parameters called through `Any` with Float and Str
      arguments;
    - variables assigned values of mixed types;
    - `List<Int>` elements and `Int` fields written through `Any` aliases;
  - homes:
    - six proven and two unproven hot locals competing for registers;
    - tail calls, handlers and `for` ranges;
    - heap values in pair homes across collections;
    - fibers;
    - top-level code.
- These all pass with the new compiler:
  - `make check`;
  - `make test-compiler`, which includes `raw_codegen.py`, `backends.py`
    and `regalloc.py`;
  - `make test-compliance`;
  - `make test-rust`;
  - `make test-bootstrap`: stage 2 equals stage 3.

## Limits and follow-ups

- List elements, struct fields, call results other than the builtins
  above, parameters, and globals that any function assigns are never
  proven. Proving parameter types would need an entry check on the
  dynamic call path, or a direct-call convention that passes proven
  arguments.
- Floats still travel through general registers. Float homes in XMM
  registers would need spilling around calls, because the System V ABI
  saves no XMM registers.
- Temporaries still live in 16-byte frame slots when they are not
  forwarded. A temporary of a proven type could use a single word.
