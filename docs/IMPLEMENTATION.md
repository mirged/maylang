# Dependable Maylang implementation

This work follows the language assessment: make runtime behavior dependable,
complete typed results and enum matching, clarify numeric contracts, unify
installation and project builds, and improve compiler feedback. Changes are
delivered in focused commits with regressions and source-bootstrap verification.

## Acceptance criteria

- Reject stale/interior GC pointer candidates, preserve live graphs across
  repeated collections, and exercise a sustained real application workload.
- Infer typed result constructors and check `?` propagation against the
  enclosing function; support typed enum payload patterns and exhaustiveness.
- Give ordinary I/O and result helpers useful static contracts; explicitly
  document the representation and remaining fixed-width restrictions.
- Produce an installable toolchain bundle and verify it outside the checkout.
- Make package-manager compiler selection explicit, apply target/runtime
  configuration, and invalidate builds when inputs or configuration change.
- Offer structured diagnostics and useful error recovery with regression tests.
- Keep one maintained CLI application in installation/workflow checks.

## Validation

Run focused tests for each change, then the source-only bootstrap, successive
self-hosting generations, compiler verification, compliance and LSP suites.
Record actual results and remaining limits here as the work progresses.

Existing uncommitted guide/reference changes belong to the user and are excluded
from this implementation's commits.
