# Unified behavior implementation

The [Unified Behavior System design](../MAYLANG_UNIFIED_BEHAVIOR_DESIGN.md)
is a long-term language and platform proposal.
The active self-hosted compiler implements a closed scalar fragment with inferred
effect sets, explicit ceilings, recursive propagation, and inspectable summaries.
This is an initial implementation, not the design's verified execution profile.

```may
fun double(x: Int) -> Int {
    return x * 2;
}

fun compute(x: Int) -> Int ! pure {
    return double(x);
}

fun display(x: Int) -> Int ! {output} {
    print(compute(x));
    return 0;
}

display(21);
```

See [the runnable example](../examples/behavior.may).

## Supported contracts

Place `! pure`, `! {}`, or `! {output, clock}` after an explicit return type.
`! pure` and `! {}` both declare an empty effect ceiling. Effect rows are sets:
ordering and duplicates do not matter, and a trailing comma is accepted. Unknown
effect names are errors. An unannotated function is analyzed when reachable from an annotated function;
omitting an annotation does not grant authority.

| Effect | Currently recognized operations |
| --- | --- |
| `output` | The runtime `print` primitive |
| `clock` | The runtime `time` and `clock` primitives |

Parameters, returns, and local bindings must explicitly use `Int`, `Bool`, or
`Float`. The checker accepts integer, boolean, and floating-point literals,
parameter/local reads, unary and binary expressions, logical expressions,
typed local bindings, blocks, conditionals, `while` loops, `break`, `continue`,
returns, and direct calls to supported source functions and the
listed primitives. `clock` returns `Float`; `time` returns `Int`. Floating-point
operations use the existing numeric typing and runtime semantics, including
integer-to-float promotion. `Float32`, `Float64`, and dynamic `Any` annotations
remain outside this fragment.

The zero-argument primitives `pi()` and `e()` have explicitly audited empty
effect rows and return `Float`. These rules apply only to the runtime primitives;
source declarations and imported functions with the same names are analyzed
normally, and local/global value shadowing cannot inherit primitive purity.
Arguments are still analyzed and strict arity checking still applies.

```may
fun circle_area(radius: Float) -> Float ! pure {
    return pi() * radius * radius;
}

fun sampled_clock() -> Float ! {clock} {
    let now: Float = clock();
    return now;
}
```

Global reads/writes, collection mutation, strings, callbacks, closures, generic
functions, `for` loops, FFI, and other unsupported AST forms are rejected as unknown.
Declaring all currently known effects cannot authorize unknown operations.
Contracts require strict checking; `--legacy` cannot disable verification.
Other proposed behavior clauses and syntax are not implemented. Programs without
contracts do not run the behavior pass.

## Private scalar state and control flow

Mutable `Int`, `Bool`, and `Float` bindings and by-value scalar parameters may be
assigned within a checked function. Plain and compound assignments only target
that function's mutable local bindings. This private state does not add an
externally visible effect. Assigning immutable `let` bindings is rejected;
assigning globals or captured values remains unknown behavior. Collection,
reference, and object mutation are outside the fragment.

```may
fun sum_to(n: Int) -> Int ! pure {
    mut total: Int = 0;
    while (n > 0) {
        total += n;
        n -= 1;
    }
    return total;
}
```

The checker analyzes a loop's condition and every body statement once, collecting
effects and call edges independently of the iteration count. A false condition,
`break`, `continue`, or early return cannot hide a later effect or unknown
operation from analysis. `break` and `continue` require an enclosing `while`
inside the same function. Block, branch, and loop declarations do not escape
their scopes, and shadowing preserves each binding's mutability.

Accepting a loop does not prove termination, bound its work, or limit allocation.
Unbounded iteration remains possible just as unbounded recursion does. `for`
loops and explicit ranges/collections require additional allocation and aliasing
rules before admission.

## Primitive audit and expansion gates

The strict checker's builtin registry in `src/strict.may` and the runtime bodies
in `native.may` and `runtime.may` are the starting points for this inventory.
A value signature is not an effect summary. Only `print`, `time`, `clock`, `pi`,
and `e` currently have explicit primitive behavior rules; other builtin and
runtime calls remain unknown, including apparently scalar mathematical operations.

| Remaining family | Representative calls | Required semantics before admission |
| --- | --- | --- |
| Input and ambient configuration | `read_stdin`, `input`, `env`, `args` | Distinguish input channels, host configuration and nondeterministic observations; define authority requirements. |
| Filesystem | `read_file`, `read_dir`, `file_exists`, `write_file`, `mkdir` | Specify read, metadata and write effects, path authority, failures and allocation. |
| Processes and native entry points | `syscall`, `system`, `exec`, `wait`, `__ccall6` | Define mediated authority and the native trust boundary; a raw call cannot inherit an empty row. |
| Scheduling and lifetime | `sleep`, `spawn`, `yield`, `run`, `exit` | Define blocking, task lifetime, cancellation and termination effects; sleep is more than a clock observation. |
| Raw memory | `addr`, `cstr`, `ptr`, `load8`–`load64`, `store8`–`store64` | Specify ownership, aliasing, reads, writes and native-memory safety. |
| Failure and recovery | `fail`, `rt_raise`, `__longjmp` | Define typed failure, unwinding and recovery before adding a failure row. |
| Scalar conversions and mathematics | `int`, `bool`, `abs`, `sqrt` | Define accepted value types, dispatch, numeric failures and runtime assumptions before claiming purity. |
| Strings, JSON and collections | `str`, `json_parse`, `push`, `pop`, `map_set`, `sort` | Define allocation, mutation, aliasing and failure; distinguish copying operations from in-place operations. |
| Callback traversal | `map`, `filter`, `reduce`, `any`, `all`, `each`, `times` | Carry callback effects through function types and prevent laundering effects through callbacks. |

These are audit families, not accepted effect names. Each new rule needs valid
unannotated controls, positive contract cases, missing-effect failures,
transitive propagation, shadowing checks and report assertions. Operations with
unresolved semantics must continue to fail closed under every supported row.

The effect-row suite includes valid unannotated controls and unknown-behavior
rejections for 21 representative calls from these families. Those checks use
`--check` so process, memory, filesystem and scheduling operations never execute.
This is representative coverage, not a complete audit of runtime entry points.

## Composition and inference

The checker discovers every annotated function and its reachable source helpers.
Contract roots are visited in declaration order. For each root, newly reachable
bodies are checked breadth first, retaining call order for equal-length paths.
Each body is checked once; recursive edges are recorded without re-entering it.
Helpers need explicit scalar value signatures but may omit effect annotations.
Every discovered body is checked, including unused annotated functions and
syntactically unreachable branches. It records direct primitive effects and call
edges, then repeatedly unions callee effects into callers until no set changes.
This least fixed point accounts for forward calls, recursion, and mutual
recursion, including effects that appear after a recursive edge.

Every annotated function's inferred set must fit its own ceiling. A caller's
broader ceiling cannot excuse a violation inside a callee. Permitted effects need
not occur, so `! {clock, output}` can have an empty inferred row. In this current
whole-source analysis, callers use actual inferred effects; stable separately
compiled behavioral interfaces remain future work.

Calls resolve through existing module/import visibility rules, including
qualified imports and parenthesized direct function references. Source functions
with names matching primitives are checked as source functions. Global values
that shadow function declarations are unknown, including destructured bindings.
Shadowed module aliases and indirect targets are rejected. Branch and block scopes
are isolated so local declarations cannot disguise later shared-state reads. A
global or imported value named `true` or `false` is a shared value, not a literal
exemption.

The diagnostic prefix is `MB-EFFECT-001`. Ceiling violations identify the effect,
permitted row, annotated function, contributing primitive location, and a call
path. Effect-ceiling witnesses use the fewest call edges from the annotated
function to a contributing primitive. Equal-length witnesses retain the first
discovered path, making selection deterministic for the same source. Recursive
propagation also updates witnesses when a shorter path becomes available.
Unknown-operation diagnostics identify the operation and a shortest call path
from the contract root whose discovery reached it. This includes unsupported
types, global reads, indirect calls, and native/runtime bodies. Earlier contract
roots retain priority over later roots; the checker does not search all roots
for a globally shortest error. The source location remains the contributing
operation, including when it resides in an imported module. Unknown behavior
still aborts checking and cannot produce a successful behavior report.

## Inspecting summaries

```sh
toolchain/mayc/mayc_new --explain-behavior examples/behavior.may
```

`--explain-behavior` checks the program and emits one JSON object to stdout after
successful type and name checking. It does not execute the program or write an
executable. On failure it emits diagnostics to stderr and no successful report.
It can be combined with `--diagnostics json`, `--raw`, and target/runtime options;
it cannot be combined with source dumps.

The version-1 report has `schema_version: 1`, `scope: "scalar_effects_v1"`,
`analysis_roots: "explicit_contracts"`, and a `functions` array in declaration
order. Each function contains its name, source file/range, normalized
`declared_effects` (null for inferred helpers), sorted `inferred_effects`, and a
`classification` of `proven` within this limited analysis scope. Pure and empty-row
contracts both report an empty declared array. Source ranges use one-based lines
and UTF-8 byte columns, as in compiler diagnostics.

Only functions reachable from explicit contracts have summaries. An omitted
function has unknown behavior, not an empty row. With no contracts the function
array is empty. The report is reproducible for equal source/path/toolchain input;
it is inspection metadata, not a signed manifest or independently verified proof.

During compilation, retained functions also carry a `behaviorSummary` in the
emission context. This internal version-1 snapshot contains the scope,
classification, display name, resolved source symbol, declared ceiling (null for
inferred helpers), and inferred row. Rows are copied so frontend mutation or
release cannot change the emission snapshot. Functions without an analyzed
summary have no snapshot; missing metadata never means pure. Unreachable functions
are not emitted even if they have an explicit contract.

This retention preserves analysis data across the frontend/IR boundary. It does
not serialize metadata into the executable, seal a separately compiled public
interface, or verify the backend's refinement of source behavior.

## Exact guarantee boundary

An accepted contract establishes that explicit supported operations in the
checked scalar call graph fit their effect ceilings. Unknown behavior cannot
satisfy a ceiling. This relies on the existing strict checker, module resolver,
compiler, scalar runtime operations, and runtime type enforcement. It is not a
mechanically proved soundness theorem or containment for hostile native code.

Purity does not establish termination, totality, resource bounds, failure freedom,
or constant-time execution. Division may fail; recursion may exhaust the stack;
runtime bookkeeping may allocate, including boxing Float values and constants.
Floating-point contracts do not establish cross-target bitwise reproducibility.
Runtime diagnostics, crash handling, debug traces, and host failures are outside
this effect model. The compiler does not
establish protected information flow, capability possession, quotas, or a verified
execution profile. Effect declarations describe ceilings; they are not capability
grants. Primitive availability and behavior still depend on the selected runtime.

The Rust source bootstrap builds the compiler, but its own source-language
frontend does not accept these contracts. Use `toolchain/mayc/mayc_new` for
annotated programs. No backend or runtime representation changes are required.

## Validation

```sh
sh toolchain/rust/build.sh
python3 toolchain/mayc/tests/behavior.py
python3 toolchain/mayc/tests/effect_rows.py
python3 toolchain/mayc/tests/behavior_reports.py
python3 toolchain/mayc/tests/behavior_scalars.py
python3 toolchain/mayc/tests/behavior_control_flow.py
python3 toolchain/mayc/tests/behavior_ir.py
python3 toolchain/mayc/tests/verify.py --compiler toolchain/mayc/build/bin/mayc_new --features-only
python3 toolchain/rust/test.py
```

The six behavior suites run through the standard native verification harness.
They execute recursive/imported functions, check fixed-point propagation and
ceilings, reject global/alias/scope bypasses and unknown operations, inspect
normalized reports, compare generated call graphs with an independent
reachability oracle, and verify that failed checking produces no successful
report or executable. Bootstrap validation checks stage-2/stage-3 binary convergence.
The scalar and control-flow suites also accept `--llvm` to execute their positive
cases through the direct LLVM backend when Clang is installed.

The complete design backlog and continuation checkpoints are tracked in
[the implementation ledger](BEHAVIOR_PROGRESS.md).
The [scalar core model](BEHAVIOR_CORE.md) specifies the observation boundary,
fixed-point rules, proof obligations, and prerequisites for behavioral callables.

## Next implementation milestones

1. Inventory remaining primitive effects and add explicit rules, with tests that
   unknown calls never silently receive empty rows. Add `guarded`, `assumed`, and
   `unknown` guarantee results when corresponding enforcement paths exist.
2. Broaden the supported AST/type fragment with defined allocation, mutation,
   failure, and aliasing semantics. Preserve minimal effect-ceiling witness
   paths and shortest unknown-operation discovery paths.
3. Carry effects in callback/function types and check behavioral subtyping at
   assignments and calls. Add regressions for callback laundering and generic
   substitution before enabling those forms.
4. Define stable separately compiled contracts, build identities, canonical
   digests, and public contract diffs. Inspection metadata alone is not proof.
5. Introduce explicit capability APIs and attenuation, then isolated native
   boundaries and adversarial OS containment tests. Ambient APIs remain outside
   any claimed verified profile until that migration is complete.
6. Add independently specified ownership/state, information-flow, typed-failure,
   resource-metering, structured-task, transaction, and replay rules. Each needs
   negative tests and an explicit enforcement/assumption model.

The design's unresolved decisions remain open. This increment does not choose
an application security profile, information-flow lattice, ownership model,
quota accounting domain, or distributed transaction semantics.
