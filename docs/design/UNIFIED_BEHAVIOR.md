# MAYLANG: THE BEHAVIORAL PROGRAMMING LANGUAGE
## Unified Behavior System — Ultimate Language & Platform Design

**Status:** Vision specification / proposed language design  
**Scope:** Language, type system, compiler, runtime, operating-system boundary, package ecosystem, debugging, and deployment  
**Working name:** MayBehavior (the Unified Behavior System, **UBS**)  
**Design principle:** *A program should express not just what it computes, but what it may do, what it must preserve, and what the platform can guarantee about its execution.*

---

## 1. Executive Summary

Traditional programming-language types principally describe values and callable signatures. But the failures that cost engineering teams the most often concern behavior not represented by a function's type: secret exfiltration, unsafe dependencies, data races, state corruption, unrecoverable partial operations, resource exhaustion, nondeterministic failures, incompatible platform assumptions, and unrepeatable incidents.

**Maylang's ultimate goal is to make behavior a first-class, composable, enforceable part of the program.** It unifies effect systems, object capabilities, information-flow control, ownership and typestate, structured concurrency, transactional state, resource accounting, deterministic execution, replay, and package contracts under **one model** rather than treating them as unrelated libraries, analyzers, or deployment add-ons.

The system is not designed to make every possible program bug impossible. The stronger and more useful promise is narrower and testable:

> **Within an explicitly declared trust boundary, a verified Maylang component cannot perform an operation outside its granted authority, exceed a hard-enforced resource quota, disclose protected data through a forbidden observed channel, or invalidate a statically proven state protocol without the violation being rejected or contained.**

Any guarantee that depends on the environment, remote systems, wall-clock scheduling, or explicitly unverified native code is labeled accordingly. The language refuses to turn wishes into proofs.

A complete program is therefore described by two interlocking artifacts:

1. **Value interface:** the values a component accepts and returns.
2. **Behavior interface:** the effects it may cause; the capabilities it must receive; the information it can reveal; the state transitions it performs; the failures it exposes; and the resource, isolation, concurrency, and determinism contracts it offers.

The compiler verifies what is provable. The runtime enforces what must be checked dynamically. The sandbox isolates what cannot safely run in-process. The build system records the contract and its provenance. The debugger can replay behavior whose sources of nondeterminism were recorded.

---

## 2. Problem Statement: The Missing Half of a Program's Type

Consider two functions with the same conventional signature:

```may
fun transform(data: Bytes) -> Bytes
```

One computes a hash. The other uploads the input to a remote server, allocates unbounded memory, spawns threads, and changes files. A conventional signature does not distinguish them.

This gap produces recurring classes of failure:

| Failure class | Missing contract |
| --- | --- |
| Supply-chain compromise | Which resources a dependency may access |
| Secret exfiltration | Which information may reach which destination |
| Injection vulnerabilities | Whether data has passed a context-specific safe construction step |
| Memory misuse | Who owns storage, how long views are valid, who may mutate |
| Resource leaks / exhaustion | What a task must release and what it may consume |
| Data races and deadlocks | Which states tasks share and which synchronization order applies |
| Partial updates | What must be committed atomically or compensated |
| Unexpected exceptions | Which failures may propagate and how they are handled |
| Hung requests | What may block, for how long, and what cancellation guarantees exist |
| Nonreproducible incidents | Which nondeterministic inputs and scheduling decisions occurred |
| Platform surprises | Which host facilities a component assumes |
| Fragile dependency upgrades | Whether an update expands effects or weakens guarantees |
| Distributed inconsistency | Which messages were delivered, duplicated, ordered, and acknowledged |
| Invisible operational regressions | Whether a version changes its observable contract |

**Unifying thesis:** Many serious defects occur where *actual behavior* exceeds *assumed behavior*. Maylang makes the assumption explicit and binds the implementation to it.

---

## 3. Foundational Concepts

### 3.1 Behavior is a type dimension

A function type is conceptually:

```text
(Inputs) -> Output ! Behavior
```

Behavior is a normalized set of constraints, not a documentation comment. It includes:

- **Authority:** accessible resources and permitted operations.
- **Effects:** possible reads, writes, I/O, allocation, spawning, blocking, and external calls.
- **Information flow:** confidentiality and integrity labels and permitted declassification.
- **State:** legal transitions, ownership, and invariants.
- **Failure:** explicit failure variants and cancellation behavior.
- **Resources:** memory, CPU, I/O, output size, tasks, and other measurable budgets.
- **Concurrency:** isolation, sharing, synchronization, and task lifetimes.
- **Determinism:** whether repeated execution under equal inputs produces equal observable traces.
- **Transactions:** which mutations commit together, and what happens on failure.
- **Environment:** platform capabilities and assumptions that must be satisfied before running.

Not every field has to be written. Inference fills what can be established; contracts constrain or document the inferred result. An omitted field is **not** an invisible grant of unlimited authority.

### 3.2 Three guarantee levels

Every contract clause carries one of three enforcement classifications:

| Level | Meaning | Example |
| --- | --- | --- |
| `proven` | Checked statically against a sound language subset | No filesystem effect can be reached from a pure function |
| `guarded` | Enforced by monitored runtime or OS boundary | Maximum heap bytes; network destination allowlist |
| `assumed` | Depends on an external actor or environment; not a local proof | Remote payment provider honors idempotency keys |

A fourth result, **`unknown`**, is not a successful guarantee. It requires contract relaxation, a runtime guard, a proof witness, or isolation.

### 3.3 Deny ambient authority

Components cannot silently acquire privileges from process globals. Files, networks, clocks, randomness, process execution, devices, secrets, and unsafe native interfaces are accessed through explicit **capabilities**. Capabilities may be attenuated (made more restrictive) when passed to a dependency, but cannot be amplified by the recipient.

### 3.4 No invisible escape hatches

Low-level operations and foreign code remain possible; Maylang is a systems language. But unsafe memory, raw syscalls, FFI, and JIT/native extensions are explicit **trust transitions** with auditable blast radii. A raw syscall in an unrestricted process is not secure just because a type annotation says otherwise. Security contracts require the OS or an equivalent isolation boundary.

### 3.5 Safe defaults; deliberate opt-outs

Pure computation requires little ceremony. Operations that cross trust boundaries require explicit capability grants. Stronger guarantees remain opt-in where their runtime cost is material, but contract checking never silently drops to best-effort mode.

---

## 4. Language Surface: One Behavior Declaration

### 4.1 Canonical syntax

The following is **proposed syntax**, not a description of an existing implementation.

```may
fun settle(order: Order, wallet: &mut Wallet) -> Result<Receipt, PaymentError>
    behavior {
        requires: [network(payments_api), clock(monotonic)];
        effects: [network.send(payments_api), wallet.write];
        disclose: [order.payment_token -> payments_api];
        state: wallet[Open] -> wallet[Open];
        fails: [Declined, Timeout, Cancelled];
        resources: { heap <= 32.MiB, tasks <= 2, cpu <= 50.ms };
        deadline: 2.seconds;
        concurrency: isolated(wallet);
        replay: recorded;
    }
{
    let response = payments_api.charge(order.payment_token)?;
    wallet.apply(response)?;
    return Ok(Receipt(response.id));
}
```

The syntax is a readable projection of a canonical behavior type. Contracts may be shorter, for example:

```may
fun double(x: Int) -> Int ! pure {
    return x * 2;
}

fun load(path: Path, fs: ReadFs) -> Result<Bytes, IoError>
    ! { read(fs), fail(IoError) }
{
    return fs.read(path);
}
```

### 4.2 Type and effect-polymorphic functions

```may
fun map<T, U, effect E>(items: Slice<T>, f: fn(T) -> U ! E)
    -> List<U> ! { E, alloc }
{
    // The caller pays for f's effects; map doesn't hide them.
}
```

A function taking a callback must account for that callback's behavior. A nominal `Fn` interface is insufficient if its effects are discarded.

### 4.3 Contract inference and sealing

```may
infer behavior for parse_config;

export fun parse_config(text: Str) -> Config
    ! { alloc <= by_input(4 * text.bytes), fail(ParseError) };
```

`infer` requests discovery and diagnostics; an exported contract is a *ceiling*. A compiler may infer behavior within the declared ceiling but must reject behavior beyond it. Inferred behavior alone is not a stable public API until sealed.

### 4.4 Behavioral subtyping

A function requiring fewer capabilities, causing fewer effects, disclosing less data, failing in fewer permitted ways, and satisfying an equal-or-stronger guarantee can substitute for a less restrictive function. It cannot silently broaden the public contract. Resource bounds use declared ordering; incompatible measures cannot be compared without a known conversion.

---

## 5. Formal Model: The Behavior Algebra

Let the behavioral contract of a function be:

```text
B = (R, E, I, S, F, Q, C, D, T, P)
```

Where:

- `R`: required capabilities (authority).
- `E`: upper bound on permitted externally relevant effects.
- `I`: information-flow constraints.
- `S`: state preconditions, postconditions, ownership and invariants.
- `F`: possible failure outcomes and cancellation semantics.
- `Q`: resource budgets, with a model of what is measured.
- `C`: concurrency and synchronization constraints.
- `D`: determinism and replay conditions.
- `T`: transaction/commit semantics.
- `P`: platform assumptions.

### 5.1 Composition

For sequential `a; b`:

- `R(a; b)` is the combined required authority, with attenuation constraints preserved.
- `E(a; b)` is the union of possible effects; conditional branches use a safe upper bound.
- `I(a; b)` composes source-to-sink flows transitively, including implicit/control-flow dependencies under the selected flow policy.
- `S(a; b)` is valid only when `a`'s post-state satisfies `b`'s pre-state.
- `F(a; b)` includes `a`'s failures and `b`'s failures reachable after `a` succeeds, adjusted for handlers.
- `Q(a; b)` is a safe bound under the declared resource model: **peak** memory usually combines live sets, not blindly sums total allocations; CPU work can be additive while deadlines may be limited by the critical path.
- `C`, `D`, `T`, and `P` compose by their own rules, not by naïve set union.

Parallel `a || b` uses a different rule: simultaneous memory and task counts may add; elapsed time is governed by scheduling and critical paths; conflicting state effects are disallowed unless synchronized; nondeterministic interleavings are recorded or excluded when deterministic replay is required.

### 5.2 Soundness obligations

A valid static proof must define the exact fragment of Maylang and its operational semantics. Recursive effects require fixed-point analysis. Dynamic dispatch requires conservative resolution or guarded dynamic checks. General termination, exact arbitrary runtime, and exact heap peaks cannot be statically decided for unrestricted programs; the language never promises otherwise.

### 5.3 Proof-carrying and monitored contracts

Compiled modules carry machine-readable behavior metadata: inferred effect summaries, public contract digests, verification results, sandbox requirements, resource-meter configuration, and trust transitions. Where static verification cannot finish, the module carries obligations that the runtime must enforce before allowing execution.

---

## 6. Authority and Dependency Security — MayGuard

### 6.1 Explicit capabilities

```may
fun read_profile(fs: ReadFs<"/profiles">, id: UserId) -> Result<Profile, IoError> {
    return fs.read_json(id + ".json");
}
```

The filesystem permission is a capability value; passing a `ReadFs<"/profiles">` does not allow writing, listing `/home`, or escalating to the entire filesystem.

### 6.2 Capability attenuation and revocation

A capability has an issuer, operation set, resource scope, lifetime, delegation policy, and optional revocation token. `cap.narrow(...)` creates a weaker capability. Revocation is observable and causes defined failures; revocation cannot retroactively undo already completed external effects.

### 6.3 Dependency authority manifests

```may
package image_decoder {
    permissions {
        filesystem: none;
        network: none;
        process: none;
        clock: none;
        allocation: <= 64.MiB;
    }
}
```

Dependency permissions are ceilings, not requests the runtime grants automatically. Transitive dependencies cannot receive more authority than their callers delegate. Updating a package with expanded effect requirements is a **contract-breaking change** even when signatures remain identical.

### 6.4 Native isolation boundary

Adversarial binary dependencies run in sandboxed processes or equivalently strong OS-isolated domains with mediated IPC and narrowly granted capabilities. In-process static checking is meaningful only for verified code and trusted primitives. A runtime cannot honestly claim to contain unrestricted arbitrary machine instructions inside the same protection domain.

---

## 7. Information-Flow Safety — MayFlow

### 7.1 Two independent label axes

Every sensitive value may carry:

- A **confidentiality** label: `Public`, `Internal`, `Secret`, or a principal-specific label.
- An **integrity** label: `Untrusted`, `Validated<Schema>`, `Authenticated<Principal>`, etc.

Confidentiality controls where data may flow. Integrity controls what it is safe to use data *for*. They are different problems and must not share a single misleading `Trusted` bit.

```may
let token: Secret<PaymentToken> = secrets.get("payment_token");
let amount: Untrusted<Str> = request.field("amount");

let payment_amount: Validated<Money> = validate_money(amount)?;
```

### 7.2 Noninterference and controlled release

For declared protected channels, publicly observable behavior must not reveal secret data unless explicitly declassified. The strict model includes values, errors, logs, exception details, control-flow outputs, and designated side channels; time/cache/power side channels require an additional constant-time or hardened-execution profile and are **not** covered by ordinary noninterference.

```may
let token: Secret<Str> = secrets.get("token");
console.print(token); // ERROR: Secret -> Public output
```

```may
let digest: Public<Hash> = declassify(hash(token))
    with authority secrets.release_hash
    because "publish stable lookup digest";
```

Declassification requires a separately delegated capability and leaves an auditable record. Hashing a low-entropy secret is not automatically safe; declassification must be a deliberate policy decision.

### 7.3 Injection-resistant sinks

SQL commands, shell arguments, HTML contexts, URLs, filesystem paths, and RPC payloads use **context-specific constructed types**, not generic string sanitization:

```may
let sql: SqlStatement = sql`SELECT id FROM users WHERE email = ${email}`;
db.execute(sql);
```

Interpolation binds a parameter, not executable SQL. Analogous builders enforce safe process argument arrays and scoped path resolution. Domain-specific validators produce proofs only for the exact grammar and normalization rules they verify.

### 7.4 Implicit flow and termination leakage

Flow labels propagate through explicit assignments and control dependencies. A `if secret { public_output = ... }` branch is checked, not overlooked. Perfect prevention of all microarchitectural and termination channels is outside the default policy; stronger hardened profiles define additional restrictions and report their assumptions.

---

## 8. Ownership, Lifetime, and Protocol State — MayState

### 8.1 Ownership and borrowing

Mutable aliases are either exclusive or mediated by synchronized shared state. References cannot outlive owners or region lifetimes. Explicit low-level regions exist for predictable resource use, but their validity is tracked in safe code.

```may
fun append(log: &mut Log, message: Str) ! { write(log) } {
    log.push(message);
}
```

The compiler rejects concurrent mutable borrowers, use-after-release, escaping region views, and invalidated iterator/arena references in verified code. Garbage collection may exist for shared immutable or managed graphs, but memory safety does not depend on a collector being perfect.

### 8.2 Typestate

Resources expose a protocol. Operations move them through statically checked states:

```may
let file: File<Open> = fs.open("report.txt")?;
file.write("ok")?;
let closed: File<Closed> = file.close()?;
closed.write("nope"); // ERROR: Closed has no write operation
```

The type system supports **linear** obligations (must be consumed exactly once), **affine** resources (at most once), and safely shared immutable values. Dropping a linear resource without completing its protocol is an error unless a compiler-verified finalizer or explicit cancellation path exists.

### 8.3 State invariants

```may
invariant Account {
    balance >= 0;
    currency != Empty;
}
```

A proven invariant is maintained at public mutation boundaries. For dynamic state checks, atomic validation occurs before publication, with rollback on failure. Invariant proofs must state whether they assume exclusive access or transactional isolation.

---

## 9. Failure and Recovery — MayFault

### 9.1 Failures are in the behavior type

Errors, cancellation, timeouts, resource exhaustion, permission denial, validation failure, and external unavailability are distinct, typed outcomes. A caller cannot silently ignore a declared failure or treat cancellation as success.

```may
fun fetch(url: Url, net: HttpClient)
    -> Bytes ! { network(net), fails(Timeout | DnsFailure | HttpFailure) }
```

### 9.2 Recovery policies

```may
let bytes = fetch(url, net)
    recover Timeout => cache.last_known(url)
    recover DnsFailure => Err(ServiceUnavailable);
```

Handlers narrow the resulting failure row. A recovery clause may itself fail and its effects must also appear in the resulting behavior.

### 9.3 Cancellation correctness

Cancellation is structured, propagated, and checked at declared safe points. Functions specify whether they are cancellable and what cleanup/finalization they guarantee. Cancellation is not magic: an uninterruptible native syscall or remote operation cannot be assumed rolled back merely because a local task stopped waiting.

---

## 10. Transactions and Consistency — MayAtomic

### 10.1 Local atomic state

```may
atomic(account_a, account_b) {
    account_a.withdraw(100)?;
    account_b.deposit(100)?;
}
```

Either all protected in-memory mutations become visible, or none do. Isolation level and conflict behavior are explicit. A failing transaction restores managed state, releases locks, and reports a typed failure.

### 10.2 External side effects require a protocol

A file rename, email, payment, or remote RPC cannot generally be rolled back by undoing local memory. Maylang distinguishes:

- `atomic local`: one runtime-controlled state domain.
- `atomic durable`: a transactional storage backend with documented commit guarantees.
- `workflow`: multi-party coordination using idempotency, durable logs, compensation, and explicit uncertainty states.

```may
workflow purchase(order: Order)
    guarantees { at_least_once_delivery, idempotent(order.id) }
{
    reserve_inventory(order) compensate release_inventory(order);
    charge_payment(order)   compensate refund_payment(order);
    emit_receipt(order);
}
```

The workflow does **not** pretend a refund is equivalent to a charge never having occurred. Outcomes include `Committed`, `Compensated`, and `NeedsReconciliation`. "Exactly once" is never claimed end to end without documented domain assumptions.

### 10.3 Transaction effect barriers

Irreversible effects cannot appear inside `atomic local`. A compiler error points to the effect and offers a transaction-safe alternative (outbox, deferred commit hook, or durable workflow).

---

## 11. Resource Guarantees — MayBudget

### 11.1 Budget types

```may
fun decode(input: Bytes) -> Image
    behavior {
        resources: {
            heap_peak <= 128.MiB,
            alloc_total <= 256.MiB,
            cpu_work <= 200.million_instructions,
            file_read <= 16.MiB,
            output <= 64.MiB,
            spawned_tasks <= 4
        };
        on_limit: Err(ResourceLimit);
    }
```

Budgets specify **units, accounting domains, and enforcement mechanisms**. Heap requested bytes differ from RSS; CPU instructions differ from elapsed time; network attempted bytes differ from delivered bytes.

### 11.2 Static and dynamic analysis

Bounded loops and sized data structures may admit static upper bounds. Unbounded recursion or arbitrary computations usually do not. Maylang can:

1. Prove a bound from a refinement (e.g., `input.len <= 4096`).
2. Insert metering that prevents further charged operations beyond quota.
3. Require an explicit unbounded or externally controlled capability.

A runtime limit is enforced before a charged operation when feasible; OS memory pressure, kernel work, and hardware faults remain subject to platform-specific semantics.

### 11.3 Deadlines and real-time claims

`deadline: 50.ms` in a general-purpose profile is an enforcement policy for cancellation or containment, **not a mathematical proof of completion within 50 ms**. A hard real-time profile must require bounded operations, certified scheduler assumptions, target hardware, and WCET analysis. These distinct meanings cannot share the same guarantee label.

---

## 12. Structured Concurrency and Deadlock Prevention — MayConcurrent

### 12.1 Task lifetimes

Child tasks belong to a lexical task scope. They must complete or be explicitly cancelled before the parent scope closes; no untracked runaway task exists in verified structured-concurrency code.

```may
scope tasks {
    let a = spawn fetch_catalog();
    let b = spawn fetch_prices();
    return combine(await a?, await b?);
}
```

Spawned tasks inherit **attenuated** capabilities and explicit quota shares, not every permission possessed by their creator.

### 12.2 Race freedom

Shared writable state requires an actor, a transaction, a synchronized region, or a provably disjoint partition. Data-race freedom is a type-level guarantee in the verified model; logical races (correctly synchronized but unwanted ordering) remain possible and require higher-level invariants.

### 12.3 Deadlock analysis

Lock ordering is tracked where resources expose locks; cycles in statically known acquisition graphs are rejected. Dynamic lock acquisition requires a deadlock-checked runtime, timeout policy, or an explicit `deadlock_risk` behavior. No general static analysis can perfectly decide deadlock freedom for arbitrary communicating concurrent programs.

### 12.4 Determinism modes

- `deterministic`: observable results and relevant ordering cannot depend on unconstrained scheduling.
- `recorded`: nondeterministic choices are logged sufficiently for supported replay.
- `nondeterministic`: allowed, with effects and observability still accounted for.

---

## 13. Determinism and Replay — MayReplay

### 13.1 The replay contract

```may
fun simulate(seed: Seed, world: World) -> World
    behavior { deterministic: true; }
```

A deterministic function can read only arguments, immutable constants, deterministic services, and explicit recorded inputs. Wall time, randomness, ambient environment, scheduling races, and network messages are nondeterministic until injected or recorded.

### 13.2 Record/replay boundaries

```may
record session "incident-482" {
    service.handle(request);
}

replay "incident-482.maytrace" {
    service.handle(request);
}
```

The recorder captures declared nondeterministic events, causal ordering, module/build identities, and boundary responses. Replay substitutes logged inputs and checks the resulting trace. Divergence includes precise event/contract diagnostics. A trace is not guaranteed to reproduce failures caused by uninstrumented raw memory corruption or external actors outside the capture boundary.

### 13.3 Trace privacy and reproducibility

Replay artifacts may include secrets and personal data. They are encrypted, access-controlled, retention-limited, and redacted only where redaction does not silently change the promised replay guarantee. A sanitized trace is explicitly downgraded if it cannot faithfully reproduce the original event.

### 13.4 Failure-to-test conversion

```bash
may replay record ./service
may replay run incident.maytrace
may replay minimize incident.maytrace
may replay test incident.maytrace --output tests/incident.test.may
```

Minimization finds a smaller trace under a specified equivalence predicate; it does not assume arbitrary side effects can be deleted while preserving behavior.

---

## 14. Distributed Behavior — MayProtocol

Networked programs have failure modes that local types cannot erase: partition, reordering, duplicate delivery, clock disagreement, ambiguous commits, stale caches, and unilateral remote changes.

Maylang treats distributed interactions as typed protocols:

```may
protocol PaymentGateway {
    state New {
        send Charge(idempotency: Key, amount: Money)
            -> Charged | Declined | Unknown;
    }
    state Unknown {
        send Reconcile(idempotency: Key)
            -> Charged | Declined | StillUnknown;
    }
}
```

Session/typestate checking prevents invalid local message order. Durable workflows preserve intent and reconciliation state. Timeouts never silently mean "the remote operation did not happen." Causal metadata and contract identities assist tracing across service boundaries. Network safety relies on authenticated peer identity, encryption, and real transport security; a protocol type alone does not supply those properties.

---

## 15. Build, Dependency, and Platform Contracts — MaySupply

### 15.1 Behavioral lockfiles

A dependency lockfile records content hashes, compiler/runtime identity, public behavior contract digests, transitive capability requirements, native artifact provenance, and supported execution domains. A dependency update that adds network access, exposes more information, weakens transaction guarantees, or increases declared peak memory prompts explicit review.

### 15.2 Reproducible builds

Hermetic build inputs and deterministic tooling produce reproducible artifacts **within a declared environment model**. Signed attestations associate the release with source and verified behavior metadata; signatures prove provenance, not absence of bugs.

### 15.3 Portable capability contracts

Instead of assuming a platform supports a feature, a module names abstract requirements:

```may
requires platform {
    monotonic_clock;
    durable_atomic_rename;
    process_isolation;
}
```

Each target provides a capability adapter with a documented contract. Unsupported guarantees fail before deployment or require an explicit downgrade; Maylang never silently maps a strong portability guarantee to a weaker OS primitive.

---

## 16. The Unified Enforcement Architecture

```text
                         MAYLANG SOURCE
                   Values + Behavior Contracts
                               |
                      Frontend / Type Checker
                               |
                 Effect, Flow, State, Cost Analysis
                               |
                 Contract IR + Proof Obligations
                     /          |           \
              Proven       Needs Guard      Unverified
                 |              |               |
            Native/VM IR   Instrumented IR   Isolated Boundary
                     \          |           /
                      Contract-Aware Linker
                               |
                       Signed Behavior Manifest
                               |
                Runtime Capability & Quota Broker
                               |
              OS Sandbox / IPC / Durable State Layer
                               |
                  Trace, Audit, Replay, Diagnostics
```

### 16.1 Compiler pipeline

1. Parse signatures, `behavior` clauses, capability declarations, state machines, policies, and refinements.
2. Resolve call graphs, traits/interfaces, virtual calls, reflection and generics conservatively.
3. Infer effect rows and authority requirements, including callback and transitive dependency effects.
4. Perform ownership/borrow/region checks and protocol-state transition validation.
5. Solve information-flow constraints and explicit declassification requirements.
6. Compose failure outcomes, transactional effect barriers, and concurrency obligations.
7. Derive resource bounds when possible; emit metering obligations otherwise.
8. Partition code by verification status and required isolation domains.
9. Lower into **Behavior IR**, preserving semantic effects rather than erasing them prematurely.
10. Emit artifacts, guard tables, sandbox profiles, replay schemas, and signed contract manifests.

### 16.2 Runtime architecture

- **Capability broker:** creates, delegates, attenuates, revokes, and checks handles.
- **Effect mediator:** governs filesystem, network, process, clock, randomness, secret and device boundaries.
- **Quota engine:** meters memory, CPU work, handles, tasks, I/O, and selected wall-clock limits.
- **Safe state runtime:** manages ownership-aware memory, actor mailboxes, transactional state, and durable logs.
- **Structured task scheduler:** manages cancellation, deterministic schedules, and conflict checking.
- **Flow monitor:** ensures protected labels survive dynamic boundaries and IPC where required.
- **Replay engine:** records nondeterministic events and detects divergence.
- **Sandbox supervisor:** runs unverified native code outside protected domains, subject to OS-level controls.
- **Contract monitor:** reports violated clauses and supports secure audit trails.

### 16.3 Linking is a security-sensitive step

The linker must preserve effective capability limits and information-flow obligations across module boundaries. Static metadata from an untrusted binary is not itself a trustworthy proof. The verifier must validate proof artifacts, or isolate the dependency and treat its claims as untrusted.

---

## 17. Standard Library and Ecosystem Rules

Every standard-library API declares its behavior. APIs may be low-level, but effects cannot be hidden behind an innocent name.

| API family | Behavioral obligation |
| --- | --- |
| Collections | Allocation, mutation, aliasing, invalidation rules |
| Files | Scoped capability, path resolution, failures, durability |
| HTTP | Host allowlist, size limits, request/response secrecy, timeouts |
| Crypto | Secret-handling rules, algorithm contracts, timing assumptions |
| SQL | Parameterization, transaction semantics, integrity labels |
| Processes | Executable allowlist, arguments as data, environment scope |
| FFI | ABI, ownership, trust boundary, isolation obligations |
| Actors | Mailbox size, state ownership, cancellation, backpressure |
| GPU | Device memory budget, synchronization, trust/domain restrictions |
| Serialization | Schema/version bounds, allocation ceilings, parse failures |

**No ambient `read_file`, `http_get`, or `run_command` in the verified standard library**: these functions require capability arguments or lexically scoped capability injection visible in the behavioral type.

---

## 18. Developer Experience

### 18.1 Behavior explanation

```bash
may explain behavior src/payments.may::settle
may explain authority --dependency fastjson
may explain flow Secret<PaymentToken> --to network
may explain resources src/decoder.may::decode
may verify --profile secure
may audit --diff main..HEAD
```

The compiler explains *why* a behavior was inferred using a minimal call path and contributing external operation, rather than showing only an opaque effect union.

### 18.2 Diagnostics

```text
error[MB-AUTH-004]: unauthorized network effect
  --> src/image.may:27:12
  decode_image -> plugin.decode -> telemetry.send

  Declared: network = none
  Required: network.connect("telemetry.example")
  Boundary: dependency "image-codec"

  Fix: remove/replace the dependency, grant a narrower capability,
       or execute the plugin in an isolated domain with network denied.
```

```text
error[MB-FLOW-011]: confidential data may reach public output
  source: Secret<AccessToken> from secrets.get("ACCESS_TOKEN")
  path: token -> format_error -> log.info
  sink: PublicLog
```

```text
error[MB-STATE-019]: illegal resource state transition
  file: File<Closed>
  attempted: File<Open>.write
```

### 18.3 IDE integration

Hover reveals a function's behavioral type; call-site hints show capability and cost requirements; data-flow tracing shows secrecy paths; refactor previews warn when authority expands. Editor fixes may insert explicit policies, but may never silently widen permissions or declassify secrets.

### 18.4 Behavioral versioning

API compatibility includes behavioral subtyping. A library version with unchanged return types but expanded effects is not automatically compatible. Contract changes become reviewable diffs and can drive semantic-versioning policy.

---

## 19. Reference Applications

### 19.1 Secure plugin host

```may
let decoder = plugins.load("image-codec") with capability {
    filesystem: none;
    network: none;
    process: none;
    memory: 64.MiB;
    cpu: 100.ms;
    output: 32.MiB;
};

let image = decoder.decode(untrusted_bytes)?;
```

Untrusted decoder code runs across an isolated boundary. Path, network, and process access are mediated; bounded output and resource consumption are guarded. The host handles timeout, crash, or malformed reply as typed failures rather than assuming the plugin is correct.

### 19.2 Secure payment processing

```may
workflow checkout(order: Validated<Order>, pay: PaymentGateway)
    behavior {
        disclose: [order.payment_token -> pay];
        failures: [Declined, Timeout, UnknownCommit, Cancelled];
        replay: recorded;
        resources: { heap_peak <= 64.MiB, tasks <= 8 };
    }
{
    let hold = inventory.reserve(order.id, order.items)?;
    let result = pay.charge(order.idempotency_key, order.total)?;

    match result {
        Charged(receipt) => {
            inventory.confirm(hold)?;
            return Committed(receipt);
        },
        Declined => {
            inventory.release(hold)?;
            return Rejected;
        },
        Unknown => {
            return NeedsReconciliation(order.id);
        }
    }
}
```

This explicitly models an uncertain external outcome rather than pretending the operation is globally atomic.

### 19.3 Deterministic game or simulation server

```may
fun tick(state: World, actions: Slice<PlayerAction>, rng: SeededRng)
    -> World ! deterministic
{
    // Same state, actions and seeded random sequence -> same observable state.
}
```

A fixed-step simulation can replay authoritative state transitions from saved input sequences, while networking and persistence stay outside the deterministic core.

### 19.4 Resource-limited public API

```may
service ThumbnailApi {
    endpoint POST "/thumbnail"(req: Untrusted<Upload>)
        -> Result<Image, ApiError>
        behavior {
            resources: { heap_peak <= 128.MiB, output <= 2.MiB };
            deadline: 500.ms;
            concurrency: isolated(request);
            authority: [sandboxed_image_decoder];
        }
    {
        let validated = validate_upload(req)?;
        return decoder.decode_and_resize(validated)?;
    }
}
```

A hostile upload cannot gain host authority through an unrestricted decoder and cannot force unlimited charged output or memory allocation within the enforced quota domain.

---

## 20. The Trust Model and Honest Guarantees

The system must label the boundary of every claim. A sound type checker cannot stop a malicious native library that executes arbitrary syscalls in the same unsandboxed process. A memory quota does not necessarily imply an RSS ceiling. A timeout cannot erase a request that has already reached a payment processor. A secret label does not automatically eliminate timing attacks. Transactional local memory does not imply distributed atomicity. Record-and-replay cannot reconstruct nondeterminism it did not observe. General-purpose static analysis cannot decide arbitrary program termination.

Maylang therefore distinguishes the following execution profiles:

| Profile | Meaning |
| --- | --- |
| `verified` | Safe language semantics with proved authority/effect/state/flow obligations; no uncontrolled native escape |
| `guarded` | Verified code plus runtime-metered obligations and monitored boundaries |
| `isolated` | Unverified or hostile code constrained by an OS sandbox and IPC interface |
| `native_unrestricted` | Full raw power with explicit loss of relevant security guarantees |
| `realtime_certified` | Narrow restricted subset under documented hardware/scheduler assumptions |

Profiles are **not** marketing levels. They define what the toolchain can substantiate. `native_unrestricted` is useful but cannot be rebranded as `verified` by supplying an annotation.

### 20.1 Trusted computing base

The trusted computing base includes the compiler/verifier for proven rules, selected runtime guards, core capability machinery, isolation supervisor, and relevant OS/hardware primitives. Its size, versions, assumptions, and security updates must be auditable. Proof artifacts and manifests are invalid if their verification basis changes without reevaluation.

### 20.2 Confidentiality caveats

Logging, crash reports, replay traces, profiler output, debugging introspection, and contract metadata are themselves output channels. The platform must label and govern them just like application data.

### 20.3 Crash isolation and availability

A sandbox may protect confidentiality and integrity while failing to guarantee service availability. Denial-of-service risk is managed with metering, process limits, queues, deadlines, and supervision; absolute availability cannot be proven under arbitrary hardware and environmental faults.

---

## 21. Normative Language Laws

A conforming verified Maylang implementation must satisfy these invariants:

1. **No ambient authority:** protected resources are inaccessible without an appropriate effective capability.
2. **No silent effect expansion:** linked and dynamically dispatched calls respect the caller's behavior ceiling.
3. **No privilege amplification:** delegated capabilities cannot exceed their origin's authority.
4. **No unchecked sensitive flow:** declared information-flow rules hold for covered channels; declassification is explicit and authorized.
5. **No invalid safe reference:** verified ownership/lifetime rules prevent use-after-free, invalid borrows, and data races for memory under the safe model.
6. **No illegal protocol transition:** typestate operations respect their preconditions and required terminal states.
7. **No hidden failures:** all recoverable exposed failures and cancellation outcomes are represented in declared contracts or handled before return.
8. **No unguarded hard quotas:** hard resource limits require metering or OS enforcement, not annotation alone.
9. **No fictional atomicity:** transactions advertise only the atomicity domain actually provided.
10. **No untracked child-task escape:** structured tasks cannot leave scope without completion, cancellation, or explicitly transferred ownership.
11. **No unsupported replay claims:** deterministic and recorded functions expose and account for all nondeterministic sources in the supported model.
12. **No silent contract downgrade:** unsupported target guarantees cause rejection or an explicit, visible downgrade accepted by the deployer.
13. **No trust laundering:** unverified native libraries cannot present unchecked metadata as verified proof.
14. **No accidental behavioral compatibility:** public effects, permissions, information flow, resource bounds, and guarantees participate in dependency/API compatibility.
15. **No invisible policy changes:** authority broadening, declassification, new external sinks, and lowered enforcement levels require traceable decisions.

---

## 22. Conformance and Validation

Conformance is measured against **behavioral properties**, not simply whether the compiler accepts example programs.

### 22.1 Negative tests

The checker must reject pure functions that perform undeclared I/O; permission escalation via callbacks; secret-to-public flows; state use after close; escaping invalid borrows; unsafe parallel mutable aliases; irreversible effects in local transactions; incompatible behavior subtyping; and unsupported environment contracts.

### 22.2 Adversarial runtime tests

An isolated dependency attempts direct syscalls, filesystem traversal, network exfiltration, process creation, excessive allocation, task floods, malformed IPC, and exit/hang behavior. Tests must verify actual containment under the supported OS boundary—not merely an expected exception in a cooperative library.

### 22.3 Property-based and differential tests

Generate programs and compare inferred contracts to instrumented traces; verify static bounds against measured charged operations; compare optimized and unoptimized behavior IR; perturb cancellation points; test concurrent schedules; check flow-policy preservation through serialization, FFI, exceptions, and logging.

### 22.4 Replay verification

Run recorded traces under the same build identity, verify event hashes and causal ordering, deliberately mutate one recorded event, and confirm deterministic divergence reporting. Validate encryption, retention and access policy of crash artifacts.

### 22.5 Formal verification targets

Define a small core calculus and mechanically verify progress/preservation (for the safe fragment), capability monotonicity, relevant noninterference properties, and operational correspondence of checked effect summaries. Expand proofs to resource guards and transactional semantics when their execution models are sufficiently specified. Full-language certification is a program of ongoing proof work, not a one-time assertion.

---

## 23. Performance and Usability Targets

MayBehavior should be usable for real applications, not merely a verifier demonstration.

- Pure functions should compile without unnecessary capability dispatch or runtime checks.
- Proven contracts should erase their guards when optimization preserves the proof.
- Hot paths should support zero-allocation and bounded-allocation programming.
- Inter-module behavior summaries should permit incremental compilation and caching.
- Dynamic checks should occur at meaningful boundaries rather than every arithmetic operation.
- Sandboxed native code should support batch IPC, shared-memory transfer under explicit ownership, and amortized crossings.
- Inference should prevent developers from writing endless boilerplate; exported contracts should stay readable.
- Compiler errors must show the smallest useful explanation path, not thousands of transitive effects.
- The language should support relaxed profiles for prototyping without misleadingly claiming stronger guarantees.

Performance numbers must be established by benchmarks and workloads. No overhead percentages are promised in this specification.

---

## 24. Design Decisions That Must Remain Explicit

These decisions materially change the language contract and must be settled through measured prototypes or formal models:

1. Whether the default execution mode is `verified` or `guarded` for application binaries.
2. Which static flow channels are mandatory, and which require hardened profiles.
3. Whether ownership is fully static, hybrid with regions/GC, or uses automatic insertion of safe runtime checks.
4. The precise lattice for confidentiality and integrity labels and how multi-principal policies compose.
5. How effect-polymorphic recursion, open-world virtual dispatch, and reflection affect inference.
6. Which resource metrics are portable and which are platform-specific.
7. What constitutes a stable behavioral API and which changes require major versions.
8. How foreign calls and native plugins are isolated while preserving high performance.
9. Which failure/recovery syntax best interoperates with typed results and `?` propagation.
10. How deterministic replay handles asynchronous I/O, message causality, native code, and mutable shared memory.
11. Which transactional isolation levels and durable storage primitives are guaranteed.
12. What proof artifacts third-party package publishers can produce, and how they are independently verified.

These are specification questions, **not excuses to weaken the ultimate objective**.

---

## 25. Final Product Definition

**Maylang is a behavior-aware systems and application programming language.**

Its essential distinction is a *unified behavior type* connecting compile-time verification with runtime enforcement and operating-system isolation. A program declares and composes what it can access, change, disclose, consume, fail with, and assume about execution. Behavior is as inspectable and reviewable as a function's ordinary type.

The ultimate developer experience is:

1. Write straightforward code; the compiler infers most behavior.
2. State constraints where they matter: module boundaries, public APIs, secrets, plugins, requests, financial actions, and resource-intensive operations.
3. See precise errors whenever implementation behavior exceeds those contracts.
4. Run unverified dependencies behind actual isolation boundaries.
5. Deploy with signed, inspectable manifests describing authorities and guarantees.
6. Reproduce supported production failures through privacy-aware, deterministic traces.
7. Upgrade dependencies with a review of their behavioral changes, not just their exported names.

**Positioning statement:**

> **Maylang does not merely type the values a program manipulates. It types, verifies, and enforces the behavior of the program itself.**

**Ultimate success criterion:** Maylang makes surprising program behavior an explicit, reviewable exception rather than the default cost of writing software.
