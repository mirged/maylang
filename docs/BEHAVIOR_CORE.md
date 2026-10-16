# Scalar behavior core and callable extension obligations

This document specifies the current scalar effect model and the obligations for
extending it to callable values. It supports sections 4, 5, 16 and 22 of the
[unified behavior design](../MAYLANG_UNIFIED_BEHAVIOR_DESIGN.md). The executable
implementation is in `toolchain/mayc/src/behavior.may`; supported syntax is listed
in [BEHAVIOR.md](BEHAVIOR.md). The callable extension below is a specification
target, not accepted syntax or an implemented guarantee. No mechanized soundness
proof is claimed.

## Scalar language and observations

Declared value types are `Int`, `Bool` and `Float`. Discarded primitive results
can include `Nil`, for example the result of `print`; Nil storage and literals
are not admitted. Arithmetic follows the selected
runtime's existing [numeric semantics](../reference/LANGUAGE.md), rather than
unbounded mathematical integers or exact real arithmetic. Numeric primitives
may fault. The full runtime uses bounded tagged integers and boxed binary64
values; raw execution has different representation assumptions. These differences
cannot be erased by an effect annotation.

The core includes scalar literals and local reads; unary negation and Boolean
negation; arithmetic `+`, `-`, `*`, `/`, `%`; comparisons; short-circuit Boolean
operators; typed bindings; local assignment; blocks; conditionals; while loops;
break/continue; explicit returns; and resolved direct calls. Syntactic sugar is
admitted only when its parsed AST consists of supported operations. Exponentiation,
ranges, collection expressions, indirect calls and closures are not in this core.
An empty control-flow body is a block; an empty map in a value position remains
a collection expression.

The effect universe is `U = {output, clock}`. Covered source observations are:

| Operation | Observation | Effect |
| --- | --- | --- |
| `print(v...)` | An output operation on its evaluated arguments | `output` |
| `time()` | A host time observation returning Int | `clock` |
| `clock()` | A host clock observation returning Float | `clock` |
| `pi()`, `e()` | Fixed mathematical constants returning Float | none |

This observation model does not count runtime allocation, arithmetic failure,
GC, stack exhaustion, debug/crash output, or host failures as members of `U`.
Those exclusions are limits of this core, not evidence that such behavior is
absent. The future resource/failure/flow contracts must account for their own
channels explicitly. Constant construction and scalar arithmetic can allocate
runtime boxes without acquiring an `alloc` guarantee.

## Environments and execution

A declaration environment `Delta` maps resolved source function identities to
their parameters, scalar return type, body, and optional effect ceiling. Identity
includes module resolution; a display name alone does not identify an imported
function. Primitive identities are distinct from source declarations and globals
that shadow their spellings.

A typing environment `Gamma` maps local binding identities to `(type, mutable)`.
A runtime frame `rho` maps those bindings to scalar values. Calls evaluate
arguments in source order, create a fresh parameter frame, execute the callee,
and return a scalar result. Parameters are mutable by-value bindings. Reassigning
a parameter changes its frame, not the caller's binding. Float boxes represent
immutable scalar values at this abstraction boundary; exposing their storage
through a pointer is outside the core.

Execution configurations contain a current term, a stack of frames/control
contexts, and a covered-observation trace. Each step either updates private
state, emits a primitive observation, transfers control, returns, or faults.
An infinite execution is described by its finite prefixes. No termination
assumption is needed to discuss the effects of a prefix.

Binding initializers are evaluated before the new binding enters scope. Blocks,
branches and loop bodies introduce scopes. Assignment requires an existing mutable
binding in the current function's environments; a matching global name is not a
local assignment target. Break/continue select an enclosing loop in the same
function. A caller's loop context cannot authorize control transfer in a callee.

Conditional and short-circuit execution chooses the usual runtime path. While
execution reevaluates its condition before each iteration. Static effect checking
does not prune untaken branches, false loops, or statements after control transfer.

## Static summaries and their fixed point

For each checked function `f`, syntax traversal produces:

- `D(f)`, the set of directly covered primitive effects.
- `C(f)`, the resolved source-function call edges, including argument expressions.
- A rejection for every unsupported operation, unknown target, invalid scalar
  signature, forbidden global/captured access or invalid local assignment.

Literals and permitted local reads contribute no effects or edges. Composite
terms union their children's contributions. Binding/assignment contributes the
initializer/right-hand side. A conditional unions its condition and both
branches. A while loop unions its condition and entire body. A direct source
call adds its target edge and all argument contributions. A primitive call adds
the primitive's explicit rule and all argument contributions. An empty primitive
row is an audited rule; a missing rule is unknown.

Reachable source functions are discovered from explicit contract roots. Define:

```text
E0(f)    = D(f)
En+1(f)  = D(f) union Union { En(g) | g in C(f) }
E(f)     = least fixed point of this system
```

This fixed point exists and the set computation terminates for a finite graph
over finite `U`. A recursive edge does not stand for an empty callee summary.
Unknown behavior is a rejected analysis outcome, not the empty set and not a
member that a wider finite row can authorize.

For each annotated function `f` with ceiling `A(f)`, require `E(f) subset A(f)`.
Every discovered annotated callee must also satisfy its own ceiling. A wider
caller cannot excuse a callee violation. This implementation uses inferred
callee effects at callers; separately compiled sealed interfaces are not yet
provided.

Value typing, arity, return-path checks and name resolution must also succeed
before a report or executable is produced. The effect pass currently runs before
strict value checking. Its temporary summaries are not independently successful
verification results when a later pass fails.

## Required refinement property and proof obligations

The intended effect-refinement property is:

```text
If f is accepted, linkage and runtime satisfy the stated trusted assumptions,
and execution from well-typed scalar arguments has finite covered trace t,
then effects(t) subset E(f).
If f has ceiling A(f), additionally effects(t) subset A(f).
```

This includes prefixes ending in a fault and prefixes of divergent executions.
It does not establish totality, failure freedom, bounded memory/work, information
flow, capability possession, sandboxing, or deterministic scheduling.

A proof must establish local-step preservation of the observation accounting,
frame isolation, correct resolution of calls/shadows, and closure of `E` under
every call edge. It must then relate actual lowering, optimization, runtime
dispatch and code emission to the core steps. The existing tests provide
regression evidence for parts of these obligations; they do not discharge this
proof. Backend-only helper calls must remain within the trusted primitive rule's
stated assumptions or become explicit trust transitions.

Effect-ceiling witnesses must be real call paths to a contributing primitive,
with the fewest call edges. Unknown-operation witnesses are shortest discovery
paths from the first contract root reaching the rejected body; root priority
remains declaration order. These are diagnostic selection rules, not additional
semantic permissions.

## Callable types: extension requirements

The next core adds an effect dimension to callable types:

```text
Fn(T1, ..., Tn) -> R ! E
```

`E` is a closed ceiling, an explicitly quantified effect expression, or unknown.
An omitted callable row must remain unknown; it must never default to pure.
For a call through a value, the caller accounts for the value's row as well as
effects of evaluating the callee and arguments. An unknown row cannot satisfy
a finite checked ceiling.

For actual callable `A` to substitute for expected callable `B`, require equal
arity, contravariant parameter compatibility, covariant result compatibility,
and `effects(A) subset effects(B)`. This applies recursively to callable-valued
parameters/results. Effect polymorphism requires explicit variables, substitution
and constraint solving; replacing an unresolved variable with an empty row is
invalid. Recursive constraints require a fixed-point or equivalent sound solver.

Before enabling callable values, the implementation must:

1. Define unambiguous parsing/binding for callable-row syntax and declaration
   ceilings, including callable return types and nested function types.
2. Preserve rows in type construction, equality, subtyping, joins, generic
   unification/substitution, local bindings, arguments and results. Extend every
   type-copy path; a value signature without its row is incomplete.
3. Infer/check source function values against their bodies. An unannotated or
   foreign function's value signature is not evidence of an empty effect row.
4. Enforce expected callable rows at every assignment, argument and return
   boundary, even when the caller itself has no explicit behavior annotation.
5. Reject legacy-mode erasure of behavioral callable annotations and prevent
   `Any`, containers, closures, reflection or native boundaries from laundering
   a callable's unknown behavior into a finite row.
6. Keep resolved effect metadata through IR construction and emission. The
   current emitter snapshots omit behavior summaries; they must not serve as
   a claimed behavior-preserving link interface until that gap is addressed.
7. Provide positive subtype cases and negative laundering cases for direct,
   imported, recursive, generic, higher-order, captured and foreign callables.
   Failed checking must produce neither successful metadata nor a new binary.

Capabilities, resource bounds, information-flow/state/failure contracts and the
other dimensions of the ultimate behavior type must later extend this ordering
with their own semantics. A subset check on `U` alone does not prove behavioral
subtyping for those dimensions.
