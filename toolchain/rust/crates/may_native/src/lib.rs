//! Native x86-64 backend: emits freestanding ELF (Linux) and Mach-O (macOS)
//! executables directly from Maylang source, with no external assembler or
//! linker.
//!
//! The native backend is the language's only execution target: it compiles the
//! whole language to machine code and runs under a small hand-written runtime
//! with a conservative mark-sweep garbage collector.

mod aarch64;
mod capture;
mod codegen;
mod elf;
mod fibers;
mod fold;
mod gc;
mod macho;
mod runtime;
pub mod x86;

use std::collections::HashSet;
use std::fmt;

use may_ast::{Block, Program};

/// The native standard library, compiled into every native program.
const NATIVE_PRELUDE: &str = include_str!("native_prelude.may");

/// A native compilation error (usually an unsupported construct).
#[derive(Debug, Clone)]
pub struct NativeError {
    pub message: String,
}

impl NativeError {
    pub fn new(message: impl Into<String>) -> Self {
        NativeError {
            message: message.into(),
        }
    }
}

impl fmt::Display for NativeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for NativeError {}

/// Supported executable formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    LinuxElf,
    MacOS,
}

impl Target {
    /// The format matching the host running this code.
    pub fn host() -> Target {
        if cfg!(target_os = "macos") {
            Target::MacOS
        } else {
            Target::LinuxElf
        }
    }

    pub fn from_name(name: &str) -> Option<Target> {
        match name {
            "linux" | "elf" => Some(Target::LinuxElf),
            "macos" | "macho" | "darwin" | "osx" => Some(Target::MacOS),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Target::LinuxElf => "linux",
            Target::MacOS => "macos",
        }
    }

    /// `write(2)` syscall number.
    pub fn write_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 1,
            Target::MacOS => 0x200_0004,
        }
    }

    /// `exit(2)` syscall number.
    pub fn exit_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 60,
            Target::MacOS => 0x200_0001,
        }
    }

    /// `read(2)` syscall number.
    pub fn read_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 0,
            Target::MacOS => 0x200_0003,
        }
    }

    /// `clock_gettime(2)` syscall number (Linux only; macOS uses gettimeofday).
    pub fn clock_gettime_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 228,
            Target::MacOS => 0,
        }
    }

    /// `gettimeofday(2)` syscall number (macOS).
    pub fn gettimeofday_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 96,
            Target::MacOS => 0x200_0074,
        }
    }

    /// `open(2)` syscall number.
    pub fn open_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 2,
            Target::MacOS => 0x200_0005,
        }
    }

    /// `close(2)` syscall number.
    pub fn close_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 3,
            Target::MacOS => 0x200_0006,
        }
    }

    /// `access(2)` syscall number.
    pub fn access_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 21,
            Target::MacOS => 0x200_0021,
        }
    }

    /// `mmap(2)` syscall number.
    pub fn mmap_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 9,
            Target::MacOS => 0x200_00C5,
        }
    }

    /// `mkdir(2)` syscall number.
    pub fn mkdir_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 83,
            Target::MacOS => 0x200_0088,
        }
    }

    /// `getdents64(2)` syscall number (Linux only; macOS uses `0`).
    pub fn getdents_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 217,
            Target::MacOS => 0,
        }
    }

    /// `O_DIRECTORY` open flag.
    pub fn o_directory(self) -> i64 {
        match self {
            Target::LinuxElf => 0x1_0000,
            Target::MacOS => 0x10_0000,
        }
    }

    /// `fork(2)` syscall number.
    pub fn fork_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 57,
            Target::MacOS => 0x200_0002,
        }
    }

    /// `execve(2)` syscall number.
    pub fn execve_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 59,
            Target::MacOS => 0x200_003b,
        }
    }

    /// `wait4(2)` syscall number.
    pub fn wait4_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 61,
            Target::MacOS => 0x200_0007,
        }
    }

    /// `nanosleep(2)` syscall number.
    pub fn nanosleep_nr(self) -> i64 {
        match self {
            Target::LinuxElf => 35,
            Target::MacOS => 0x200_0023,
        }
    }

    /// `MAP_PRIVATE | MAP_ANONYMOUS` for this target.
    pub fn mmap_anon_flags(self) -> i64 {
        match self {
            Target::LinuxElf => 0x22,
            Target::MacOS => 0x1002,
        }
    }

    /// Base virtual address of the single loadable segment.
    pub fn base_vaddr(self) -> u64 {
        match self {
            Target::LinuxElf => 0x40_0000,
            Target::MacOS => 0x1_0000_0000,
        }
    }

    pub fn header_size(self) -> usize {
        match self {
            Target::LinuxElf => elf::HEADER_SIZE,
            Target::MacOS => macho::HEADER_SIZE,
        }
    }
}

/// Compile a parsed program into an executable image for `target`.
pub fn compile(program: &Program, target: Target) -> Result<Vec<u8>, NativeError> {
    compile_with_heap(program, target, HEAP_SIZE)
}

/// Compile with an explicit GC heap size (bytes). Tests use a small heap to
/// force frequent collection.
pub fn compile_with_heap(
    program: &Program,
    target: Target,
    heap_size: usize,
) -> Result<Vec<u8>, NativeError> {
    let prelude = may_parser::parse(NATIVE_PRELUDE)
        .map_err(|e| NativeError::new(format!("internal prelude error: {e}")))?;
    let mut merged = merge_prelude(&prelude, program);
    fold::fold_program(&mut merged);
    codegen::Codegen::with_heap(target, heap_size).build(&merged)
}

/// Emit the AArch64 "hello" ELF image (Phase 7 scaffold: encoder + writer, not
/// yet a full code generator; no AArch64 host to execute it here).
pub fn aarch64_hello() -> Vec<u8> {
    aarch64::build_hello()
}

/// Default heap reservation for native executables. The heap is mapped with
/// `mmap` at startup and is demand-zero, so only touched pages consume memory.
pub const HEAP_SIZE: usize = 1 << 30; // 1 GiB

/// BSS scratch for `exec` argument vectors: room for 1024 pointers.
pub const PROC_SCRATCH_ARGV_BYTES: usize = 8192;
/// BSS scratch for the NUL-terminated argument strings used by `exec`/`system`.
pub const PROC_SCRATCH_STR_CAP: usize = 262144; // 256 KiB

/// Prepend the prelude's functions, letting user definitions win on conflict.
fn merge_prelude(prelude: &Program, user: &Program) -> Program {
    let mut stmts = user.body.stmts.clone();
    let mut defined: HashSet<String> = stmts
        .iter()
        .filter_map(|stmt| match &stmt.kind {
            may_ast::StmtKind::Fun { name, .. } => Some(name.clone()),
            _ => None,
        })
        .collect();
    for stmt in &prelude.body.stmts {
        if let may_ast::StmtKind::Fun { name, .. } = &stmt.kind {
            if !defined.insert(name.clone()) {
                continue;
            }
        }
        stmts.push(stmt.clone());
    }
    let tail = user.body.tail.as_ref().map(|expr| (**expr).clone());
    Program::new(Block::new(stmts, tail, user.body.tail_line))
}

/// Parse and compile source text into an executable image.
pub fn compile_source(source: &str, target: Target) -> Result<Vec<u8>, NativeError> {
    let program = may_parser::parse(source)
        .map_err(|e| NativeError::new(format!("parse error: {e}")))?;
    compile(&program, target)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "linux")]
    fn run_elf(src: &str) -> String {
        run_elf_heap(src, HEAP_SIZE)
    }

    #[cfg(target_os = "linux")]
    fn run_elf_heap(src: &str, heap: usize) -> String {
        run_elf_args_heap(src, heap, &[])
    }

    #[cfg(target_os = "linux")]
    fn run_elf_args(src: &str, args: &[&str]) -> String {
        run_elf_args_heap(src, HEAP_SIZE, args)
    }

    #[cfg(target_os = "linux")]
    fn run_elf_args_heap(src: &str, heap: usize, args: &[&str]) -> String {
        use std::io::Write;
        use std::os::unix::fs::PermissionsExt;
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::Mutex;

        static COUNTER: AtomicUsize = AtomicUsize::new(0);
        static LOCK: Mutex<()> = Mutex::new(());
        let _guard = LOCK.lock().unwrap();
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let program = may_parser::parse(src).expect("parse");
        let bytes = compile_with_heap(&program, Target::LinuxElf, heap).expect("native compile");
        let path = std::env::temp_dir().join(format!(
            "may_native_test_{}_{}",
            std::process::id(),
            unique
        ));
        let mut file = std::fs::File::create(&path).unwrap();
        file.write_all(&bytes).unwrap();
        drop(file);
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        let output = std::process::Command::new(&path)
            .args(args)
            .output()
            .unwrap();
        let _ = std::fs::remove_file(&path);
        assert!(output.status.success(), "program exited with {:?}", output.status);
        String::from_utf8_lossy(&output.stdout).into_owned()
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn arithmetic_and_concat_free_printing() {
        assert_eq!(run_elf("print(1 + 2 * 3);").trim(), "7");
        assert_eq!(run_elf("print(-7);").trim(), "-7");
        assert_eq!(run_elf("print(true); print(false); print(nil);").trim(), "true\nfalse\nnil");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn functions_recursion_and_strings() {
        let out = run_elf(
            "fun fib(n) { if (n < 2) { n } else { fib(n - 1) + fib(n - 2) } } print(\"fib\", fib(15));",
        );
        assert_eq!(out.trim(), "fib 610");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn loops_and_globals() {
        let out = run_elf(
            "let LIMIT = 20;\n\
             fun total(n) { mut t = 0; for i in 1..=n { if (i == 5) { continue; } if (i > LIMIT) { break; } t += i; } t }\n\
             print(total(100));",
        );
        assert_eq!(out.trim(), "205"); // sum(1..=20) - 5
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn floats_may_and_safe_nav() {
        assert_eq!(run_elf("print(1.5 + 2.25);").trim(), "3.75");
        assert_eq!(run_elf("print(2 ** 10);").trim(), "1024");
        assert_eq!(run_elf("print(sqrt(2.0));").trim(), "1.4142135623730951");
        assert_eq!(
            run_elf("print(may { 1 / 0 } otherwise { \"caught\" });").trim(),
            "caught"
        );
        assert_eq!(run_elf("print(may { 42 });").trim(), "42");
        assert_eq!(
            run_elf("print(({\"a\": {\"b\": 7}})?.a?.b, nil?.x);").trim(),
            "7 nil"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn first_class_functions() {
        let out = run_elf(
            "fun add1(x) { x + 1 }\n\
             let f = add1;\n\
             let g = |x| x * 2;\n\
             fun apply(fn, v) { fn(v) }\n\
             print(f(41), g(21), map([1, 2, 3], g), apply(add1, 10));",
        );
        assert_eq!(out.trim(), "42 42 [2, 4, 6] 11");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn capturing_closures() {
        let out = run_elf(
            "fun make_counter(start) { mut n = start; fun next() { n = n + 1; n } next }\n\
             let a = make_counter(0);\n\
             let b = make_counter(100);\n\
             print(a(), a(), a(), b());\n\
             fun adder(n) { |x| x + n }\n\
             print(adder(5)(10), adder(5)(1));",
        );
        assert_eq!(out.trim(), "1 2 3 101\n15 6");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn arrays_heap_and_push() {
        let out = run_elf(
            "let xs = [];\n\
             for i in 1..=4 { push(xs, i * i); }\n\
             print(xs);\n\
             print(len(xs), pop(xs));\n\
             let copy = [1, [2, 3], true, nil, \"s\"];\n\
             print(copy);",
        );
        assert_eq!(out.trim(), "[1, 4, 9, 16]\n4 16\n[1, [2, 3], true, nil, \"s\"]");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn structured_errors_and_type_faults() {
        let out = run_elf(
            "print(may { fail(\"boom\") } otherwise { \"${err.kind}: ${err.message}\" });\n\
             print(may { 1 / 0 } otherwise { \"${err.kind}: ${err.message}\" });\n\
             print(may { \"x\" / 2 } otherwise { \"${err.kind}: ${err.message}\" });",
        );
        assert_eq!(
            out.trim(),
            "fail: boom\narithmetic: division by zero\ntype: cannot apply `/` to Str and Int"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn quantifiers_and_mixed_interpolation() {
        let out = run_elf(
            "let nums = [1, 2, 3, 4, 5];\n\
             print(any(nums, |x| x > 4), all(nums, |x| x > 0), all(nums, |x| x > 2));\n\
             print(\"v=${1 + 2}!\");",
        );
        assert_eq!(out.trim(), "true true false\nv=3!");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn json_math_and_collections() {
        let out = run_elf(
            "let doc = json_parse(\"{\\\"name\\\": \\\"Ada\\\", \\\"scores\\\": [1, 2, 3]}\");\n\
             print(doc.name, len(doc.scores));\n\
             print(json_stringify({\"b\": 2, \"a\": [true, nil]}));\n\
             print(sin(pi() / 2.0), floor(3.9), sign(-4));",
        );
        assert_eq!(
            out.trim(),
            "Ada 3\n{\"a\":[true,null],\"b\":2}\n1.0 3 -1"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn file_io_round_trip() {
        let out = run_elf(
            "let path = \"/tmp/maylang_native_io_test.txt\";\n\
             write_file(path, \"hello file\");\n\
             print(file_exists(path), read_file(path));\n",
        );
        assert_eq!(out.trim(), "true hello file");
        let _ = std::fs::remove_file("/tmp/maylang_native_io_test.txt");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn function_locals_shadow_globals() {
        let out = run_elf(
            "let a = 6.28;\n\
             fun loopit(n) { mut a = 0; while (a < n) { a = a + 1; } a }\n\
             let r = loopit(5);\n\
             print(a, r);",
        );
        assert_eq!(out.trim(), "6.28 5");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn shortest_float_formatting() {
        let out = run_elf("print(12.34, 0.000168, 100.0 / 7.0, 1.0 / 3.0, sqrt(2.0));");
        assert_eq!(
            out.trim(),
            "12.34 0.000168 14.285714285714286 0.3333333333333333 1.4142135623730951"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn raw_syscall_builtin() {
        // getpid (39) returns a positive pid; unknown syscalls return a negative errno.
        let out = run_elf("print(syscall(39, []) > 0, syscall(9999, []) < 0);");
        assert_eq!(out.trim(), "true true");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn generational_gc_promotes_survivors() {
        // Many young strings churn while a few survive into the old generation.
        let out = run_elf_heap(
            "let keep = [];\n\
             mut i = 0;\n\
             while (i < 300000) {\n\
                 let junk = \"j\" + str(i);\n\
                 if (i % 10000 == 0) { push(keep, junk); }\n\
                 i = i + 1;\n\
             }\n\
             print(len(keep), keep[0], keep[29]);",
            1 << 20,
        );
        assert_eq!(out.trim(), "30 j0 j290000");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn fibers_interleave_round_robin() {
        let out = run_elf(
            "fun worker(id) { mut i = 0; while (i < 2) { print(id, i); yield(); i = i + 1; } }\n\
             spawn(fun() { worker(1) });\n\
             spawn(fun() { worker(2) });\n\
             run();",
        );
        assert_eq!(out.trim(), "1 0\n2 0\n1 1\n2 1");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn fibers_run_and_gc_scans_every_stack() {
        // Live heap objects are referenced only from each fiber's stack
        // (`keep`), while a small heap forces frequent collections.
        let out = run_elf_heap(
            "fun worker(id) {\n\
                 let keep = [];\n\
                 mut i = 0;\n\
                 while (i < 100000) {\n\
                     let junk = \"j\" + str(id) + \"-\" + str(i);\n\
                     if (i % 100 == 0) { push(keep, junk); }\n\
                     if (i % 500 == 0) { yield(); }\n\
                     i = i + 1;\n\
                 }\n\
                 print(id, len(keep), keep[len(keep) - 1]);\n\
             }\n\
             spawn(fun() { worker(1) });\n\
             spawn(fun() { worker(2) });\n\
             run();\n\
             print(\"done\");",
            1 << 22,
        );
        assert_eq!(
            out.trim(),
            "1 1000 j1-99900\n2 1000 j2-99900\ndone"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn structs_can_overload_arithmetic_operators() {
        let out = run_elf(
            "fun vadd(self, other) { V(self.x + other.x, self.y + other.y) }\n\
             fun vsub(self, other) { V(self.x - other.x, self.y - other.y) }\n\
             struct V { x, y, \"+\": vadd, \"-\": vsub }\n\
             let c = V(1, 2) + V(3, 4);\n\
             let d = V(5, 6) - V(1, 1);\n\
             print(c.x, c.y, d.x, d.y, 2 + 3, \"a\" + \"b\");",
        );
        assert_eq!(out.trim(), "4 6 4 5 5 ab");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn result_question_operator_propagates() {
        let out = run_elf(
            "fun safe_div(a, b) { if (b == 0) { return Err(\"div0\"); } Ok(a / b) }\n\
             fun compute(a, b) { let q = safe_div(a, b)?; Ok(q + 100) }\n\
             fun some(v) { Some(v + 1)? }\n\
             fun none() { let v = None()?; 42 }\n\
             print(compute(10, 2).value, compute(10, 0).error, some(41), none());",
        );
        assert_eq!(out.trim(), "105 div0 42 nil");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn enums_desugar_to_tagged_maps() {
        let out = run_elf(
            "enum Shape { Circle(r), Rect(w, h), Empty }\n\
             fun area(s) { match (s.tag) { \"Circle\" => 3.0 * s.r * s.r, \"Rect\" => s.w * s.h, _ => 0.0 } }\n\
             print(area(Circle(2.0)), area(Rect(3.0, 4.0)), area(Empty()), Empty().tag);",
        );
        assert_eq!(out.trim(), "12.0 12.0 0.0 Empty");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn let_and_for_destructuring() {
        let out = run_elf(
            "struct Point { x, y }\n\
             let {x, y} = Point(3, 4);\n\
             let [a, b] = [10, 20];\n\
             let {pos: [q, r]} = {\"pos\": [1, 2]};\n\
             print(x, y, a, b, q, r);\n\
             let pairs = [[1, 2], [3, 4]];\n\
             mut total = 0;\n\
             for [u, v] in pairs { total = total + u + v; }\n\
             print(total);",
        );
        assert_eq!(out.trim(), "3 4 10 20 1 2\n10");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn structs_desugar_to_tagged_maps() {
        let out = run_elf(
            "struct Point { x, y }\n\
             let p = Point(3, 4);\n\
             print(p.x + p.y, len(p), has(p, \"x\"));",
        );
        assert_eq!(out.trim(), "7 2 true");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn constant_folding_preserves_semantics() {
        let out = run_elf("print(2 + 3 * 4, \"a\" + \"b\", -5, (1 < 2) || false);");
        assert_eq!(out.trim(), "14 ab -5 true");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn self_tail_calls_are_optimised() {
        let out = run_elf(
            "fun loop(n, acc) { if (n == 0) { acc } else { loop(n - 1, acc + n) } }\n\
             fun ret(n, acc) { if (n == 0) { return acc; } return ret(n - 1, acc + n); }\n\
             print(loop(1000000, 0), ret(1000000, 0));",
        );
        assert_eq!(out.trim(), "500000500000 500000500000");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn extreme_floats_use_scientific_notation() {
        let out = run_elf("print(1e300, 1e-10, 2.5e-9, 6.022e23);");
        assert_eq!(out.trim(), "1e300 1e-10 2.5e-9 6.022e23");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn gc_reclaims_string_garbage() {
        let out = run_elf_heap(
            "mut i = 0;\n\
             mut s = \"\";\n\
             while (i < 200000) { s = \"v\" + str(i); i = i + 1; }\n\
             print(s);",
            1 << 22,
        );
        assert_eq!(out.trim(), "v199999");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn gc_preserves_live_containers() {
        let out = run_elf_heap(
            "let keep = [];\n\
             mut i = 0;\n\
             while (i < 200000) {\n\
                 let junk = [\"a\" + str(i), \"b\" + str(i), \"c\" + str(i)];\n\
                 if (i % 100 == 0) { push(keep, junk); }\n\
                 i = i + 1;\n\
             }\n\
             print(len(keep), keep[0], keep[1999]);",
            1 << 22,
        );
        assert_eq!(
            out.trim(),
            "2000 [\"a0\", \"b0\", \"c0\"] [\"a199900\", \"b199900\", \"c199900\"]"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn gc_preserves_closures() {
        let out = run_elf_heap(
            "mut f = fun() { 0 };\n\
             mut i = 0;\n\
             while (i < 200000) { f = fun() { i }; i = i + 1; }\n\
             print(f());",
            1 << 22,
        );
        assert_eq!(out.trim(), "200000");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn extra_builtins_and_descending_ranges() {
        let out = run_elf(
            "print(range(5, 0));\n\
             print(clamp(15, 0, 10), has([1, 2, 3], 2), has(\"hello\", \"ell\"));\n\
             print(enumerate([\"a\", \"b\"]), zip([1, 2], [\"x\", \"y\"]));\n\
             print(flatten([[1], [2, 3]]), unique([1, 2, 2, 3]), product([1, 2, 3]));\n\
             print(find([5, 6, 7], 6), slice([0, 1, 2, 3], 1, 3), range_step(0, 9, 3));\n\
             print(chr(65), ord(\"A\"), even(4), odd(5), get({\"a\": 1}, \"b\", 9));",
        );
        assert_eq!(
            out.trim(),
            "[5, 4, 3, 2, 1]\n\
             10 true true\n\
             [[0, \"a\"], [1, \"b\"]] [[1, \"x\"], [2, \"y\"]]\n\
             [1, 2, 3] [1, 2, 3] 6\n\
             1 [1, 2] [0, 3, 6]\n\
             A 65 true true 9"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn command_line_args() {
        let out = run_elf_args(
            "let av = args();\n\
             print(len(av), av[1], av[2]);",
            &["alpha", "beta"],
        );
        assert_eq!(out.trim(), "3 alpha beta");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn env_matches_whole_variable_names() {
        let out = run_elf(
            "print(env(\"PATH\") != nil, env(\"ATH\"), env(\"NO_SUCH_VAR_XYZ\"));",
        );
        assert_eq!(out.trim(), "true nil nil");
    }

    #[test]
    fn elf_has_a_symbol_table() {
        let bytes = compile_source("fun foo(x) { x + 1 } print(foo(1));", Target::LinuxElf).unwrap();
        assert!(bytes.windows(4).any(|w| w == b"foo\0"));
        assert!(bytes.windows(7).any(|w| w == b".symtab"));
        let shoff = u64::from_le_bytes(bytes[0x28..0x30].try_into().unwrap());
        assert!(shoff > 0 && (shoff as usize) < bytes.len());
        assert!(bytes.windows(11).any(|w| w == b".debug_line"));
    }

    #[test]
    fn macho_has_valid_magic() {
        let bytes = compile_source("print(1);", Target::MacOS).unwrap();
        assert_eq!(&bytes[0..4], &0xFEED_FACFu32.to_le_bytes());
        assert_eq!(&bytes[4..8], &0x0100_0007i32.to_le_bytes());
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn many_arguments_via_stack() {
        let out = run_elf(
            "fun f(a, b, c, d, e, g, h, i, j, k) { a + b + c + d + e + g + h + i + j + k }\n\
             print(f(1, 2, 3, 4, 5, 6, 7, 8, 9, 10));",
        );
        assert_eq!(out.trim(), "55");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn int_overflow_is_a_catchable_fault() {
        let out = run_elf(
            "let big = 1152921504606846975;\n\
             print(may { big * 4 } otherwise { err.kind });\n\
             print(may { big + big } otherwise { err.kind });",
        );
        assert_eq!(out.trim(), "arithmetic\narithmetic");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn heap_is_not_capped_at_128mib() {
        // ~160 MiB of live integers: impossible with the old fixed 128 MiB heap.
        let out = run_elf(
            "let xs = [];\n\
             mut i = 0;\n\
             while (i < 20000000) { push(xs, i); i = i + 1; }\n\
             print(len(xs));",
        );
        assert_eq!(out.trim(), "20000000");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn strings_are_utf8_codepoint_based() {
        let out = run_elf(
            "let s = \"h\u{e9}llo \u{2603}\";\n\
             print(len(s), s[1], s[6], ord(\"\u{2603}\"));",
        );
        assert_eq!(out.trim(), "7 é ☃ 9731");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn for_over_a_map_walks_keys() {
        let out = run_elf(
            "let m = {\"a\": 1, \"b\": 2, \"c\": 3};\n\
             mut total = 0;\n\
             for k in m { total = total + m[k]; }\n\
             print(total);",
        );
        assert_eq!(out.trim(), "6");
    }
}
