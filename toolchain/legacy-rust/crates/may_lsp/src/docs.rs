//! Hover documentation for keywords and built-ins.
//!
//! These tables back the "full docs on hover" experience for names that have no
//! source definition (keywords and native/prelude built-ins). Functions defined
//! in a project — including the standard library, which is written in Maylang —
//! are documented from their own source instead.

pub struct Doc {
    pub signature: &'static str,
    pub description: &'static str,
    pub example: &'static str,
}

const fn doc(signature: &'static str, description: &'static str, example: &'static str) -> Doc {
    Doc {
        signature,
        description,
        example,
    }
}

/// Markdown for a keyword, or `None`.
pub fn keyword_markdown(name: &str) -> Option<String> {
    KEYWORDS.iter().find(|(k, _)| *k == name).map(|(_, d)| render(d))
}

/// Markdown for a built-in, or `None`.
pub fn builtin_markdown(name: &str) -> Option<String> {
    BUILTINS.iter().find(|(k, _)| *k == name).map(|(_, d)| render(d))
}

/// The signature of a documented built-in, if any.
pub fn builtin_signature(name: &str) -> Option<&'static str> {
    BUILTINS
        .iter()
        .find(|(k, _)| *k == name)
        .map(|(_, d)| d.signature)
}

pub fn is_keyword(name: &str) -> bool {
    KEYWORDS.iter().any(|(k, _)| *k == name)
}

pub fn keyword_names() -> Vec<&'static str> {
    KEYWORDS.iter().map(|(k, _)| *k).collect()
}

pub fn builtin_names() -> Vec<&'static str> {
    BUILTINS.iter().map(|(k, _)| *k).collect()
}

/// The parameter list of a signature (`fun f(a, b)` → `["a", "b"]`), if any.
pub fn signature_params(signature: &str) -> Vec<String> {
    let open = match signature.find('(') {
        Some(i) => i,
        None => return Vec::new(),
    };
    let close = match signature[open..].find(')') {
        Some(i) => open + i,
        None => return Vec::new(),
    };
    split_top_level(&signature[open + 1..close])
}

fn split_top_level(inner: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut current = String::new();
    for c in inner.chars() {
        match c {
            '(' | '[' | '<' | '{' => {
                depth += 1;
                current.push(c);
            }
            ')' | ']' | '>' | '}' => {
                depth -= 1;
                current.push(c);
            }
            ',' if depth == 0 => {
                let trimmed = current.trim();
                if !trimmed.is_empty() {
                    out.push(trimmed.to_string());
                }
                current.clear();
            }
            _ => current.push(c),
        }
    }
    let trimmed = current.trim();
    if !trimmed.is_empty() {
        out.push(trimmed.to_string());
    }
    out
}

fn render(d: &Doc) -> String {
    let mut out = format!("```maylang\n{}\n```\n{}", d.signature, d.description);
    if !d.example.is_empty() {
        out.push_str(&format!("\n\n```maylang\n{}\n```", d.example));
    }
    out
}

const KEYWORDS: &[(&str, Doc)] = &[
    ("fun", doc("fun name(params) { body }", "Declare a named function. Anonymous functions use `fun(x) { .. }`, `|x| expr`, or `x => expr`.", "fun add(a, b) { a + b }\nlet inc = |x| x + 1;")),
    ("let", doc("let name = value;", "Bind an immutable name. Supports type hints and destructuring patterns.", "let x: Int = 10;\nlet {a, b} = point;")),
    ("mut", doc("mut name = value;", "Bind a mutable name. Compound assignments (`+=`, `-=`, `*=`, `/=`) are available.", "mut count = 0;\ncount += 1;")),
    ("if", doc("if cond { .. } else { .. }", "Conditional expression; the condition parentheses are optional and `if` yields a value. Chain with `else if`.", "let label = if n > 0 { \"pos\" } else { \"non-pos\" };")),
    ("else", doc("if cond { .. } else { .. }", "Alternative branch of an `if` (or `else if`).", "if ready { go(); } else { wait(); }")),
    ("unless", doc("unless cond { .. }", "Inverted guard: runs the body when the condition is false. Useful for early exits.", "unless (len(xs) > 0) return nil;")),
    ("while", doc("while cond { .. }", "Loop while the condition is truthy.", "mut i = 0;\nwhile (i < 10) { i += 1; }")),
    ("for", doc("for item in iterable { .. }", "Iterate a range, list, string, or a map's keys. The binding may destructure.", "for x in 1..=10 { print(x); }")),
    ("in", doc("for item in iterable", "Introduces the iterable of a `for` loop or a list comprehension.", "for [k, v] in pairs { print(k, v); }")),
    ("return", doc("return value;", "Return early from a function; without a value it returns `nil`.", "fun f(x) { if (x < 0) return 0; x * 2 }")),
    ("break", doc("break;", "Exit the innermost loop.", "while true { if done { break; } }")),
    ("continue", doc("continue;", "Skip to the next iteration of the innermost loop.", "for x in xs { if x == 0 { continue; } use(x); }")),
    ("match", doc("match value { pattern => result, .. }", "Pattern-match a value. Arms support literals, bindings, and `if` guards; `_` is the wildcard.", "match code {\n    200 => \"OK\",\n    n if n >= 500 => \"Server error\",\n    _ => \"Unknown\",\n}")),
    ("import", doc("import \"module.may\";\nimport \"module\" as ns;", "Import a module. Plain imports bring names in unqualified; `as` exposes them under a namespace.", "import \"util.may\";\nimport \"math.may\" as math;")),
    ("from", doc("from \"module\" import a, b;", "Import only the listed names from a module, unqualified.", "from \"util\" import square, TAU;")),
    ("as", doc("import \"m\" as ns;", "Namespace alias for an import, accessed as `ns.name`.", "import \"math.may\" as math;\nmath.gcd(48, 36);")),
    ("pub", doc("pub fun name(..) { .. }", "Mark a top-level declaration as exported. Once a module uses `pub`, only `pub` names are visible to importers.", "pub fun greet(name) { \"hi \" + name }")),
    ("struct", doc("struct Name { field, field: Type, \"method\": expr }", "Declare a record type, desugared to a constructor returning a tagged map with mutable fields.", "struct Point { x, y }\nlet p = Point(3, 4);\np.x;")),
    ("enum", doc("enum Name { A, B(x, y) }", "Declare a sum type. Variants become constructors returning maps with a `tag` field; match on `value.tag`.", "enum Shape { Circle(r), Empty }\nlet c = Circle(2.0);\nc.tag;")),
    ("true", doc("true", "Boolean literal.", "let ok = true;")),
    ("false", doc("false", "Boolean literal.", "let ok = false;")),
    ("nil", doc("nil", "The absence of a value. `x ?? fallback` and `a?.b` guard against it.", "let missing = nil;\nprint(missing ?? \"default\");")),
    ("may", doc("may { risky } otherwise { safe }", "Speculative execution. With `otherwise` a fault runs the fallback; bare, a fault yields `nil`. The handler sees a structured `err`.", "let port = (may { int(s) }) ?? 8080;")),
    ("otherwise", doc("may { .. } otherwise { .. }", "Fallback block for `may`. Inside it, `err.kind`, `err.message` and `err.stack` describe the fault.", "may { 1 / 0 } otherwise { print(err.kind); 0 };")),
    ("and", doc("a and b   // also &&", "Logical AND; short-circuits.", "if (x > 0 and y > 0) { .. }")),
    ("or", doc("a or b   // also ||", "Logical OR; short-circuits.", "let name = input or \"anonymous\";")),
    ("not", doc("not x   // also !x", "Logical negation.", "if (not ready) { wait(); }")),
];

const BUILTINS: &[(&str, Doc)] = &[
    ("print", doc("print(a, b, ...)", "Print values separated by a space, followed by a newline.", "print(\"total:\", 42);")),
    ("str", doc("str(value) -> Str", "Convert a value to its string representation.", "str(123) + \"!\"")),
    ("int", doc("int(value) -> Int", "Convert to an integer. `int(\"12\")` parses; a bad string faults (catch with `may`).", "(may { int(s) }) ?? 0")),
    ("float", doc("float(value) -> Float", "Convert to a float.", "float(3) / 2")),
    ("bool", doc("bool(value) -> Bool", "Convert to a boolean (truthiness).", "bool(1)")),
    ("type", doc("type(value) -> Str", "The runtime type name: `Int`, `Float`, `Str`, `Bool`, `Nil`, `List`, `Map`.", "type([]) == \"List\"")),
    ("len", doc("len(value) -> Int", "Number of codepoints in a string, elements in a list, or entries in a map.", "len(\"hello\")")),
    ("push", doc("push(list, value) -> List", "Append to a list in place and return it.", "mut xs = []; push(xs, 1);")),
    ("pop", doc("pop(list) -> value", "Remove and return the last element, or `nil` when empty.", "pop([1, 2, 3])")),
    ("range", doc("range(end) / range(start, end)", "Build a list of integers `0..end` or `start..end`.", "range(3) == [0, 1, 2]")),
    ("keys", doc("keys(map) -> List", "The keys of a map.", "keys({\"a\": 1})")),
    ("values", doc("values(map) -> List", "The values of a map.", "values({\"a\": 1})")),
    ("has", doc("has(container, key) -> Bool", "Membership: map key, list element, or substring.", "has({\"a\": 1}, \"a\")")),
    ("merge", doc("merge(a, b) -> Map", "Shallow-merge two maps; later keys win.", "merge({\"a\": 1}, {\"b\": 2})")),
    ("remove", doc("remove(map, key) -> Map", "Return a copy of a map without `key`.", "remove({\"a\": 1}, \"a\")")),
    ("map", doc("map(list, f) -> List", "Apply `f` to every element.", "map([1, 2, 3], |x| x * x)")),
    ("filter", doc("filter(list, pred) -> List", "Keep the elements for which `pred` is truthy.", "filter([1, 2, 3, 4], |x| x % 2 == 0)")),
    ("reduce", doc("reduce(list, f, init) -> value", "Fold left: `f(acc, x)` for each element.", "reduce([1, 2, 3], |a, b| a + b, 0)")),
    ("any", doc("any(list, pred) -> Bool", "True when `pred` holds for at least one element.", "any([1, 2, 3], |x| x > 2)")),
    ("all", doc("all(list, pred) -> Bool", "True when `pred` holds for every element.", "all([1, 2, 3], |x| x > 0)")),
    ("sort", doc("sort(list) -> List", "Return a naturally sorted copy (comparison-based, stable).", "sort([3, 1, 2])")),
    ("reverse", doc("reverse(list|str) -> same", "Reverse a list or string.", "reverse([1, 2, 3])")),
    ("sum", doc("sum(list) -> number", "Sum of a numeric list.", "sum([1, 2, 3])")),
    ("product", doc("product(list) -> number", "Product of a numeric list.", "product([2, 3, 4])")),
    ("count", doc("count(list, value) -> Int", "Occurrences of `value` in `list`.", "count([1, 1, 2], 1)")),
    ("find", doc("find(list, pred) -> value", "First element satisfying `pred`, or `nil`.", "find([1, 2, 3], |x| x > 1)")),
    ("slice", doc("slice(list|str, start, end)", "Sub-sequence `[start, end)`; on strings returns the characters.", "slice([10, 20, 30], 1, 3)")),
    ("enumerate", doc("enumerate(list) -> List", "Pairs of `[index, value]`.", "enumerate([\"a\", \"b\"])")),
    ("zip", doc("zip(a, b) -> List", "Pairs of corresponding elements.", "zip([1, 2], [\"a\", \"b\"])")),
    ("flatten", doc("flatten(list_of_lists) -> List", "One level of flattening.", "flatten([[1], [2, 3]])")),
    ("unique", doc("unique(list) -> List", "Remove duplicates, preserving order.", "unique([1, 1, 2])")),
    ("range_step", doc("range_step(start, end, step) -> List", "Arithmetic sequence.", "range_step(0, 10, 2)")),
    ("pad_left", doc("pad_left(s, width, pad)", "Left-pad a string to `width`.", "pad_left(\"7\", 3, \"0\")")),
    ("pad_right", doc("pad_right(s, width, pad)", "Right-pad a string to `width`.", "pad_right(\"x\", 3, \".\")")),
    ("split_lines", doc("split_lines(s) -> List", "Split on newlines.", "split_lines(\"a\\nb\")")),
    ("get", doc("get(map, key, default)", "Map lookup with a default.", "get({\"a\": 1}, \"b\", 0)")),
    ("times", doc("times(n, f)", "Call `f(i)` for `i` in `0..n`.", "times(3, |i| print(i))")),
    ("each", doc("each(list, f)", "Call `f(x)` for each element for its side effect.", "each([1, 2], |x| print(x))")),
    ("chr", doc("chr(code) -> Str", "Unicode codepoint to a one-character string.", "chr(65) == \"A\"")),
    ("ord", doc("ord(s) -> Int", "First codepoint of a string.", "ord(\"A\") == 65")),
    ("even", doc("even(n) -> Bool", "True when `n` is even.", "even(4)")),
    ("odd", doc("odd(n) -> Bool", "True when `n` is odd.", "odd(3)")),
    ("abs", doc("abs(x) -> number", "Absolute value.", "abs(-3)")),
    ("min", doc("min(a, b) -> number", "Smaller of two values.", "min(3, 5)")),
    ("max", doc("max(a, b) -> number", "Larger of two values.", "max(3, 5)")),
    ("clamp", doc("clamp(x, lo, hi) -> number", "Restrict `x` to `[lo, hi]`.", "clamp(15, 0, 10)")),
    ("sqrt", doc("sqrt(x) -> Float", "Square root.", "sqrt(2.0)")),
    ("floor", doc("floor(x) -> Int", "Round down.", "floor(2.7)")),
    ("ceil", doc("ceil(x) -> Int", "Round up.", "ceil(2.1)")),
    ("round", doc("round(x) -> Int", "Round to the nearest integer.", "round(2.5)")),
    ("trunc", doc("trunc(x) -> Int", "Drop the fractional part.", "trunc(2.9)")),
    ("sign", doc("sign(x) -> Int", "`-1`, `0` or `1`.", "sign(-9)")),
    ("pow", doc("pow(base, exp) -> Float", "Power; `a ** b` is the operator form.", "pow(2.0, 10.0)")),
    ("assert", doc("assert(cond)", "Fault when `cond` is falsy.", "assert(len(xs) > 0)")),
    ("assert_eq", doc("assert_eq(a, b)", "Fault when `a != b`.", "assert_eq(add(2, 2), 4)")),
    ("fail", doc("fail(message)", "Raise a structured fault; catch it with `may ... otherwise`.", "may { fail(\"boom\") } otherwise { 0 }")),
    ("clock", doc("clock() -> Float", "Unix epoch seconds.", "clock()")),
    ("time", doc("time() -> Int", "Unix epoch milliseconds.", "time()")),
    ("input", doc("input([prompt]) -> Str", "Read a line from stdin (returns `nil` at EOF).", "input(\"name> \")")),
    ("args", doc("args() -> List", "The process command-line arguments.", "args()")),
    ("env", doc("env(name) -> Str", "Environment variable value, or `nil`.", "env(\"HOME\")")),
    ("exit", doc("exit(code)", "Terminate the process.", "exit(0)")),
    ("split", doc("s.split(sep) -> List", "Split a string by a separator.", "\"a,b,c\".split(\",\")")),
    ("trim", doc("s.trim() -> Str", "Strip leading and trailing whitespace.", "\"  hi \".trim()")),
    ("to_upper", doc("s.to_upper() -> Str", "Uppercase a string.", "\"hi\".to_upper()")),
    ("to_lower", doc("s.to_lower() -> Str", "Lowercase a string.", "\"HI\".to_lower()")),
    ("contains", doc("s.contains(sub) -> Bool", "Substring test.", "\"hello\".contains(\"ell\")")),
    ("starts_with", doc("s.starts_with(prefix) -> Bool", "Prefix test.", "\"file.may\".starts_with(\"file\")")),
    ("ends_with", doc("s.ends_with(suffix) -> Bool", "Suffix test.", "\"file.may\".ends_with(\".may\")")),
    ("replace", doc("s.replace(from, to) -> Str", "Replace every occurrence.", "\"a-b\".replace(\"-\", \"+\")")),
    ("index_of", doc("index_of(haystack, needle) -> Int", "First index of `needle`, or `-1`.", "index_of(\"a.b\", \".\")")),
    ("chars", doc("chars(s) -> List", "The codepoints of a string as one-character strings.", "chars(\"ab\")")),
    ("parse_int", doc("parse_int(s) -> Int", "Parse an integer.", "parse_int(\"42\")")),
    ("parse_float", doc("parse_float(s) -> Float", "Parse a float.", "parse_float(\"3.5\")")),
    ("read_file", doc("read_file(path) -> Str", "Read a file (faults on error).", "read_file(\"data.txt\")")),
    ("write_file", doc("write_file(path, content)", "Write a file.", "write_file(\"out.txt\", \"hi\")")),
    ("file_exists", doc("file_exists(path) -> Bool", "Whether a path exists.", "file_exists(\"out.txt\")")),
    ("mkdir", doc("mkdir(path)", "Create a directory (mode 0755); faults on failure.", "may { mkdir(\"build\"); } otherwise { nil };")),
    ("read_dir", doc("read_dir(path) -> List", "Directory entry names, excluding `.` and `..` (Linux).", "read_dir(\"src\")")),
    ("exec", doc("exec(argv) -> Int", "`fork` + `execve`; returns the child pid.", "let pid = exec([\"git\", \"status\"]);")),
    ("wait", doc("wait(pid) -> Int", "Block for a child and return its exit status.", "wait(pid)")),
    ("system", doc("system(command) -> Int", "Run `command` via `/bin/sh -c` and return its status.", "system(\"maylang build -o app main.may\")")),
    ("sleep", doc("sleep(ms)", "Block for `ms` milliseconds.", "sleep(250)")),
    ("syscall", doc("syscall(id, arg, ...)", "Raw syscall: arguments are passed untagged.", "syscall(39)  // getpid")),
    ("json_parse", doc("json_parse(text) -> value", "Parse JSON into maps/lists/values.", "json_parse(\"{\\\"a\\\":1}\")")),
    ("json_stringify", doc("json_stringify(value) -> Str", "Serialize a value to JSON.", "json_stringify({\"a\": 1})")),
    ("spawn", doc("spawn(f)", "Start a zero-argument function on its own fiber.", "spawn(fun() { work(); })")),
    ("yield", doc("yield()", "Hand control to the next fiber.", "yield()")),
    ("run", doc("run()", "Drain ready fibers with a round-robin scheduler.", "run()")),
    ("ptr", doc("ptr(n) -> Int", "A raw pointer is just an integer address.", "ptr(addr(s))")),
    ("addr", doc("addr(value) -> Int", "The machine address of a heap value (string bytes, list/map/float base).", "addr(\"hi\")")),
    ("cstr", doc("cstr(s) -> Int", "A NUL-terminated copy of a string for C interop.", "cstr(\"hi\")")),
    ("load8", doc("load8(p) -> Int", "Read one byte of raw memory.", "load8(addr(s))")),
    ("load16", doc("load16(p) -> Int", "Read a 16-bit word of raw memory.", "load16(p)")),
    ("load32", doc("load32(p) -> Int", "Read a 32-bit word of raw memory.", "load32(p)")),
    ("load64", doc("load64(p) -> Int", "Read a 64-bit word of raw memory.", "load64(p)")),
    ("store8", doc("store8(p, v)", "Write a byte of raw memory.", "store8(p, 0)")),
    ("store16", doc("store16(p, v)", "Write a 16-bit word of raw memory.", "store16(p, 1)")),
    ("store32", doc("store32(p, v)", "Write a 32-bit word of raw memory.", "store32(p, 2)")),
    ("store64", doc("store64(p, v)", "Write a 64-bit word of raw memory.", "store64(p, 3)")),
    ("ccall", doc("ccall(fn, argv) -> Int", "Call an address with the System V C ABI.", "ccall(p, [40, 2])")),
    ("extern_c", doc("extern_c(fn) -> Fun", "Wrap an address as a callable value.", "let f = extern_c(p); f(1, 2);")),
];
