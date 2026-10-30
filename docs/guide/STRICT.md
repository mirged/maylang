# Strict typing in mayc

The self-hosted `compiler/mayc/mayc_new` compiler checks types by default.
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
compiler/mayc/mayc_new examples/strict.may -o /tmp/strict-example
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

`Any` supports heterogeneous JSON, runtime maps, AST nodes, raw APIs and legacy
operator dispatch. Concrete values can widen to `Any`. Strict mode rejects
implicit narrowing from `Any` to a concrete type at bindings, assignments,
user function arguments and returns, typed collection writes and loop bindings.
This rule also applies inside `List`, `Map`, `Optional`, `Result` and function
types. Use a generic API to preserve a payload's type, or an explicit conversion
such as `str(value)`, `int(value)`, `float(value)` or `bool(value)`:

```may
fun identity<T>(value: T) -> T { return value; }
let dynamic: Any = 123;
// let text: Str = dynamic; // error: expected Str, found Any
let text: Str = str(dynamic);
let number: Int = identity(123); // generic identity<T> preserves Int
let payload: Str = Some("hello").value ?? "missing";
```

Conversions have their own conversion semantics: `str(123)` produces `"123"`
and `int("hello")` faults. They are not arbitrary casts. `Some` and `Ok` preserve
the success payload type as `Result<T, Never>`; `.value` is optional. There is
no general checked cast from dynamic objects to nominal records or functions.
Dynamic calls, operators, predicates and native builtins retain runtime
dispatch; an `Any` condition still uses truthiness. Typed callbacks check
parameter compatibility in the contravariant direction and return compatibility
in the covariant direction. `--legacy` keeps the previous unchecked behavior.
Values are fat (16 bytes: a type word and a payload), with types erased after
checking ([docs/design/FAT_VALUES.md](../design/FAT_VALUES.md)).

`Int8`, `Int16`, `Int32`, `UInt8`, `UInt16` and `UInt32` enforce their
declared bounds at typed bindings, assignments, arguments, returns and
collection accesses. Invalid integer literals fail checking; dynamic overflow
raises an `arithmetic` fault, which ends the program with status 70 when it is
not caught. Integer families are assignment-compatible, so a dynamic
conversion to a narrower type is checked rather than rejected solely for
having a wider type. `Int` and `Int64` are signed 64-bit on every runtime and
target; `UInt64` uses the nonnegative part of that range.

On every target, a function whose parameters and result are all `Int`, `Ptr`
or `Bool`, and whose body uses only such locals and globals, `true`, `false`,
integer operators, comparisons, `if`, `while`, `for` over `a..b` or `a..=b`,
`break`, `continue`, `load8` through `load64`, `store8` through `store64`,
`syscall` (full runtime), calls to top-level functions
whose parameters (at most six) and result are `Int`, `Ptr` or `Bool`, and
calls to `extern` functions whose parameters are `Int`, `UInt`, `Ptr` or
`Bool` and whose result is one of those or `Void` (x86-64 Linux), compiles as a native-word function on x86-64 (ARM64 and RISC-V compile it as ordinary code with the same results). Inside it, and across calls
between such functions, `Int` values are signed 64-bit machine words:
bitwise operators reach bit 63, `load64` keeps all 64 bits, shift counts may
be 0 through 63, and `+`, `-`, `*`, `/` and negation fault on 64-bit
overflow. Int and Bool payloads already are machine words, so native-word
functions exchange them with other code unchanged; an argument of another
type raises a `type` fault. Extern calls pass machine words straight to C,
so an `Int` or `Ptr` result keeps all 64 bits; a negative `UInt` argument or a
`UInt` result above the `Int` range raises an `arithmetic` fault. `Int32` and
`UInt32` values carry range contracts, so their users stay ordinary code. In other
code, an `Int` or `Bool` expression that contains a bitwise operator and uses
only integer variables, literals, operators and such calls is compiled the
same way, with its variables (at most six) passed as arguments, so
`(1 << 63) & (1 << 63) != 0` is `true`; an expression that calls a function
and also reads a global stays ordinary code. Debug traces omit native-word frames,
so under `--debug` a native-word function may only call other native-word
functions ([#92](https://github.com/mirged/maylang/issues/92)).

`Float32` rounds through IEEE binary32 at typed boundaries and keeps the
existing boxed binary64 storage. `Float` and `Float64` use binary64. Float32
requires the full runtime. Lists and results recursively check their numeric
payloads; rounding collection elements also affects aliases to that collection.
Arrays and slices use the list representation. Fixed arrays check their length
on assignment and return, including runtime values whose length is unknown
during checking. `Tuple` remains a static description of existing values.
Mutable dynamic aliases can still bypass invariants; numeric contracts run at
the next typed access. Rejecting implicit narrowing does not prevent mutation
through a separately retained `Any` alias or raw memory operations;
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
compiler/mayc/mayc_new --legacy old.may -o /tmp/old
python3 compiler/mayc/tools/migrate_strict.py old.may --write
```

The migration script adds explicit `Any` annotations and return statements.
Review its output, especially destructuring loops and complex control flow,
then replace dynamic annotations with concrete types where appropriate.
In VS Code, `maylang.strict` defaults to `true`; set it to `false` only when
editing legacy code. Rebuild the server and reload the VS Code window after
updating the compiler and extension.
