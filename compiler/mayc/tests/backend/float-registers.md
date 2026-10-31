# Floats in XMM registers and versioned parameters

The [proven-types](proven-types.md) change dropped the type checks of
proven Floats, but Mandelbrot did not speed up. Every Float operation still
moved both operands from general registers into XMM0 and XMM1 with `movq`,
moved its result back, and stored it in a 16-byte frame slot that the next
operation loaded again. All of that sat on the loop's chain of dependent
multiplications. In the benchmark as written, the values were not even
proven: `cr` and `ci` derive from the `Int` parameter `size`, and
annotations are not proofs.

This change makes two improvements. A function can be specialized for its
annotated parameter types. Proven Floats stay in XMM registers.

## Changes

All of the changes are in `src/backend/x86_64_fat.may`.

### Versioned functions

A strict function qualifies for a second body when all of these hold:

- at least one parameter is annotated `Int`, `Float` or `Bool`;
- it has no captures;
- it contains a loop;
- it has no tail call and no handler;
- its IR has at most 4 000 instructions;
- assuming the annotated types proves more temporaries (`fat_versioned`).

Such a function gets two bodies:

- a **specialized** body, in which those parameters start at their
  annotated type in `fat_plan_types`;
- the **generic** body, which is the same code as before.

Annotations can be bypassed through `Any`, so the function's entry compares
each such argument's type word with the annotation (`cmp qword [rsp + d],
type`). It falls through to the specialized body only when every one
matches, and otherwise jumps to the generic body.

Behaviour is therefore unchanged for every argument, including a `Float`
passed to an `Int` parameter through an `Any` alias. The specialized body
places fresh labels for the IR's labels (`FAT_LABEL_MAP`).

Tail calls are excluded because they store new arguments straight into the
parameter slots, and those arguments are never checked. Handlers are
excluded for simplicity.

### XMM homes

A local proven Float gets a home in one of XMM8–XMM15. Those registers come
in addition to the five general-register homes, so Float locals no longer
compete with Int locals.

The System V ABI saves no XMM register, and any call can run any Maylang
function or C code. Every call that a body emits therefore stores the XMM
homes in their own frame slots and reloads them afterwards
(`fat_call_begin`, `fat_call_end`). That covers:

- runtime calls (`fat_rt_call`);
- stub calls, including the out-of-line slow paths, because `rt_binary`
  can call a function stored under an operator on a map;
- direct calls and closure calls;
- `__ccall6`;
- closure allocation.

Fibers switch inside runtime calls, so they are covered too. Float payloads
are never pointers, so the collector needs no XMM roots.

### XMM temporaries

A proven Float result of `+`, `-` or `*` qualifies for one of XMM2–XMM7
when it is defined once and every instruction before its last reader emits
no call (`fat_xmm_safe`). Such instructions are:

- constants and copies;
- reads and stores of variables that need no cell;
- arithmetic on proven numbers, whose slow paths only raise faults.

The registers are assigned in order of definition and are reused after
their last reader. A temporary in a register is never stored. Its readers
take it as an XMM operand, or as a Float in RDX/RAX through `fat_get`.

### XMM operations

`+`, `-`, `*` and comparisons on two proven Floats read their operands
straight from XMM homes and temporaries, and their constants from an
immediate (`xorpd` for +0.0). They write into the result's register. A
store of an XMM value into an XMM home is a single `movapd`.

Comparisons, whether fused with a branch or not, use `ucomisd` with the
existing NaN rules. None of these operations has a slow path. `/` still
takes the general path, which checks for a zero divisor of either sign and
raises the arithmetic fault.

## Measurements

[`float-registers-performance.json`](float-registers-performance.json)
holds the raw samples, taken with [`fat_registers/run.py`](fat_registers/run.py)
(`--rounds 11 --self-compile`) on an Intel i5-13500H under Linux 6.12.

- **Load:** another workload was running, at a load average of 2.6–2.8.
- **Compilers:** "before" is `main` at `76f46a9`. "After" is this change;
  the file records both compilers' SHA-256.
- **Values:** median CPU times. Every workload printed the same output on
  both sides.

| Workload | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| `float_loop`: Mandelbrot in a function | 291 ms | 119 ms | 2.45× |
| `int_loop`: Collatz steps in a function | 222 ms | 223 ms | 1.00× |
| `collatz_top`: the same at top level | 229 ms | 229 ms | 1.00× |
| `nbody` | 262 ms | 265 ms | 0.99× |
| `list_loop` | 396 ms | 388 ms | 1.02× |
| `map_loop` | 674 ms | 680 ms | 0.99× |
| `closures` | 559 ms | 574 ms | 0.97× |
| `stress` | 385 ms | 379 ms | 1.02× |

- **Mandelbrot:**
  - The inner loop now keeps `zr`, `zi`, `cr`, `ci` and the temporaries
    of `zr * zr - zi * zi + cr` in XMM registers.
  - The one `movq` left per iteration loads the constant 2.0, and the one
    `ucomisd` loads 4.0.
  - Its binary grows from 92 264 to 96 360 bytes, because `run` has two
    bodies.
- **n-body:** its Floats are struct fields, which are not proven.
- **Other workloads:** they are within ±3%, which is this run's noise.
- **An earlier run** of 9 rounds at the same load showed the same
  Mandelbrot result. It also showed `int_loop` at 209 ms against 241 ms.
  Interleaved runs of those two binaries then measured 0.230–0.241 s each,
  and this run shows no difference, so that sample is treated as noise.

**Compilation.**
- **Size:** the compiler grows from 2 450 544 to 2 475 120 bytes (+1.0%).
  The growth comes from the second bodies of its few typed functions with
  loops, and from the spill code.
- **Emit time:** the `--time` emit stage over eight interleaved pairs had a
  median of 3 154 ms before and 2 658 ms after. Individual pairs ranged
  from 1.9 s to 3.5 s under this load, so neither a slowdown nor a speedup
  can be attributed.
- **Self-compilation:** 4 881 ms before and 4 778 ms after. As the
  proven-types report notes, it is bimodal.

## Validation

- **Fixture.** `compiler/mayc/tests/float_registers.may` is a new feature
  fixture. Its expected output was produced by the `76f46a9` compiler, so
  it is an oracle against code with neither change. A disassembly confirms
  that its binary contains dispatchers, XMM homes with spills and reloads,
  and XMM temporaries. It covers:
  - **Versioning:** Mandelbrot, plus functions with `Float`, `Int` and
    `Bool` parameters, called directly and through `Any` with Int, Float,
    Str, Bool-like and nil arguments. It also covers a parameter
    reassigned with another type, and a tail-calling function.
  - **Homes across calls:** a callee that has its own XMM homes, closures
    and runtime calls in the loop, and a map operator whose function runs
    from the out-of-line path of an unproven `+`.
  - **Register pressure:** ten Float locals (more than eight homes), and
    an expression with more than six live temporaries.
  - **Comparisons:** all six operators, fused and unfused, on NaN, ±0.0
    and ±infinity.
  - **Faults:** Float division and its zero-divisor fault.
  - **Other contexts:** a handler body, fibers that yield with Float homes
    live, and top-level code.
- **Checks run with the new compiler:**
  - `make check`;
  - `make test-compiler`, including `raw_codegen.py`, `backends.py` and
    `regalloc.py`;
  - `make test-compliance`, `make test-rust` and `make test-docs`;
  - `make test-bootstrap`: stage 2 equals stage 3.
- **`make test-tools`:** it failed once in the `maypkg` watcher test
  ("watcher left a child process running"), the timing race also seen in CI
  on `main`. It passed on a rerun.

## Limits and follow-ups

- `/` on proven Floats still moves through general registers for its
  divisor check. An XMM path would need the fault's slow path to rebuild
  the fat operands.
- Float constants are rematerialized on every use. A constant pool, or a
  constant home hoisted out of the loop, would remove the last `movq` from
  Mandelbrot.
- Calls spill every XMM home, including ones not live at that call.
  Liveness would make calls in Float loops cheaper.
- `to_float`, unary `-` and Float struct fields still go through the
  runtime or general registers. n-body needs proven field types, which
  depends on the struct-layout work in phase 2.
- Tail-calling functions and functions with handlers are not versioned. A
  tail call could check its new arguments and jump to the matching body.
