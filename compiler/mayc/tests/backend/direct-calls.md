# Direct calls with register arguments — issue #132

A call to a function known at compile time with matching arity no longer
builds the 16-byte argument vector. A fat callee with one to three parameters
receives them as register pairs and a native-word callee receives payloads in
the SysV argument registers, so the caller stores nothing to the stack and the
callee loads no argument from it. The vector remains for every other call:
closures, function values, a legacy arity mismatch, functions with more than
three fat parameters and `--no-opt`.

## Changes

All of the changes are in `src/backend/x86_64_fat.may`.

### The convention

The vector entry of a compiled function finds argument `i` above the return
address: its type word at `[rsp + 8 + 16 i]` and its payload 8 bytes above
that. A direct call instead passes up to three arguments in the pairs
RDX/RAX, RDI/RSI and R8/R9, in that order. Argument 0 uses the result
registers, so it needs no copy: `fat_register_arguments` loads arguments right
to left and leaves argument 0 in RDX/RAX. RDX is a pair's register and also the
scratch register of a load, which is why the native-word path loads parameter 2
last.

A register-callable fat function keeps one body: `fat_body` stores its
parameters from the registers, and its vector entry becomes an adapter that
copies the argument vector into the same registers first, so closures and
function values still work. A versioned function puts its type-word dispatch
after the adapter, so the vector path and the register path share it; the
specialized and generic bodies both start from registers, and a mismatched
argument through an `Any` alias still takes the generic body.

A native-word callee needs no adapter in the compiler: `rec.nativeLab` is the
body's own entry. The direct call checks each argument's type word unless
`fat_known_type` proves it, moves payloads into the SysV registers, calls the
body and tags the result. A type fault jumps to one out-of-line
`rt_word_type_fault` stub per body (`fat_word_fault`), emitted with the
deferred slow paths.

### Deciding where to use it

`fat_plan_direct_calls` runs once, before any body is emitted, over the top
level and every fat function's IR. It marks a callee when a direct call's
argument count equals its parameter count and the callee is a fat body with one
to three parameters and no closure environment, or a native-word body with at
most six parameters. Marking before emission means a callee emits its register
entry whatever the emission order; a caller allocates the label on first use
(`fat_register_label`). A call site only uses the convention when the prepass
marked the callee and the arity matches again at emission; everything else
keeps `fat_direct`.

The register entry is a label created after `emission_begin` registered the
function's own label, so both direct paths call `emission_reference` on
`rec.lab` to keep the function in the reachability queue.

### Limits

- At most three fat arguments travel in registers. The pairs are caller-saved
  integer registers; Float payloads are bits in them, as in the vector.
- A native-word argument whose type a proof does not know keeps its type check:
  two instructions, still fewer than the vector and the fat entry.
- A marked function's closure and function-value calls pay the adapter: two
  loads per argument, then a jump to the body.
- Valid strict source cannot reach the fallback paths for a marked callee
  (the checker enforces arity and argument types), and `--legacy` turns
  native-word lowering off entirely, so the native type check is defensive.

## Measurements

[`direct-calls-performance.json`](direct-calls-performance.json) holds the raw
samples, taken with [`direct_calls/run.py`](direct_calls/run.py) (`--rounds 15
--cpu 2 --self-compile`) on a 13th Gen Intel i5-13500H under Linux 6.12.

- "Before" is `e0f0932`, built in a separate worktree and preserved with its
  sidecars; "after" is this change. The runtime sidecars are identical
  (`77200ff5…`); the compiler images are `b2a42ba3…` and `374f786e…`.
- Every measured child was pinned to CPU 2 with `taskset`: the host has
  P-cores (CPUs 0-7) and slower E-cores, and an unpinned process migrated
  between them, which made one binary measure up to 55% apart. Interleaved
  rounds alternate the order, so load drift hits both sides alike.
- Values are median CPU times of 15 samples after one warm-up; every workload
  printed the same output on both sides.
- Another workload ran on the host during the run, at a load average of 5.7.

| Workload | Before, ms | After, ms | Change |
| --- | ---: | ---: | ---: |
| `fat_call_1`: 20M one-argument fat calls | 31.71 | 26.54 | **−16.3%** |
| `fat_call_2`: 10M two-argument fat calls | 23.93 | 19.31 | **−19.3%** |
| `word_call_1`: 20M one-argument native-word calls | 35.62 | 26.02 | **−27.0%** |
| `word_call_2`: 10M two-argument native-word calls | 26.48 | 19.19 | **−27.5%** |
| fib(35) | 64.33 | 63.56 | −1.2% |
| binary trees, depth 16 | 1962.09 | 1942.06 | −1.0% |
| n-body, 5 bodies × 200 000 steps | 111.62 | 109.41 | −2.0% |
| self-compile: mayc compiling `main.may` | 2952.82 | 2901.27 | −1.7% |

The call-bound microbenchmarks show what the convention saves: a fat call
loses the vector stores, the stack adjustment and the callee's vector loads; a
native-word call loses the fat entry's frame, vector loads and (when the
argument is proven) its type check. Peak RSS is unchanged on every workload
(18.4 MiB for the microbenchmarks, 254.0 MiB for trees, 458.2 → 456.1 MiB for
self-compile).

**fib does not move.** Its recursive calls are native-word code and already
pass arguments in registers (the raw backend does that since #87); only the
single fat call from `main` into it changed, so the difference is inside the
run-to-run spread. The remaining fib gap is the native function's prologue and
callee-saved spills, which the #131 inliner was measured not to pay for.

**Trees and n-body are near the spread** because most of their time is
allocation and map probes (#134, #135), not the calls being made: `make` and
`check` are recursive but small next to the work in their bodies, and n-body's
once-per-step `advance` call is small next to its ten pairwise interactions and
square roots. The compiler itself, which is fat code with many small calls,
gets the same 1.7% as its self-compile, a throughput effect rather than a
benchmark result.

**Code size.** The compiler image shrinks from 3 107 944 to 3 031 088 bytes
(−2.5%): a direct call site no longer emits its vector stores and stack
adjustment, which is more than the adapters cost.

## Tests

- `tests/direct_calls.may` is a new feature fixture, pinned in
  `tests/legacy_behavior.json` from the compiler before the change. It covers
  one, two and three fat parameters, a Bool parameter, a Float parameter,
  native-word callees with one, two, three and six parameters, Bool and Ptr
  parameters and a Bool result, a versioned function whose specialized body,
  generic body and vector entry are all reached, calls in loops, direct and
  mutual recursion, a self tail call, reentrancy, argument evaluation order
  across calls that mutate a global, callees that fault (overflow, division by
  zero, `fail`), and function values for a fat function, a native-word function
  and a captured closure.
- `tests/direct_calls.py` is a new area harness. It compiles every case with
  and without `--no-opt` and requires the same behavior, and covers what a
  strict fixture cannot: the argument-vector fallback for a legacy arity
  mismatch (extra and missing arguments), a parameter of the wrong runtime type
  forwarded through an `Any` parameter of a legacy program, `--debug` traces
  across a chain of direct calls with an uncaught fault, and the strict
  checker's rejection of arity and type mismatches.
- `tests/oracle.py` compiles the fixture with and without `--no-opt` and
  requires identical output, as it does for every fixture.
- With the rebuilt compiler: `make check`; `make test-compiler` (134 checks,
  including `raw_codegen.py` and `backends.py`); `make test-bootstrap`
  (source-only stage 2 equals stage 3).

## Follow-ups

- The remaining call cost is in the callees' prologues and register homes, not
  in the arguments: fib still pays its frame setup and three callee-saved saves
  per recursive call. That is raw-backend work (#131), outside this calling
  convention.
- Fat arguments beyond three could use the remaining callee-saved registers at
  call sites that know the callee does not use them as homes, or an XMM-based
  convention for proven Floats.
