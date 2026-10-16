# Unified behavior implementation ledger

The target is the complete [unified behavior design](../MAYLANG_UNIFIED_BEHAVIOR_DESIGN.md).
This ledger distinguishes working implementation from proposed guarantees. No
row below implies a verified execution profile or independently checked proof.
The current supported language is documented in [BEHAVIOR.md](BEHAVIOR.md).

## Checkpoints and continuation

Commit and push focused, tested increments regularly. Merge their PRs after CI
passes. Preserve unrelated launch, licensing, distribution, and installer edits
already present in the working tree. Rebuild the cached compiler after compiler
changes with `sh toolchain/rust/build.sh` before testing it.

Completed checkpoints:

- `c4e3233`, PR #67 (merged): shortest unknown-behavior diagnostic paths.
- `fc66f48`, PR #68 (merged): Float contracts and explicit pure pi/e primitive rules;
  local verification passed 82 checks and 55 native/LLVM scalar cases, including
  stage-2/stage-3 compiler convergence.

Active increment: allow private scalar mutation and `while` loops while retaining
fail-closed checks for shared state, collections, captures, and indirect calls.
Analyze loop conditions and all body statements, including unreachable code;
preserve scopes, effect propagation, and diagnostic paths. Do not infer termination
or a resource bound from loop acceptance. Add native/LLVM execution, negative
scope/shadowing cases, and report assertions before merging.

## Full design coverage

| Design area | Current evidence | Required implementation and acceptance evidence |
| --- | --- | --- |
| 3–5: behavior types, syntax, algebra | Scalar effect ceilings, recursive fixed points, strict fail-closed fragment | Canonical behavior IR, all clause syntax, composition rules and formally specified safe fragment |
| 4.2, 4.4: polymorphism and subtyping | Callback and generic contracts rejected | Effect-bearing callable types, substitution, recursive constraints, callback laundering and behavioral subtyping tests |
| 4.3: public sealing | Explicit per-function ceilings | Stable public interfaces and separate compilation; implementation changes cannot broaden sealed contracts |
| 6: authority and dependency security | Ambient/foreign operations remain unknown under contracts | Explicit scoped capabilities, attenuation, revocation, delegation, dependency ceilings and actual native sandbox containment |
| 7: information flow | No confidentiality/integrity guarantees | Independent label lattices, explicit and implicit flow, authorized declassification, sink construction, errors/logging/serialization tests |
| 8: ownership and protocol state | Scalar values only; existing GC is not an ownership proof | Ownership/borrowing model, alias/lifetime rules, typestate transitions, invariant preservation and terminal-state checks |
| 9: failures and recovery | Existing runtime failures are outside effect rows | Typed exposed failure sets, propagation/handling, cancellation semantics and recovery-policy validation |
| 10: transactions | No transactional guarantee | Defined local atomicity domain, rollback/commit, irreversible-effect barriers and explicit external compensation protocols |
| 11: resources and deadlines | No hard behavior quotas | Specified charging model, enforced meters/OS limits, quota domains, deadlines, exhaustion and adversarial tests |
| 12: structured concurrency | Task operations remain unknown | Child-task ownership, cancellation/join, sharing rules, lock order and stated scheduling assumptions |
| 13: determinism and replay | No deterministic/replay contract | Accounted nondeterministic boundaries, build identity, protected traces, divergence checks and failure-to-test conversion |
| 14: distributed protocols | No delivery or distributed consistency guarantee | Delivery/idempotency/order contracts, explicit uncertainty, failure injection and protocol-state validation |
| 15: supply/build/platform contracts | Existing toolchain metadata is not a behavior lockfile | Canonical contract digests, transitive authority diffs, build identities, provenance and target enforcement obligations |
| 16: unified enforcement architecture | Frontend effect pass and inspection reports | Behavior IR preservation through lowering/optimization/linking, runtime guards, capability broker and isolation supervisor |
| 17: standard library | print/time/clock/pi/e rules; primitive audit in BEHAVIOR.md | Audited APIs, capability-based ambient facilities, precise callback/allocation/mutation/failure semantics |
| 18: developer experience | JSON summaries and minimal diagnostic paths | IDE behavior hover/tracing, authority/resource explanations, contract diffs and behavioral version compatibility |
| 19: reference applications | Small scalar behavior example | Secure isolated decoder, payment uncertainty, deterministic simulation and quota-limited API with end-to-end tests |
| 20: trust model | Supported fragment and exclusions documented | Auditable TCB, versioned assumptions, profile enforcement and policy for debug/replay/crash output channels |
| 21: normative laws | Partial effect-ceiling law within the scalar fragment | Independent conformance evidence for all fifteen laws; never infer security from annotations alone |
| 22: conformance | Negative suites, graph oracles and compiler convergence | Instrumented differential/property tests, adversarial OS tests, replay corruption tests and mechanized core proofs |
| 23: performance/usability | No behavior-specific overhead claim | Reproducible workloads, incremental summaries, bounded diagnostics and measured enforcement overhead |
| 24: unresolved decisions | Remain explicit in the design | Record decisions with semantics, alternatives, evidence and limits before relying on them |

## Dependency order

1. Complete the scalar fragment's control flow and primitive audit; keep tests
   and supported-scope documentation synchronized.
2. Specify a behavior IR and effect-bearing function types, then implement
   callback composition/subtyping and public interface sealing.
3. Build explicit authority APIs and native isolation. Introduce guarded results
   only with actual enforcement and adversarial boundary tests.
4. Develop ownership/state, information-flow and typed-failure rules against the
   safe core. Extend library contracts without permitting dynamic escape hatches.
5. Add resource domains and structured tasks; compose transactions, determinism,
   replay and distributed protocols on their actual enforcement boundaries.
6. Finish build/link/platform contracts, IDE explanations, reference applications,
   conformance proofs and measured performance across supported targets.

This order does not defer any design area out of scope. Changes to the order
must preserve prerequisite semantics and the design's honest guarantee levels.
