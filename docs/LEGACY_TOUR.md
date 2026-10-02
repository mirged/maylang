# Historical language tour

These examples describe the archived Rust implementation and legacy syntax.
For the active self-hosted compiler, use [the strict guide](STRICT.md).

## Language tour (legacy syntax)

### Values and types
`nil`, `Bool`, `Int` (61-bit immediate), `Float` (64-bit), `Str`, `List`,
`Map`, and functions (closures). Type hints are optional and informational at
runtime, but `maylang check` infers and verifies them. Parametric hints,
return types and generic functions are supported:

```may
let x: Int = 10;
let xs: List<Int> = [1, 2, 3];
let m: Map<Str, Int> = {"a": 1};
fun head<T>(items: List<T>) -> T { items[0] }
fun compose<A, B, C>(f: (A) -> B, g: (B) -> C) -> (A) -> C { |x| g(f(x)) }
```

### Bindings
```may
let immutable = 1;
mut counter = 0;
counter += 1;          // compound assignments: += -= *= /=
let {x, y} = point;          // record destructuring ({x: px} renames)
let [first, second] = pair;  // list destructuring
let {pos: [px, py]} = obj;   // patterns nest
for [k, v] in pairs { .. }   // destructuring loop bindings
```

### Expression-oriented control flow
`if`, blocks and `may` all yield values; condition parentheses are optional:
```may
let label = if n > 0 { "positive" } else { "non-positive" };
```

### Loops
```may
while running { .. }
for item in 1..=10 { .. }      // ranges (ascending or descending), lists, strings
break; continue;
```

### Functions and closures
```may
fun adder(n) {
    fun add(x) { x + n }   // captures `n`
    add
}
let add5 = adder(5);
print(add5(10)); // 15
```

Anonymous functions come in three spellings:
`fun(x) { x * x }`, `|x| x * x`, and `x => x * x`.

### User-defined types
`struct` declares a record type and `enum` a sum type; both desugar to
constructor functions returning tagged maps, so fields are accessed with `.`
and the usual map built-ins work:

```may
struct Point { x: Float, y: Float }
let p = Point(3.0, 4.0);
print(p.x, p.y, len(p));   // 3.0 4.0 2

enum Shape { Circle(r), Rect(w, h), Empty }
fun area(s) {
    match (s.tag) {          // variants carry a "tag" field
        "Circle" => 3.14159 * s.r * s.r,
        "Rect"   => s.w * s.h,
        _        => 0.0,
    }
}
```

A `struct` may carry **fixed members**, including methods named after operators
(string keys are not constructor parameters). Arithmetic operators dispatch to
the left operand's method, which is called as `method(self, other)`:

```may
fun vadd(self, other) { V(self.x + other.x, self.y + other.y) }
struct V { x, y, "+": vadd }
let c = V(1, 2) + V(3, 4);   // V(4, 6)
```

### Pattern matching (legacy tour)
```may
let label = match (status) {
    200 => "OK",
    404 => "Missing",
    n if n >= 500 => "Server error",
    _   => "Unknown",
};
```

### Strings, collections, spread and comprehensions
```may
print("total: ${n}, status: ${status}");   // interpolation
print(2 ** 10);                            // exponentiation
let xs = [1, 2, ...rest, 5];               // spread
let cfg = {...defaults, dev: true};        // map merge, later keys win
let evens = [x * 2 for x in 1..=10 if x % 2 == 0];
"  hi ".trim().to_upper();
"a,b,c".split(",");
any(nums, |x| x > 0); all(nums, x => x > 0);
```

### The `may` boundary and safe fallbacks
```may
let r = may { 10 / 0 } otherwise { print("oops: ${err.kind}"); 0 };
let maybe = may { risky() };      // bare: nil on fault
let port = (may { int(s) }) ?? 8080;
print(user?.profile?.email);      // nil, never a fault
```

### Results and `?`
`Ok`/`Err` (and `Some`/`None`, where `None` is `nil`) build ordinary
`{ok, value, error}` results. Postfix `?` unwraps a success or **returns the
failure from the enclosing function**, so fallible code reads linearly:

```may
fun safe_div(a, b) { if (b == 0) { return Err("division by zero"); } Ok(a / b) }
fun compute(a, b) {
    let q = safe_div(a, b)?;   // propagates Err upward
    Ok(q + 100)
}
print(compute(10, 2).value);   // 105
compute(10, 0).error;          // "division by zero"
```

### Concurrency (cooperative fibers)
`spawn` starts a zero-argument function on its own stack; `run` drains the
ready fibers with a round-robin scheduler, and `yield` hands control to the
next fiber. Fibers share the heap, and the collector scans every fiber stack.

```may
fun worker(id) {
    mut i = 0;
    while (i < 3) { print("fiber", id, i); yield(); i = i + 1; }
}
spawn(fun() { worker(1) });
spawn(fun() { worker(2) });
run();   // interleaves the two workers
```

### JSON, files and time
```may
let doc = json_parse(read_file("data.json"));
print(doc.name, doc.items |> sum);
write_file("out.json", json_stringify(doc));
file_exists("out.json");
clock();  // Unix epoch seconds (Float); time() gives milliseconds (Int)
```

### Directories and subprocesses
```may
mkdir("build");                       // 0755; raises an `io` fault on failure
for name in read_dir("src") { print(name); }
system("maylang build -o app main.may");   // /bin/sh -c, returns exit status
let pid = exec(["git", "status"]);         // fork + execve, returns the pid
wait(pid);                                 // blocks, returns the exit status
sleep(250);                                // milliseconds
```
`read_dir` uses `getdents64` (Linux); `exec` inherits the environment captured
at `_start`, and argument vectors live in demand-zero BSS scratch so they never
move before `execve`.

### The Sovereign Trio: raw pointers, syscalls and the C ABI
```may
let s = "hello";
let a = addr(s);              // pointer to the bytes (length at addr - 8)
load8(a); load16(a); load32(a); load64(a);
store8(a, 0); store64(a + 8, 42);

// any system call, with any number of arguments (passed raw):
let page = syscall(9, 0, 4096, 7, 34, 0 - 1, 0);   // mmap(..., PROT_RWX, ...)
syscall(1, 1, addr("hi\n"), 3);                     // write(1, "hi\n", 3)

// call machine code at an address with the System V C ABI:
let r = ccall(page, [40, 2]);      // integer/pointer arguments
let f = extern_c(page);            // wrap as a callable value
f(19, 23);
```
A pointer is just an `Int` whose numeric value is an address, so `+`/`-` are
pointer arithmetic. `addr` returns the payload address of a string, list, map
or float (0 for immediates); `cstr` returns a NUL-terminated copy for C. The
first six arguments of `ccall`/`extern_c` are passed in registers and untagged;
floats in `xmm` and stack arguments are not yet wired up. `syscall` takes the
call number followed by any number of untagged integer arguments.

### Modules
```may
import "util.may";              // names available unqualified, and as util.name
import "util" as u;             // only u.name
from "util" import square, TAU; // only the listed names, unqualified
```
Imports are resolved and inlined at **build time**, but every top-level name is
rewritten to a unique `namespace::name`, so modules no longer share one global
namespace and duplicate names in different modules no longer silently collide.
Two plain imports that export the same unqualified name are a compile error;
use `as` to disambiguate. Visibility is opt-in: a module that marks any
top-level declaration `pub` exports **only** its `pub` names (unmarked ones are
private); a module with no `pub` at all exports everything, for compatibility.
The loader searches the importing
file's directory and then the stdlib path (`$MAYLANG_STDLIB`, `./stdlib`,
`~/.maylang/stdlib`, …). `stdlib/prelude.may` is auto-loaded
(`MAYLANG_NO_PRELUDE=1` disables it).

### Native compilation (ELF / Mach-O)
```sh
maylang build -o prog app.may              # host target
maylang build --target macos -o prog app.may
```
`may_native` emits **raw x86-64 machine code** and wraps it in a freestanding
executable — no assembler, linker, libc or dynamic loader. Values are 64-bit
tagged words; strings, maps and lists are heap objects in the same loadable
segment; `print` uses the `write` syscall directly. `maylang build` resolves and
inlines `import`ed modules at build time, prepends a Maylang-native prelude, and
compiles the result into a single executable.

### Garbage collection
The native runtime has a **conservative, non-moving mark-sweep collector**. Every
allocation has a small header; blocks are freed by a first-fit allocator that
splits and coalesces, and after each collection the free list is rebuilt and the
bump pointer is rewound past the last live block. The heap is a 1 GiB
demand-zero `mmap` reservation that is **not stored in the executable**, and
only touched pages consume physical memory — so long-running, allocation-heavy
programs (like `examples/game.may`) run without leaking. See
[`GC.md`](docs/GC.md).

### Standard library
`stdlib/` contains Maylang modules — `math`, `string`, `collections` (stack,
queue, set), `algo` (sorts, search, `zip`/`chunk`/`partition`/`group_by`),
`functional` (compose/curry/memoize/pipeline), `result`, `test` — with native
built-ins for transcendental math, file I/O, JSON, `env`, `time` and `exit`.
See [`stdlib/README.md`](stdlib/README.md).

### Collections and built-ins
`print`, `str`, `int`, `float`, `bool`, `type`, `len`, `push`, `pop`, `range`,
`keys`, `values`, `has`, `merge`, `remove`, `map`, `filter`, `reduce`, `any`,
`all`, `abs`, `min`, `max`, `clamp`, `sqrt`, `floor`, `ceil`, `round`, `trunc`,
`sign`, `pow`, `assert`, `assert_eq`, `fail`, `clock`, `time`, `input`, `args`, `join`,
`sort`, `reverse`, `sum`, `product`, `count`, `find`, `slice`, `enumerate`,
`zip`, `flatten`, `unique`, `range_step`, `pad_left`, `pad_right`, `split_lines`,
`get`, `times`, `each`, `chr`, `ord`, `even`, `odd`, `env`, `exit`,
`spawn`, `yield`, `run`,
`parse_int`, `parse_float`, `split`, `trim`, `to_upper`, `to_lower`,
`contains`, `starts_with`, `ends_with`, `replace`, `index_of`, `chars`,
`read_file`, `write_file`, `file_exists`, `mkdir`, `read_dir`,
`exec`, `wait`, `system`, `sleep`, `syscall`,
`ptr`, `addr`, `cstr`, `load8`, `load16`, `load32`, `load64`,
`store8`, `store16`, `store32`, `store64`, `ccall`, `extern_c`,
`json_parse`, `json_stringify`,
and the x87 transcendentals `sin`, `cos`, `tan`, `asin`, `acos`, `atan`,
`atan2`, `sinh`, `cosh`, `tanh`, `ln`, `log2`, `log10`, `exp`, `hypot`, `cbrt`,
`pi`, `e`.

### Comments
`// line` and nested `/* block */`.
