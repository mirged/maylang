# Strict typing in mayc

The self-hosted `toolchain/mayc/mayc_new` compiler checks types by default.
The Maylang language server uses the same checker. The Rust `maylang` toolchain
remains a separate legacy implementation; use mayc for the syntax below.

```may
fun add(a: Int, b: Int) -> Int {
    return a + b;
}
let answer: Int = add(20, 22);
mut total: Int = 0;
let values: List<Int> = [answer, 8];
for value: Int in values {
    total += value;
}
print(total);
```

Compile and run from the repository root:

```sh
toolchain/mayc/mayc_new examples/strict.may -o /tmp/strict-example
/tmp/strict-example
```

Function parameters, struct fields and enum payload parameters need types.
Loop and comprehension bindings infer their type from the iterable's element
type. Local `let` and `mut` bindings infer their type from the initializer;
add an annotation when you want to state a public contract or resolve an
ambiguous/dynamic value. Function parameters always need annotations.
A function may declare its result type, or mayc can infer it
from explicit returns. Every path must still use `return`; a final expression
does not implicitly return from a strict function. Use `return;` for a function
returning `Nil`. Conditions must have type `Bool`.

Primitive types include `Int`, `Int8`, `Int16`, `Int32`, `Int64`, `UInt8`
(also `Byte`), `UInt16`, `UInt32`, `UInt64`, `Float`, `Float32` (also `F32`),
`Float64` (also `F64`), `Str`, `Bool`, `Nil` (also `Void`), and `Ptr<T>` (also
`RawPtr`). Collections include `List<T>`, `Slice<T>`, fixed arrays `[T; N]`
(also `Array<T, N>`), `Map<K, V>`, `Option<T>`/`Optional<T>`, `Result<T, E>`,
and `Tuple<T, U, ...>`. Function types can use `(A, B) -> R` or
`Fn(A, B) -> R`. Bare generic collection names are invalid annotations. Map
lookup yields `Optional<V>` because a key may be absent. Use `??` to supply a
value:

```may
let counts: Map<Str, Int> = {"apple": 2};
let count: Int = counts["pear"] ?? 0;
let doubled: List<Int> = [x * 2 for x in [1, 2, 3]];
let transform: (Int) -> Int = fun(x: Int) -> Int { return x * 2; };
```

Struct constructors, fields, collection elements, assignments, call arity,
function arguments and return values are checked. Named types retain their
module identity; imported types can be written `library.Point`. Generic
functions unify type parameters across arguments:

```may
struct Point { x: Int, y: Int }
fun identity<T>(value: T) -> T { return value; }
let point: Point = identity(Point(3, 4));
```

`Any` explicitly opts a value out of static type checking. It is useful for
heterogeneous JSON, runtime maps, AST nodes, raw APIs and legacy operator
dispatch. The repository migration uses `Any` at existing dynamic boundaries;
it does not infer concrete contracts for every old program. Values still use
the existing tagged runtime representation, and types are erased after checking.
Calling a dynamic value or passing one into a concrete API can still fail at runtime.

Integer annotations use the tagged integer ABI. `Int8`, `Int16`, `Int32`,
`UInt8`, `UInt16` and `UInt32` enforce their declared bounds at typed
bindings, assignments, arguments, returns and collection accesses. Invalid
integer literals fail checking; dynamic overflow raises an `arithmetic`
fault in the full runtime, or exits with status 70 in the core runtime.
Integer families are assignment-compatible, so a dynamic conversion to a
narrower type is checked rather than rejected solely for having a wider type.
`Int` and `Int64` retain the signed 61-bit range
`-1152921504606846976..1152921504606846975`; `UInt64` uses its nonnegative
part. These names do not provide a complete 64-bit payload or machine-width
storage.

`Float32` rounds through IEEE binary32 at typed boundaries and keeps the
existing boxed binary64 storage. `Float` and `Float64` use binary64. Float32
requires the full runtime. Lists and results recursively check their numeric
payloads; rounding collection elements also affects aliases to that collection.
Arrays and slices use the list representation. Fixed arrays check their length
on assignment and return, including runtime values whose length is unknown
during checking. `Tuple` remains a static description of existing values.
`Any` and mutable aliases can bypass invariants until the next typed access;
the language does not provide ownership or immutable collection storage.

The return analysis accepts both returning branches of an `if` and returning
`may`/`otherwise` branches. It is conservative about loops: add an explicit
return after a loop even if it seems endless. Destructuring declarations and
loop patterns must currently be expanded to individually typed bindings.
`Ok(value)` infers `Result<T, Never>` and `Err(error)` infers
`Result<Never, E>`. Postfix `?` unwraps a typed result's success value and
propagates failure only from a function returning `Result<U, E>` with a
compatible error type. Dynamic `Any` propagation remains available.
Result `.value` and `.error` fields are optional; matching extracts a concrete
payload without an unchecked access:

```may
fun describe(value: Result<Int, Str>) -> Str {
    return match(value) { Ok(n) => str(n), Err(message) => message };
}
enum Shape { Empty, Point(x: Int, y: Int) }
fun size(shape: Shape) -> Int {
    return match(shape) { Empty() => 0, Point(x, y) => x + y };
}
```

Constructor patterns support typed bindings, ignored `_` payloads, guards,
and imported namespace constructors. Nullary patterns use `Variant()`.
Enum and Result matches must cover every variant or have an unguarded wildcard;
guarded arms do not count as complete coverage. Payload bindings can be captured
by closures and are scoped to their arm.
Overloaded arithmetic also uses explicit `Any` boundaries until it has static
contracts. For `Bool` matches, both `true` and `false` cases (or a wildcard)
are required; other open-ended value matches should include a wildcard.

For existing untyped source, `--legacy` disables the new strict pass:

```sh
toolchain/mayc/mayc_new --legacy old.may -o /tmp/old
python3 toolchain/mayc/tools/migrate_strict.py old.may --write
```

The migration script adds explicit `Any` annotations and return statements.
Review its output, especially destructuring loops and complex control flow,
then replace dynamic annotations with concrete types where appropriate.
In VS Code, `maylang.strict` defaults to `true`; set it to `false` only when
editing legacy code. Rebuild the server and reload the VS Code window after
updating the compiler and extension.
