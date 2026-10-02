# Maylang Grammar (EBNF)

This grammar describes the legacy Rust toolchain. In self-hosted `mayc`,
parameter, variable and loop annotations and function result types are required,
and function bodies must use explicit `return`. See [strict syntax](STRICT.md).

Notation: `{ x }` = zero or more, `[ x ]` = optional, `|` = alternative,
`"..."` = terminal, `(* ... *)` = comment.

```ebnf
(* ------------------------------------------------------------------ *)
(* Program                                                             *)
(* ------------------------------------------------------------------ *)
program          = { declaration } EOF ;

declaration      = funDecl
                 | letDecl
                 | importDecl
                 | statement ;

funDecl          = "fun" IDENT [ "<" IDENT { "," IDENT } ">" ]
                   "(" [ params ] ")" [ "->" type ] block ;

letDecl          = [ "let" | "mut" ] IDENT [ ":" type ] [ "=" expression ] ";" ;
                 (* "let"/"mut" are required for declarations; bare
                    IDENT "=" ... is an assignment expression statement. *)

importDecl       = "import" STRING ";"
                 | "from" STRING "import" IDENT { "," IDENT } ";" ;

params           = param { "," param } ;
param            = IDENT [ ":" type ] ;

type             = typeAtom [ "<" type { "," type } ">" ] [ "?" ]
                 | "[" type ";" INT "]" ;
typeAtom         = IDENT | "(" [ type { "," type } ] ")" [ "->" type ]
                 | "Fn" "(" [ type { "," type } ] ")" "->" type ;

(* ------------------------------------------------------------------ *)
(* Statements                                                          *)
(* ------------------------------------------------------------------ *)
statement        = letDecl
                 | funDecl
                 | importDecl
                 | whileStmt
                 | forStmt
                 | returnStmt
                 | breakStmt
                 | continueStmt
                 | block
                 | exprStmt ;

whileStmt        = "while" [ "(" ] expression [ ")" ] body ;
forStmt          = "for" IDENT "in" expression body ;
returnStmt       = "return" [ expression ] ";" ;
breakStmt        = "break" ";" ;
continueStmt     = "continue" ";" ;
exprStmt         = expression [ ";" ] ;   (* no ";" => trailing value of a block *)

body             = block | statement ;     (* brace-less single statements allowed *)
block            = "{" { statement } [ expression ] "}" ;
                 (* block value = trailing expression, else nil *)

(* ------------------------------------------------------------------ *)
(* Expressions  (lowest to highest precedence)                          *)
(* ------------------------------------------------------------------ *)
expression       = assignment ;
assignment       = nilCoalesce [ ( "=" | "+=" | "-=" | "*=" | "/=" ) assignment ] ;
nilCoalesce      = pipe { "??" pipe } ;                  (* left associative  *)
pipe             = logicOr { "|>" logicOr } ;            (* left associative  *)
logicOr          = logicAnd { ( "or" | "||" ) logicAnd } ;
logicAnd         = equality { ( "and" | "&&" ) equality } ;
equality         = comparison { ( "==" | "!=" ) comparison } ;
comparison       = rangeExpr { ( "<" | "<=" | ">" | ">=" ) rangeExpr } ;
rangeExpr        = term [ ( ".." | "..=" ) term ] ;
term             = factor { ( "+" | "-" ) factor } ;
factor           = unary { ( "*" | "/" | "%" ) unary } ;
unary            = ( "-" | "!" | "not" ) unary | power ;
power            = postfix [ "**" unary ] ;              (* right associative *)
postfix          = primary { call | index | property | safeProperty } ;
call             = "(" [ arguments ] ")" ;
index            = "[" expression "]" ;
property         = "." IDENT ;
safeProperty     = "?." IDENT ;
arguments        = expression { "," expression } ;

primary          = INT
                 | FLOAT
                 | STRING
                 | INTERP_STRING
                 | "true" | "false" | "nil"
                 | IDENT
                 | "(" expression ")"
                 | listLiteral
                 | mapLiteral
                 | comprehension
                 | ifExpr
                 | unlessExpr
                 | mayExpr
                 | matchExpr
                 | lambda
                 | shortLambda
                 | arrowLambda ;

interp           = STRING with embedded ${ expression } holes    (* desugared to + *)
listLiteral      = "[" [ listItem { "," listItem } ] "]" ;
listItem         = expression | "..." expression ;
mapLiteral       = "{" [ mapItem { "," mapItem } ] "}" ;
mapItem          = mapEntry | "..." expression ;
mapEntry         = ( IDENT | expression ) ":" expression ;
comprehension    = "[" expression "for" IDENT "in" expression [ "if" expression "]" ;
matchExpr        = "match" expression "{" { matchArm } "}" ;
matchArm         = pattern [ "if" expression ] "=>" ( expression | block ) [ "," ] ;
pattern          = "_" | IDENT | literal | "-" number ;
lambda           = "fun" "(" [ params ] ")" block ;
shortLambda      = "|" [ params ] "|" ( expression | block ) ;
arrowLambda      = IDENT "=>" ( expression | block ) ;

ifExpr           = "if" expression body [ "else" ( body | ifExpr ) ] ;
unlessExpr       = "unless" expression body [ "else" ( body | ifExpr ) ] ;
mayExpr          = "may" block [ "otherwise" block ] ;

(* ------------------------------------------------------------------ *)
(* Tokens                                                              *)
(* ------------------------------------------------------------------ *)
IDENT            = ( letter | "_" ) { letter | digit | "_" } ;
INT              = digit { digit | "_" } ;
FLOAT            = digit { digit | "_" } "." digit { digit | "_" } [ exponent ]
                 | digit { digit | "_" } exponent ;
exponent         = ( "e" | "E" ) [ "+" | "-" ] digit { digit } ;
STRING           = '"' { char | escape | interpolation } '"' ;
interpolation    = "${" expression "}" ;
escape           = "\\" ( "n" | "t" | "r" | "0" | "\\" | '"' | "$" ) ;
comment          = "//" { any-char-except-newline }
                 | "/*" { any-char } "*/" ;     (* block comments nest *)
```

## Semantics of the signature features

### `may { A } [otherwise { B }]`
`A` is executed speculatively. If evaluating `A` raises a runtime fault
(division by zero, type error, name/index errors, `fail(...)`, arity mismatch,
...), the runtime unwinds to the speculative boundary. With an `otherwise` block it
evaluates `B` instead; **without** one, the expression yields `nil`.

```may
let cfg = may { read_config("app.toml") } otherwise { default_config };
let n   = may { parse_int(s) };              // nil on failure
```

### Error propagation `expr?`
`Ok(v)`/`Err(e)` (and `Some(v)`/`None`, where `None` is `nil`) are ordinary
`{ok, value, error}` maps. Postfix `?` evaluates the operand and, when its `ok`
field is `false` (or the operand is `nil`), returns that operand from the
enclosing function; otherwise it yields the `value` field.

```may
fun load(path) { if (!file_exists(path)) { return Err("missing " + path); } Ok(read_file(path)) }
fun length(path) { let text = load(path)?; len(text) }
```

### Nil-coalescing `a ?? b`
Yields `b` when `a` is `nil`, otherwise `a`. Chains cleanly with `may`:

```may
let port = (may { parse_int(s) }) ?? 8080;
```

### Safe navigation `a?.b`
If `a` is `nil`, the **entire remaining postfix chain** short-circuits to
`nil`, including calls and further accesses:

```may
user?.profile?.email       // nil instead of a fault
user?.address?.print()     // never called when user/address is nil
```

### Structured errors
Inside `otherwise`, `err` is an error object exposing:

| field     | description                                            |
|-----------|--------------------------------------------------------|
| `message` | human-readable message                                 |
| `kind`    | `arithmetic`, `type`, `name`, `index`, `arity`, `fail`, `assert`, `io`, `parse`, `runtime` |
| `stack`   | newline-separated `at <function> (line N)` frames      |

```may
may { risky() } otherwise { print("${err.kind}: ${err.message}") };
```

### `unless C S else E`
Syntactic sugar for `if !C S else E`. Useful for guard clauses:
`unless (ready) return nil;`

### `a |> f |> g`
Pipelines insert the left-hand value as the **first argument** of the call on
the right. `x |> f` desugars to `f(x)`; `x |> f(y)` desugars to `f(x, y)`.

### Pattern matching
`match` is an expression. Patterns are literals, `_` (wildcard) or an
identifier (binding). Arms may have `if` guards; the first matching arm wins.
A non-exhaustive `match` raises a `match` fault (catchable by `may`). In strict
`mayc`, Boolean matches are checked for both `true` and `false`; an unguarded
identifier or wildcard arm covers both. Other types still need a wildcard when
runtime values may be unmatched. Enum variant destructuring is not supported
by the strict matcher yet.

```may
let label = match (status) {
    200 => "OK",
    404 => "Missing",
    n if n >= 500 => "Server error",
    _   => "Unknown",
};
```

### Spread, comprehensions, interpolation
* `[1, ...rest, 3]` concatenates lists; `{...defaults, k: 1}` merges maps
  (`merge`) left-to-right, later keys winning.
* `[expr for x in items if cond]` desugars to `map(filter(items, |x| cond), |x| expr)`.
* `"total: ${n}, ${x + 1}"` desugars to a `+` chain, so any value is
  stringified via its display form.
* Short lambdas `|x| x + 1`, `|a, b| a + b`, `x => x * 2` are sugar for
  `fun`-lambdas; the body may be an expression or a block.

### Expression-oriented blocks
A block `{ s1; s2; expr }` evaluates to `expr`; a block ending in `;` (or with
no trailing expression) evaluates to `nil`.

### Types and generics
Type hints, return types and type parameters are parsed (and erased at
runtime); `maylang check` verifies them with unification.

```may
let x: Int = 1;
let grid: List<List<Int>> = [[1, 2], [3, 4]];
let table: Map<Str, Int> = {"a": 1};
let maybe: Int? = nil;
fun head<T>(items: List<T>) -> T { items[0] }
fun apply<A, B>(f: (A) -> B, x: A) -> B { f(x) }
```

Types include `Int8`/`Int16`/`Int32`/`Int64`, `UInt8`/`UInt16`/`UInt32`/
`UInt64`, `Float32`/`Float64`, `Ptr<T>`, `Array<T, N>` or `[T; N]`, `Slice<T>`,
`Option<T>`, `Result<T, E>`, `Tuple<T, U, ...>`, and function types written
`(Type, ...) -> Type` or `Fn(Type, ...) -> Type`. `Byte`, `RawPtr`, `F32`, and
`F64` are aliases. Existing `List`, `Map`, named enum/struct types, nullable
`Type?`, and generic parameter names are also accepted. The fixed-width and
aggregate annotations are erased by the current runtime; see the
[strict typing guide](STRICT.md) for representation limits.

### Destructuring
`let`/`mut` and `for` accept a binding pattern. Patterns are desugared into
ordinary `let` bindings, so they are pure sugar:

```may
let {x, y} = point;          // x = point["x"], y = point["y"]
let {x: px} = point;         // px = point["x"]
let [a, b] = pair;           // a = pair[0], b = pair[1]
let {pos: [px, py]} = obj;   // patterns nest; `_` ignores a position
for {name, age} in people { .. }
```

A composite pattern evaluates its source once into a hidden temporary.
