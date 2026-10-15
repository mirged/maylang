# Unified behavior implementation

The Unified Behavior System design is a long-term language and platform proposal.
The active self-hosted compiler now implements one conservative starting point:
explicit `! pure` contracts for scalar functions. This is not an implementation
of the design's verified execution profile.

```may
fun double(x: Int) -> Int ! pure {
    let result: Int = x * 2;
    return result;
}
print(double(21));
```

## Supported contract

Place `! pure` after an explicit return type. Parameters, returns, and local
bindings must explicitly use `Int` or `Bool`. The checker accepts scalar
literals, parameter/local reads, unary and binary expressions, logical
expressions, immutable local bindings, blocks, conditionals, returns, and direct
calls to other explicitly pure functions. Forward calls, recursion, and mutual
recursion are supported: every annotated body is checked, including unused
functions and syntactically unreachable branches.

Calls resolve through the existing module/import visibility rules. A function
without an explicit contract is unknown, even if its body looks pure. Global
value bindings that shadow function declarations remain unknown; a function
annotation cannot certify a separately assigned callback.

Global reads, mutation, collections, strings, callbacks, closures, generic
functions, loops, FFI, runtime primitives, and other unsupported AST forms are
rejected. Pure contracts require strict checking; `--legacy` cannot disable
their verification. Other proposed contract syntax is not implemented. Existing
unannotated programs retain their current behavior.

The diagnostic prefix is `MB-EFFECT-001`. Diagnostics identify the offending
operation and source location. Full transitive explanation paths and structured
behavior-specific diagnostic fields are future work.

## Exact guarantee boundary

The check establishes absence of explicit external operations and shared-state
access in this closed scalar fragment and its explicitly contracted direct
callees. It relies on the existing strict checker, module resolver, native
compiler, scalar runtime operations, and runtime type enforcement. It is not a
mechanically proved soundness theorem or containment for hostile native code.

Purity does not establish termination, totality, resource bounds, failure freedom,
or constant-time execution. Division may fail; recursion may exhaust the stack;
runtime bookkeeping may allocate. Runtime diagnostics, crash handling, debug
traces, and host failure behavior are not protected information-flow channels.
The compiler does not emit a `verified` profile, signed proof, or quota guarantee.

The Rust source bootstrap builds the compiler, but its own source-language
frontend does not accept `! pure`. Use `toolchain/mayc/mayc_new` for annotated
programs. No backend or runtime representation changes are required.

## Validation

```sh
sh toolchain/rust/build.sh
python3 toolchain/mayc/tests/behavior.py
python3 toolchain/mayc/tests/strict_types.py
python3 toolchain/rust/test.py
```

The behavior suite runs through the standard native verification harness. It
executes recursive and imported pure functions and rejects direct/transitive
I/O, raw syscalls, hidden branch effects, global access, mutation, unknown calls,
callback types, shadowed functions, unsupported contracts, and legacy bypasses.

## Next implementation milestones

1. Define normalized effect rows and guarantee classifications (`proven`,
   `guarded`, `assumed`, `unknown`), with unknown never satisfying a ceiling.
   Inventory primitive effects and test that every primitive is classified.
2. Infer conservative direct-call summaries to a fixed point, retaining minimal
   explanation paths. Compare inferred effects with explicit ceilings. Preserve
   unknown effects for unresolved calls and unsupported forms.
3. Carry effects in callback/function types and check behavioral subtyping at
   assignments and calls. Add negative tests for callback laundering, generic
   substitution, and cross-module dispatch before broadening this fragment.
4. Emit versioned, canonical behavior manifests with compiler/build identity,
   trust boundaries, and public contract diffs. Metadata alone is not proof.
5. Introduce explicit capability APIs and attenuation, then isolated native
   boundaries and adversarial OS containment tests. Ambient APIs remain outside
   any claimed verified profile until that migration is complete.
6. Add independently specified ownership/state, information-flow, typed-failure,
   resource-metering, structured-task, transaction, and replay rules. Each
   milestone needs negative tests and an explicit enforcement/assumption model.

The design's unresolved decisions remain open. This increment does not choose
an application security profile, information-flow lattice, ownership model,
quota accounting domain, or distributed transaction semantics.
