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

Fixed-width integer and float annotations currently use the tagged `Int` and
`Float` runtime values and do not select machine-width storage or enforce
overflow bounds. Arrays and slices use the list runtime representation;
`Result` and `Tuple` currently describe existing values at the type-checking
level.

The return analysis accepts both returning branches of an `if` and returning
`may`/`otherwise` branches. It is conservative about loops: add an explicit
return after a loop even if it seems endless. Destructuring declarations and
loop patterns must currently be expanded to individually typed bindings.
Postfix `?` currently requires an `Any` operand in strict code; `Result<T, E>`
does not yet connect result propagation to a function's declared error type.
Overloaded arithmetic also uses explicit `Any` boundaries until it has static
contracts. For `Bool` matches, both `true` and `false` cases (or a wildcard)
are required; other matches may still fail at runtime if no arm matches.

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
