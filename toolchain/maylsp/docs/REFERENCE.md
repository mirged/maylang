# Maylang editor reference

Generated from `reference.json`; edit the catalog and run `python3 docs/generate.py` from `toolchain/maylsp`. These descriptions also appear in hover, completion, and signature help. Signatures describe the public API; dynamic values may have several types.

## Keywords

### `fun`

```may
fun name(arg: Type) -> ReturnType { return value; }
```

Declare a function with typed parameters. Its return type may be written explicitly or inferred from return statements. Every path must return; functions capture surrounding bindings.

**Example**
```may
fun double(x: Int) -> Int { return x * 2 }
print(double(3));
```

### `let`

```may
let name: Type = expression;  // Type may be inferred
```

Declare an immutable binding. Mayc infers its type from the initializer when the annotation is omitted. Lists and maps stored in a let binding may still be mutated; their element types are checked.

**Example**
```may
let count: Int = 10;
let items: List<Int> = [];
push(items, count);
```

### `mut`

```may
mut name: Type = expression;  // Type may be inferred
```

Declare a mutable binding. Mayc infers its type from the initializer when the annotation is omitted. Later assignments must match that type.

**Example**
```may
mut total: Int = 0;
total += 5;
```

### `if`

```may
if (condition) { value } else { alternative }
```

Evaluate a branch based on the condition. An `if` expression produces the chosen branch value.

**Example**
```may
let label: Str = if (true) { "ready" } else { "waiting" };
```

### `else`

```may
if (condition) { ... } else { ... }
```

Provide the alternative branch of an `if` or `unless`. Chain `else if` for additional conditions.

**Example**
```may
let sign: Int = if (3 > 0) { 1 } else if (3 < 0) { -1 } else { 0 };
```

### `while`

```may
while (condition) { body }
```

Repeat a body while its condition is true. `break` stops the loop and `continue` skips to its next iteration.

**Example**
```may
mut i: Int = 0;
while (i < 3) { print(i); i += 1; }
```

### `for`

```may
for item in iterable { body }  // optional: item: Type
```

Iterate over values or an integer range. Mayc infers the loop variable type from the iterable; an explicit type may be added as a checked constraint.

**Example**
```may
for i: Int in 0..3 { print(i); }
let squares: List<Int> = [x * x for x: Int in [1, 2, 3]];
```

### `in`

```may
for item in iterable { ... }
```

Connect a loop or comprehension binding to its iterable. Range upper bounds use `..` for exclusive and `..=` for inclusive.

**Example**
```may
let evens: List<Int> = [x for x: Int in 0..6 if (x % 2 == 0)];
```

### `return`

```may
return expression;
```

Exit the enclosing function with a value of its declared return type. A bare return yields nil. Strict functions require explicit return on every path.

**Example**
```may
fun first(xs: Any) -> Any {
    unless (len(xs) > 0) return nil;
    return xs[0];
}
```

### `break`

```may
break;
```

Stop the innermost loop immediately. Execution resumes after the loop.

**Example**
```may
for x: Any in [1, 2, 3] { if (x == 2) { break; } print(x); }
```

### `continue`

```may
continue;
```

Skip the remaining body of the innermost loop and advance to its next iteration.

**Example**
```may
for x: Any in 0..4 { if (x == 2) { continue; } print(x); }
```

### `unless`

```may
unless (condition) statement
```

Execute the body when the condition is false. Useful for guard clauses; an `else` branch is also supported.

**Example**
```may
fun head(xs: Any) -> Any { unless (len(xs) > 0) return nil; return xs[0] }
```

### `match`

```may
match (value) { pattern => expression, ... }
```

Choose the first matching arm. Literal patterns, name bindings and the wildcard _ are supported by mayc.

**Example**
```may
let label: Any = match (2) { 1 => "one", 2 => "two", _ => "other" };
```

### `may`

```may
may { expression } otherwise { recovery }
```

Catch a runtime failure within the block and evaluate a recovery expression. Inside `otherwise`, `err` contains the failure information.

Without `otherwise`, a caught failure produces `nil`.

**Example**
```may
let value: Any = may { int("oops") } otherwise { print(err.message); 0 };
```

### `otherwise`

```may
may { ... } otherwise { ... }
```

Handle a failure from the preceding `may` block. `err.message` describes it and `err.kind` identifies its category.

**Example**
```may
may { fail("missing item"); } otherwise { print(err.kind, err.message); };
```

### `struct`

```may
struct Name { field: Type, ... }
```

Declare a record type with named fields. Construct values by calling the type name and access fields with `.`.

**Example**
```may
struct Point { x: Int, y: Int }
let p: Point = Point(2, 3);
print(p.x);
```

### `enum`

```may
enum Name { Variant, Variant(Type), ... }
```

Declare tagged variants, optionally carrying values. Match variants to select behavior and bind their payloads.

**Example**
```may
enum Color { Red, Green, Blue }
let color: Any = Red();
```

### `pub`

```may
pub fun name(...) { ... }
```

Export a top-level declaration from its module. When a module contains explicit public declarations, private declarations are hidden from importers.

**Example**
```may
pub fun answer() -> Any { return 42 }
```

### `extern`

```may
extern fun name(parameters);
```

Declare a foreign function for native linking. This requires an actual external symbol and suitable compiler/linker setup.

**Example**
```may
extern fun puts(s: Ptr) -> Any;
```

### `import`

```may
import "module" as alias;
```

Load a module relative to the current source file, then search the standard library. The `.may` suffix is optional. Use an alias for qualified access.

**Example**
```may
import "math" as math;
print(math.square(3));
```

### `from`

```may
from "module" import name;
```

Import selected public declarations into the current scope. Unselected names remain unavailable.

**Example**
```may
from "math" import square;
print(square(4));
```

### `as`

```may
import "module" as alias;
```

Give an imported module a local namespace. Access its public declarations with `alias.name`.

**Example**
```may
import "string" as strings;
print(strings.words("hello world"));
```

### `and`

```may
left and right
```

Evaluate logical conjunction with short circuiting. The right expression is skipped when the left expression is false.

**Example**
```may
let ok: Any = len([1]) > 0 and [1][0] == 1;
```

### `or`

```may
left or right
```

Evaluate logical disjunction with short circuiting. The right expression is skipped when the left expression is true.

**Example**
```may
let accepted: Any = true or false;
```

### `not`

```may
not expression
```

Negate the truth value of an expression. `!` is the symbolic spelling.

**Example**
```may
print(not false); // true
```

### `true`

```may
true
```

The boolean true value. Returned by successful comparisons and predicates.

**Example**
```may
let enabled: Bool = true;
```

### `false`

```may
false
```

The boolean false value. Together with `nil`, it is false in condition tests.

**Example**
```may
let enabled: Bool = false;
```

### `nil`

```may
nil
```

Represent the absence of a value. Missing map lookups and empty `pop` calls produce `nil`; `??` supplies a fallback.

**Example**
```may
let missing: Any = map_get({}, "name");
print(missing ?? "anonymous");
```

## Types

### `Int8`

```may
Int8
```

Signed 8 bit integer

**Example**
```may
let small: Int8 = 12;
```

### `Int16`

```may
Int16
```

Signed 16 bit integer

**Example**
```may
let small: Int16 = 1200;
```

### `Int32`

```may
Int32
```

Signed 32 bit integer

**Example**
```may
let count: Int32 = 100000;
```

### `Int64`

```may
Int64
```

Signed 64 bit integer

**Example**
```may
let count: Int64 = 10000000000;
```

### `UInt8`

```may
UInt8
```

Unsigned 8 bit integer, also named Byte

**Example**
```may
let byte: UInt8 = 255;
```

### `UInt16`

```may
UInt16
```

Unsigned 16 bit integer

**Example**
```may
let value: UInt16 = 500;
```

### `UInt32`

```may
UInt32
```

Unsigned 32 bit integer

**Example**
```may
let value: UInt32 = 50000;
```

### `UInt64`

```may
UInt64
```

Unsigned 64 bit integer

**Example**
```may
let value: UInt64 = 5000000;
```

### `Float32`

```may
Float32
```

32 bit floating point number, also named F32

**Example**
```may
let ratio: Float32 = 0.5;
```

### `Float64`

```may
Float64
```

64 bit floating point number, also named F64

**Example**
```may
let ratio: Float64 = 0.5;
```

### `Slice`

```may
Slice
```

Borrowed view of a sequence with element type T

**Example**
```may
let part: Slice<Int> = values[0..2];
```

### `Tuple`

```may
Tuple
```

Tuple type containing the listed element types

**Example**
```may
let pair: Tuple<Int, Str> = (1, "one");
```

### `Result`

```may
Result
```

Result type with success and error types

**Example**
```may
let outcome: Result<Int, Str> = value;
```

### `Array`

```may
Array
```

Fixed length array type with element type T

**Example**
```may
let values: [Int; 3] = [1, 2, 3];
```

### `Never`

```may
Never
```

Type of an expression that cannot return normally

**Example**
```may
fun stop() -> Never { fail("stop"); }
```

### `Byte`

```may
Byte
```

Alias for UInt8

**Example**
```may
let byte: Byte = 255;
```

### `RawPtr`

```may
RawPtr
```

Alias for Ptr, used for untyped native addresses

**Example**
```may
let address: RawPtr = addr("data");
```

### `Option`

```may
Option
```

Alias for Optional<T>

**Example**
```may
let item: Option<Int> = nil;
```

### `F32`

```may
F32
```

Alias for Float32

**Example**
```may
let ratio: F32 = 0.5;
```

### `F64`

```may
F64
```

Alias for Float64

**Example**
```may
let ratio: F64 = 0.5;
```

### `Void`

```may
Void
```

Alias for Nil

**Example**
```may
fun finish() -> Void { return; }
```

### `Int`

```may
Int
```

A signed 61-bit integer used for whole numbers, indexes, and system call arguments.

**Example**
```may
let answer: Int = 42;
```

### `Float`

```may
Float
```

A 64-bit floating-point number.

**Example**
```may
let ratio: Float = 0.5;
```

### `Str`

```may
Str
```

A UTF-8 string. Indexing and len use Unicode character positions.

**Example**
```may
let greeting: Str = "hello";
```

### `Bool`

```may
Bool
```

A boolean value, either true or false.

**Example**
```may
let ready: Bool = true;
```

### `List`

```may
List<T>
```

An ordered mutable collection whose elements have type T.

**Example**
```may
let values: List<Int> = [1, 2, 3];
```

### `Map`

```may
Map<K, V>
```

A mutable key-value collection with key type K and value type V.

**Example**
```may
let names: Map<Str, Int> = {"Ada": 1};
```

### `Any`

```may
Any
```

A dynamic value that can hold any runtime type.

**Example**
```may
let value: Any = "dynamic";
```

### `Nil`

```may
Nil
```

The type of the absence value nil.

**Example**
```may
let missing: Nil = nil;
```

### `Ptr`

```may
Ptr
```

A raw memory address used by native operations and syscalls.

**Example**
```may
let address: Ptr = addr("data");
```

### `Optional`

```may
Optional<T>
```

A value of type T or nil.

**Example**
```may
let value: Optional<Int> = nil;
```

## Operators

### `??`

```may
value ?? fallback
```

Return the fallback only when the left value is `nil`. Values such as `0` and `false` are preserved.

**Example**
```may
print(false ?? true); // false
```

### `?.`

```may
value?.field
```

Access a field only if the receiver is present. A `nil` receiver yields `nil` instead of a field access failure.

**Example**
```may
let person: Any = nil;
print(person?.name ?? "anonymous");
```

### `|>`

```may
value |> function(extraArguments)
```

Pass the left value as the first argument of the function on the right. Pipelines can be chained.

**Example**
```may
print([1, 2, 3] |> map(|x: Any| -> Any { return x * 2; }) |> sum);
```

### `..`

```may
start..stop
```

An integer range with an exclusive upper endpoint, suitable for loops and comprehensions.

**Example**
```may
for i: Any in 0..3 { print(i); } // 0, 1, 2
```

### `..=`

```may
start..=stop
```

An integer range that includes its upper endpoint.

**Example**
```may
for i: Any in 1..=3 { print(i); } // 1, 2, 3
```

### `=>`

```may
parameter => expression
```

Separate a match pattern from its result. Legacy code also uses this for short lambdas; strict lambdas require typed parameters, a return type and an explicit return.

**Example**
```may
print(map([1, 2], |x: Any| -> Any { return x + 1; }));
```

### `->`

```may
fun name(...) -> Type { ... }
```

Declare the required return type of a named or anonymous function. Use explicit return statements in its body.

**Example**
```may
fun answer() -> Int { return 42 }
```

### `**`

```may
base ** exponent
```

Raise a number to a power. Integer and floating-point operands are supported by the native runtime.

**Example**
```may
print(2 ** 3); // 8
```

## Functions

### `print`

```may
print(values...)
```

Write values to standard output, separated by spaces, followed by a newline.

**Parameters**
- `values...`: Values to display, converted using runtime formatting.

**Returns:** Used for its output side effect; the native runtime currently produces zero.

**Example**
```may
print("answer:", 42);
```

### `len`

```may
len(value)
```

Count list elements, map entries, or Unicode characters in a string.

**Parameters**
- `value`: The string, list, or map to measure.

**Returns:** An integer count.

**Example**
```may
print(len("héllo")); // 5
```

### `str`

```may
str(value)
```

Convert a value to its textual representation.

**Parameters**
- `value`: The value to format.

**Returns:** A string.

**Example**
```may
print(str(42));
```

### `int`

```may
int(value)
```

Convert an integer, float, or decimal string to an integer. Floats are truncated toward zero; invalid text raises a catchable failure.

**Parameters**
- `value`: A number or a trimmed decimal string with optional sign.

**Returns:** An integer.

**Example**
```may
print(int(" 42 "));
print(int(3.9));
```

### `float`

```may
float(value)
```

Convert a number or numeric string to a floating-point value.

**Parameters**
- `value`: A number or numeric string.

**Returns:** A floating-point number.

**Example**
```may
print(float("3.5"));
```

### `to_float`

```may
to_float(value)
```

Convert a value using the native floating-point conversion helper.

**Parameters**
- `value`: The numeric value or string to convert.

**Returns:** A floating-point number.

**Example**
```may
print(to_float(3));
```

### `bool`

```may
bool(value)
```

Convert a value to its truth value. Only `nil` and `false` are false; zero, empty strings, and empty collections are true.

**Parameters**
- `value`: The value whose truthiness is tested.

**Returns:** `true` or `false`.

**Example**
```may
print(bool(0)); // true
```

### `push`

```may
push(xs, value)
```

Append one item to the existing list. All aliases of that list observe the mutation.

**Parameters**
- `xs`: The list to modify.
- `value`: The item to append.

**Returns:** The modified list.

**Example**
```may
let xs: Any = [1];
push(xs, 2);
print(xs);
```

### `pop`

```may
pop(xs)
```

Remove and return the last item of the existing list.

**Parameters**
- `xs`: The list to modify.

**Returns:** The removed item, or `nil` when empty.

**Example**
```may
let xs: Any = [1, 2];
print(pop(xs)); // 2
```

### `map`

```may
map(xs, f)
```

Call a function once for each list item and collect the returned values. The input list is preserved.

**Parameters**
- `xs`: The input list.
- `f`: A function taking one item and returning its replacement.

**Returns:** A new list of transformed values.

**Example**
```may
print(map([1, 2, 3], |x: Any| -> Any { return x * 2; }));
```

### `filter`

```may
filter(xs, f)
```

Collect input items for which the predicate returns the boolean `true`.

**Parameters**
- `xs`: The input list.
- `f`: A function taking one item and returning a boolean.

**Returns:** A new list containing matching items.

**Example**
```may
print(filter([1, 2, 3], |x: Any| -> Any { return x > 1; }));
```

### `reduce`

```may
reduce(xs, f, init)
```

Fold a list from left to right, passing the accumulator and current item to the function.

**Parameters**
- `xs`: The input list.
- `f`: A function taking (accumulator, item).
- `init`: The initial accumulator.

**Returns:** The final accumulator, or `init` for an empty list.

**Example**
```may
print(reduce([1, 2, 3], |acc: Any, x: Any| -> Any { return acc + x; }, 0));
```

### `sum`

```may
sum(xs)
```

Add the numeric values in a list.

**Parameters**
- `xs`: A list of numbers.

**Returns:** The total; zero for an empty list.

**Example**
```may
print(sum([1, 2, 3])); // 6
```

### `any`

```may
any(xs, f)
```

Test whether at least one item makes the predicate return `true`. Stop at the first match.

**Parameters**
- `xs`: The input list.
- `f`: A predicate returning a boolean.

**Returns:** A boolean; `false` for an empty list.

**Example**
```may
print(any([1, 2, 3], |x: Any| -> Any { return x > 2; }));
```

### `all`

```may
all(xs, f)
```

Test whether every item makes the predicate return `true`. Stop at the first nonmatching item.

**Parameters**
- `xs`: The input list.
- `f`: A predicate returning a boolean.

**Returns:** A boolean; `true` for an empty list.

**Example**
```may
print(all([1, 2, 3], |x: Any| -> Any { return x > 0; }));
```

### `min`

```may
min(a, b)
```

Return the lesser of two comparable values.

**Parameters**
- `a`: The first value.
- `b`: The second value.

**Returns:** One of the two values.

**Example**
```may
print(min(3, 8)); // 3
```

### `max`

```may
max(a, b)
```

Return the greater of two comparable values.

**Parameters**
- `a`: The first value.
- `b`: The second value.

**Returns:** One of the two values.

**Example**
```may
print(max(3, 8)); // 8
```

### `abs`

```may
abs(x)
```

Return the nonnegative magnitude of a number.

**Parameters**
- `x`: The input number.

**Returns:** A numeric absolute value.

**Example**
```may
print(abs(-4)); // 4
```

### `sort`

```may
sort(xs)
```

Return the items in ascending order using the standard comparison function. The input list is preserved.

**Parameters**
- `xs`: A list of comparable values.

**Returns:** A new sorted list.

**Example**
```may
print(sort([3, 1, 2]));
```

### `reverse`

```may
reverse(xs)
```

Build a list with the input items in reverse order.

**Parameters**
- `xs`: The input list.

**Returns:** A new list.

**Example**
```may
print(reverse([1, 2, 3]));
```

### `slice`

```may
slice(xs, start, stop)
```

Copy a contiguous section of a list. Bounds are clamped to the list length; the stop index is exclusive.

**Parameters**
- `xs`: The input list.
- `start`: The zero-based inclusive starting index.
- `stop`: The exclusive ending index.

**Returns:** A new list; empty if stop is not greater than start.

**Example**
```may
print(slice([10, 20, 30, 40], 1, 3)); // [20, 30]
```

### `keys`

```may
keys(m)
```

Collect the keys of a map.

**Parameters**
- `m`: The input map.

**Returns:** A list of keys.

**Example**
```may
print(keys({"a": 1}));
```

### `values`

```may
values(m)
```

Collect the values of a map.

**Parameters**
- `m`: The input map.

**Returns:** A list of values.

**Example**
```may
print(values({"a": 1}));
```

### `has`

```may
has(x, key)
```

Check for a map key, a matching list item, or a substring within a string.

**Parameters**
- `x`: The map, list, or string to search.
- `key`: The key, item, or substring to find.

**Returns:** A boolean.

**Example**
```may
print(has({"name": "Ada"}, "name"));
```

### `map_get`

```may
map_get(m, key)
```

Look up a map entry without changing the map.

**Parameters**
- `m`: The input map.
- `key`: The key to look up.

**Returns:** The stored value, or `nil` if missing.

**Example**
```may
print(map_get({"a": 1}, "a"));
```

### `map_set`

```may
map_set(m, key, value)
```

Insert or replace an entry in the existing map.

**Parameters**
- `m`: The map to modify.
- `key`: The key to assign.
- `value`: The value to store.

**Returns:** The assigned value.

**Example**
```may
let m: Any = {};
map_set(m, "a", 1);
print(m.a);
```

### `remove`

```may
remove(m, key)
```

Copy a map while omitting one key. The original map is preserved.

**Parameters**
- `m`: The input map.
- `key`: The key to omit.

**Returns:** A new map.

**Example**
```may
let m: Any = {"a": 1, "b": 2};
let smaller: Any = remove(m, "a");
```

### `merge`

```may
merge(a, b)
```

Combine two maps into a new map. Entries from the second map replace matching keys from the first.

**Parameters**
- `a`: The first map.
- `b`: The second map, which takes precedence.

**Returns:** A new combined map.

**Example**
```may
print(merge({"a": 1}, {"a": 2, "b": 3}));
```

### `read_file`

```may
read_file(path)
```

Read a file into a string. An I/O failure can be caught with `may` / `otherwise`.

**Parameters**
- `path`: The filesystem path to read.

**Returns:** The file contents as a string.

**Example**
```may
let text: Any = may { read_file("notes.txt") } otherwise { "" };
```

### `write_file`

```may
write_file(path, text)
```

Write a string to a file, creating it or replacing its existing contents. I/O failures are catchable.

**Parameters**
- `path`: The filesystem path to write.
- `text`: The contents to store.

**Returns:** `nil`.

**Example**
```may
write_file("notes.txt", "hello
");
```

### `read_dir`

```may
read_dir(path)
```

List names in a directory, excluding `.` and `..`. Names are relative to the supplied directory.

**Parameters**
- `path`: The directory to inspect.

**Returns:** A list of names; empty if the directory cannot be read.

**Example**
```may
print(read_dir("."));
```

### `file_exists`

```may
file_exists(path)
```

Test whether a filesystem path exists.

**Parameters**
- `path`: The file or directory path to test.

**Returns:** A boolean.

**Example**
```may
print(file_exists("notes.txt"));
```

### `json_parse`

```may
json_parse(s)
```

Decode a JSON string into Maylang strings, numbers, booleans, lists, maps, and `nil`.

**Parameters**
- `s`: The JSON text.

**Returns:** The decoded value.

**Example**
```may
let value: Any = json_parse("{\"name\":\"Ada\"}");
print(value.name);
```

### `json_stringify`

```may
json_stringify(v)
```

Encode a value as JSON text. Strings are quoted and escaped; lists and maps are encoded recursively.

**Parameters**
- `v`: The value to encode.

**Returns:** A JSON string.

**Example**
```may
print(json_stringify({"name": "Ada", "ready": true}));
```

### `input`

```may
input(prompt)
```

Display a prompt and read one line from standard input. The trailing newline is removed.

**Parameters**
- `prompt`: The text to display before reading; `nil` suppresses it.

**Returns:** A string, or `nil` at end of input.

**Example**
```may
let name: Any = input("Name: ");
```

### `read_stdin`

```may
read_stdin()
```

Read standard input until end of file. This waits for EOF, so it is suitable for piped data.

**Returns:** The collected input as a string.

**Example**
```may
let text: Any = read_stdin();
print(len(text));
```

### `clock`

```may
clock()
```

Read the wall clock as fractional seconds since the Unix epoch.

**Returns:** A floating-point timestamp.

This is a wall clock, so clock adjustments can change elapsed-time measurements.

**Example**
```may
let before: Any = clock();
print(clock() - before);
```

### `time`

```may
time()
```

Read the current Unix timestamp in milliseconds.

**Returns:** An integer timestamp in milliseconds.

**Example**
```may
print(time());
```

### `sleep`

```may
sleep(ms)
```

Pause the calling thread for a duration measured in milliseconds.

**Parameters**
- `ms`: The nonnegative duration in milliseconds.

**Returns:** `nil`.

**Example**
```may
sleep(100);
```

### `spawn`

```may
spawn(f)
```

Register a zero-argument function as a cooperative fiber. Call `run()` to execute scheduled fibers.

**Parameters**
- `f`: A zero-argument function to schedule.

**Returns:** A runtime fiber handle.

**Example**
```may
spawn(fun() -> Any { return print("worker"); });
run();
```

### `yield`

```may
yield()
```

Suspend the current cooperative fiber so another scheduled fiber can run. Outside a fiber it has no scheduling effect.

**Returns:** A runtime scheduling result.

**Example**
```may
spawn(fun() -> Any { print("first"); yield(); return print("again"); });
run();
```

### `run`

```may
run()
```

Execute scheduled cooperative fibers until they finish. Fibers yield explicitly with `yield()`.

**Returns:** A runtime scheduling result.

**Example**
```may
spawn(fun() -> Any { return print("hello"); });
run();
```

### `fail`

```may
fail(message)
```

Raise a runtime failure. A surrounding `may` block can catch it and access `err.message`.

**Parameters**
- `message`: The failure description.

**Returns:** Does not return normally.

**Example**
```may
may { fail("bad input"); } otherwise { print(err.message); };
```

### `exit`

```may
exit(status)
```

Terminate the process with an exit status. Zero conventionally indicates success.

**Parameters**
- `status`: The process exit code.

**Returns:** Does not return.

**Example**
```may
exit(0);
```

### `syscall`

```may
syscall(number, arguments...)
```

Invoke a Linux system call directly, with up to six integer arguments. This bypasses normal file and memory helpers.

**Parameters**
- `number`: The Linux x86-64 syscall number.
- `arguments...`: Raw integer arguments in syscall order.

**Returns:** The raw integer result; failures usually return a negative errno.

**Example**
```may
let pid: Any = syscall(39); // Linux getpid
```

### `addr`

```may
addr(s)
```

Return the address of a string’s UTF-8 bytes. Keep the string alive while using the address.

**Parameters**
- `s`: The string whose byte storage is addressed.

**Returns:** An integer address.

**Example**
```may
let s: Any = "abc";
print(load8(addr(s))); // 97
```

### `cstr`

```may
cstr(s)
```

Create a NUL-terminated representation of a string for a native API.

**Parameters**
- `s`: The string to pass to native code.

**Returns:** An integer address to NUL-terminated bytes.

**Example**
```may
let path: Any = cstr("notes.txt");
```

### `load8`

```may
load8(p)
```

Read 8 bits from a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid readable address with enough remaining bytes.

**Returns:** The loaded integer value.

**Example**
```may
let s: Any = "abcdefgh";
let value: Any = load8(addr(s));
```

### `store8`

```may
store8(p, value)
```

Write 8 bits to a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid writable address with enough remaining bytes.
- `value`: The integer bits to write.

**Returns:** A raw runtime result.

**Example**
```may
// p must refer to writable allocated memory.
store8(p, 0);
```

### `load16`

```may
load16(p)
```

Read 16 bits from a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid readable address with enough remaining bytes.

**Returns:** The loaded integer value.

**Example**
```may
let s: Any = "abcdefgh";
let value: Any = load16(addr(s));
```

### `store16`

```may
store16(p, value)
```

Write 16 bits to a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid writable address with enough remaining bytes.
- `value`: The integer bits to write.

**Returns:** A raw runtime result.

**Example**
```may
// p must refer to writable allocated memory.
store16(p, 0);
```

### `load32`

```may
load32(p)
```

Read 32 bits from a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid readable address with enough remaining bytes.

**Returns:** The loaded integer value.

**Example**
```may
let s: Any = "abcdefgh";
let value: Any = load32(addr(s));
```

### `store32`

```may
store32(p, value)
```

Write 32 bits to a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid writable address with enough remaining bytes.
- `value`: The integer bits to write.

**Returns:** A raw runtime result.

**Example**
```may
// p must refer to writable allocated memory.
store32(p, 0);
```

### `load64`

```may
load64(p)
```

Read 64 bits from a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid readable address with enough remaining bytes.

**Returns:** The loaded integer value.

**Example**
```may
let s: Any = "abcdefgh";
let value: Any = load64(addr(s));
```

### `store64`

```may
store64(p, value)
```

Write 64 bits to a raw memory address. This operation performs no bounds or lifetime checks.

**Parameters**
- `p`: A valid writable address with enough remaining bytes.
- `value`: The integer bits to write.

**Returns:** A raw runtime result.

**Example**
```may
// p must refer to writable allocated memory.
store64(p, 0);
```

### `ccall`

```may
ccall(fn, args)
```

Call machine code at a raw address with up to six integer arguments using the native calling convention.

**Parameters**
- `fn`: The native function address.
- `args`: A list of at most six integer arguments.

**Returns:** The native integer return value.

**Example**
```may
// fn must be a valid native function address.
let result: Any = ccall(fn, [1, 2]);
```

### `extern_c`

```may
extern_c(fn)
```

Wrap a native function address as a callable Maylang function accepting six integer arguments.

**Parameters**
- `fn`: The native function address.

**Returns:** A callable wrapper.

**Example**
```may
// fn must be a valid native function address.
let call: Any = extern_c(fn);
let result: Any = call(1, 2, 0, 0, 0, 0);
```

### `sqrt`

```may
sqrt(x)
```

Compute a number’s square root.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** A floating-point result.

**Example**
```may
print(sqrt(9.0));
```

### `floor`

```may
floor(x)
```

Round a number down to an integer-valued numeric result.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** The rounded value.

**Example**
```may
print(floor(2.9));
```

### `ceil`

```may
ceil(x)
```

Round a number up to an integer-valued numeric result.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** The rounded value.

**Example**
```may
print(ceil(2.1));
```

### `sin`

```may
sin(x)
```

Compute the sine of an angle in radians.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** A floating-point result.

**Example**
```may
print(sin(0.0));
```

### `cos`

```may
cos(x)
```

Compute the cosine of an angle in radians.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** A floating-point result.

**Example**
```may
print(cos(0.0));
```

### `tan`

```may
tan(x)
```

Compute the tangent of an angle in radians.

**Parameters**
- `x`: The number to evaluate; trigonometric angles use radians.

**Returns:** A floating-point result.

**Example**
```may
print(tan(0.0));
```

### `env`

```may
env(name)
```

Look up an environment variable in the current process.

**Parameters**
- `name`: The environment variable name.

**Returns:** The variable’s string value, or `nil` if missing.

**Example**
```may
print(env("HOME") ?? "unset");
```

### `args`

```may
args()
```

Read the process’s command-line arguments, including the executable name as the first item.

**Returns:** A list of argument strings.

**Example**
```may
print(args());
```

### `substring`

```may
substring(s, start, count)
```

Copy a section of a string using Unicode character indices. The third argument is a count, not an ending index.

**Parameters**
- `s`: The input string.
- `start`: The zero-based starting character index.
- `count`: The number of characters to copy.

**Returns:** A string.

**Example**
```may
print(substring("hello", 1, 3)); // ell
```

### `split`

```may
split(s, sep)
```

Separate a string at occurrences of a separator.

**Parameters**
- `s`: The input string.
- `sep`: The separator string.

**Returns:** A list of string segments.

**Example**
```may
print(split("a,b,c", ","));
```

### `join`

```may
join(xs, sep)
```

Convert items to strings and combine them with a separator between neighboring items.

**Parameters**
- `xs`: The values to combine.
- `sep`: The text inserted between items.

**Returns:** The combined string.

**Example**
```may
print(join(["a", "b"], ","));
```

### `trim`

```may
trim(s)
```

Remove whitespace from the beginning and end of a string.

**Parameters**
- `s`: The input string.

**Returns:** A string.

**Example**
```may
print(trim("  hello  "));
```

### `repeat`

```may
repeat(s, n)
```

Concatenate copies of a string.

**Parameters**
- `s`: The string to repeat.
- `n`: The nonnegative number of copies.

**Returns:** The repeated string.

**Example**
```may
print(repeat("ab", 3)); // ababab
```

### `range`

```may
range(a, b)
```

Build a list of consecutive integers from the start up to, but excluding, the stop value.

**Parameters**
- `a`: The inclusive starting value.
- `b`: The exclusive stop value.

**Returns:** A list of integers.

**Example**
```may
print(range(1, 4)); // [1, 2, 3]
```

### `err`

```may
err
```

The error object available inside an `otherwise` recovery block.

**Returns:** Fields include `kind`, `message`, and `stack`.

**Example**
```may
may { fail("oops"); } otherwise { print(err.kind, err.message); };
```
