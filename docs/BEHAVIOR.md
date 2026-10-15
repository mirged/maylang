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

Parameters, returns, and local bindings must explicitly use `Int` or `Bool`.
The checker accepts integer/boolean literals, parameter/local reads, unary and
binary expressions, logical expressions, immutable local bindings, blocks,
conditionals, returns, and direct calls to supported source functions and the
listed primitives. `clock` returns a temporary `Float`, which may be used in
comparisons or printed; `Float` annotations and literals are not yet supported
in this fragment. `time` returns `Int`.

Global reads, mutation, collections, strings, callbacks, closures, generic
functions, loops, FFI, and other unsupported AST forms are rejected as unknown.
Declaring all currently known effects cannot authorize unknown operations.
Contracts require strict checking; `--legacy` cannot disable verification.
Other proposed behavior clauses and syntax are not implemented. Programs without
contracts retain their current behavior.

## Composition and inference

The checker discovers every annotated function and its reachable source helpers.
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
Unknown-operation diagnostics identify the operation and discovery traversal
path; those paths do not yet have the same minimality guarantee.

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

## Exact guarantee boundary

An accepted contract establishes that explicit supported operations in the
checked scalar call graph fit their effect ceilings. Unknown behavior cannot
satisfy a ceiling. This relies on the existing strict checker, module resolver,
compiler, scalar runtime operations, and runtime type enforcement. It is not a
mechanically proved soundness theorem or containment for hostile native code.

Purity does not establish termination, totality, resource bounds, failure freedom,
or constant-time execution. Division may fail; recursion may exhaust the stack;
runtime bookkeeping may allocate. Runtime diagnostics, crash handling, debug
traces, and host failures are outside this effect model. The compiler does not
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
python3 toolchain/mayc/tests/verify.py --compiler toolchain/mayc/build/bin/mayc_new --features-only
python3 toolchain/rust/test.py
```

The three behavior suites run through the standard native verification harness.
They execute recursive/imported functions, check fixed-point propagation and
ceilings, reject global/alias/scope bypasses and unknown operations, inspect
normalized reports, compare generated call graphs with an independent
reachability oracle, and verify that failed checking produces no successful
report or executable. Bootstrap validation checks stage-2/stage-3 binary convergence.

## Next implementation milestones

1. Inventory remaining primitive effects and add explicit rules, with tests that
   unknown calls never silently receive empty rows. Add `guarded`, `assumed`, and
   `unknown` guarantee results when corresponding enforcement paths exist.
2. Broaden the supported AST/type fragment with defined allocation, mutation,
   failure, and aliasing semantics. Preserve minimal effect-ceiling witness
   paths and extend minimal witnesses to unknown-operation diagnostics.
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
