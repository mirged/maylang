//! The `maylang` command-line interface: native runner, builder and tooling.
//!
//! There is no interpreter: `run` compiles the program with the native backend
//! and executes the resulting freestanding binary in a temporary file.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

use may_ast::{Program, StmtKind};
use may_check as check;

mod resolve;

const VERSION: &str = env!("CARGO_PKG_VERSION");

static RUN_COUNTER: AtomicUsize = AtomicUsize::new(0);

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let code = match args.first().map(String::as_str) {
        None | Some("-h") | Some("--help") | Some("help") => {
            print_help();
            0
        }
        Some("-V") | Some("--version") | Some("version") => {
            println!("maylang {VERSION}");
            0
        }
        Some("run") => run_file(args.get(1).map(String::as_str)),
        Some("build") => build_native(&args[1..]),
        Some("check") => check_file(args.get(1).map(String::as_str)),
        Some("aarch64-hello") => emit_aarch64_hello(&args[1..]),
        Some("tokens") => dump_tokens(args.get(1).map(String::as_str)),
        Some("ast") => dump_ast(args.get(1).map(String::as_str)),
        Some(other) => {
            eprintln!("maylang: unknown command `{other}`");
            print_help();
            2
        }
    };
    std::process::exit(code);
}

fn print_help() {
    println!(
        "maylang {VERSION} — the Maylang language toolchain

USAGE:
    maylang run <file>     Compile and run a .may program natively
    maylang check <file>   Static analysis (no code generation)
    maylang aarch64-hello [out]   Emit the AArch64 hello ELF (scaffold)
    maylang build [opts] <file>
                           Emit a native executable (ELF / Mach-O)
        -t, --target <linux|macos>   default: host
        -o <path>                    output path (default: <stem>)
    maylang tokens <file>  Print the token stream
    maylang ast <file>     Print the parsed AST
    maylang help           Show this help
    maylang version        Show the version"
    );
}

fn read_source(path: Option<&str>) -> Result<(String, String), i32> {
    let path = match path {
        Some(p) => p,
        None => {
            eprintln!("maylang: missing file path");
            return Err(2);
        }
    };
    match std::fs::read_to_string(path) {
        Ok(src) => Ok((path.to_string(), src)),
        Err(e) => {
            eprintln!("maylang: cannot read {path}: {e}");
            Err(1)
        }
    }
}

fn run_file(path: Option<&str>) -> i32 {
    let path = match path {
        Some(p) => p,
        None => {
            eprintln!("maylang: missing file path");
            return 2;
        }
    };
    let program = match collect_native_program(Path::new(path), true) {
        Ok(program) => program,
        Err(e) => {
            report_load_error(e);
            return 1;
        }
    };
    let bytes = match may_native::compile(&program, may_native::Target::host()) {
        Ok(bytes) => bytes,
        Err(e) => {
            eprintln!("{path}: native error: {e}");
            return 1;
        }
    };

    let unique = RUN_COUNTER.fetch_add(1, Ordering::Relaxed);
    let tmp = std::env::temp_dir().join(format!(
        "maylang_run_{}_{}.bin",
        std::process::id(),
        unique
    ));
    if let Err(e) = std::fs::write(&tmp, &bytes) {
        eprintln!("maylang: cannot write {}: {e}", tmp.display());
        return 1;
    }
    make_executable_path(&tmp);

    let status = std::process::Command::new(&tmp).status();
    let _ = std::fs::remove_file(&tmp);
    match status {
        Ok(status) => status.code().unwrap_or(1),
        Err(e) => {
            eprintln!("maylang: cannot run native program: {e}");
            1
        }
    }
}

fn report_load_error(error: LoadError) -> i32 {
    eprintln!("maylang: {}", load_error_message(error));
    1
}

fn load_error_message(error: LoadError) -> String {
    match error {
        LoadError::Io(message) => message,
        LoadError::Compile(message) => format!("compile error: {message}"),
    }
}

enum LoadError {
    Io(String),
    Compile(String),
}

fn build_native(args: &[String]) -> i32 {
    let mut target = may_native::Target::host();
    let mut out: Option<String> = None;
    let mut file: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "-t" | "--target" => {
                i += 1;
                match args.get(i).and_then(|n| may_native::Target::from_name(n)) {
                    Some(t) => target = t,
                    None => {
                        eprintln!("maylang: expected a target after --target (linux|macos)");
                        return 2;
                    }
                }
            }
            "-o" => {
                i += 1;
                match args.get(i) {
                    Some(path) => out = Some(path.clone()),
                    None => {
                        eprintln!("maylang: expected a path after -o");
                        return 2;
                    }
                }
            }
            other if other.starts_with('-') => {
                eprintln!("maylang: unknown build option `{other}`");
                return 2;
            }
            other => file = Some(other.to_string()),
        }
        i += 1;
    }

    let file = match file {
        Some(f) => f,
        None => {
            eprintln!("maylang: build requires a source file");
            return 2;
        }
    };
    let program = match collect_native_program(Path::new(&file), true) {
        Ok(program) => program,
        Err(e) => {
            report_load_error(e);
            return 1;
        }
    };

    let bytes = match may_native::compile(&program, target) {
        Ok(bytes) => bytes,
        Err(e) => {
            eprintln!("{file}: native error: {e}");
            return 1;
        }
    };

    let output = out.unwrap_or_else(|| {
        Path::new(&file)
            .with_extension("")
            .to_string_lossy()
            .into_owned()
    });
    if let Err(e) = std::fs::write(&output, &bytes) {
        eprintln!("maylang: cannot write {output}: {e}");
        return 1;
    }
    make_executable(&output);
    println!(
        "wrote {output} ({}, {} bytes)",
        target.name(),
        bytes.len()
    );
    0
}

#[cfg(unix)]
fn make_executable(path: &str) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755));
}

#[cfg(not(unix))]
fn make_executable(_path: &str) {}

#[cfg(unix)]
fn make_executable_path(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755));
}

#[cfg(not(unix))]
fn make_executable_path(_path: &Path) {}

/// Parse and link all `import`ed modules into one namespaced program for the
/// native backend (which has no linker of its own).
fn collect_native_program(entry: &Path, with_prelude: bool) -> Result<Program, LoadError> {
    let mut visited = HashSet::new();
    let mut modules: Vec<resolve::ModuleInput> = Vec::new();
    collect_native(entry, &mut visited, &mut modules)?;

    let mut program = resolve::resolve(modules).map_err(LoadError::Compile)?;

    // The prelude is a set of global helpers; append it without mangling so it
    // stays reachable by its plain names from every module.
    if let Some(prelude) = load_native_prelude().filter(|_| with_prelude) {
        for stmt in prelude.body.stmts {
            if let StmtKind::Import { .. } = stmt.kind {
                continue;
            }
            program.body.stmts.push(stmt);
        }
    }

    Ok(program)
}

/// Load `stdlib/prelude.may` for a native build. Returns `None` when disabled
/// or not found.
fn load_native_prelude() -> Option<Program> {
    if std::env::var("MAYLANG_NO_PRELUDE").is_ok() {
        return None;
    }
    for dir in stdlib_dirs() {
        let candidate = dir.join("prelude.may");
        if candidate.exists() {
            let source = std::fs::read_to_string(&candidate).ok()?;
            return may_parser::parse(&source).ok();
        }
    }
    None
}

fn collect_native(
    path: &Path,
    visited: &mut HashSet<PathBuf>,
    out: &mut Vec<resolve::ModuleInput>,
) -> Result<(), LoadError> {
    let canonical = std::fs::canonicalize(path)
        .map_err(|e| LoadError::Io(format!("cannot open {}: {e}", path.display())))?;
    if !visited.insert(canonical.clone()) {
        return Ok(());
    }
    let source = std::fs::read_to_string(&canonical)
        .map_err(|e| LoadError::Io(format!("cannot read {}: {e}", canonical.display())))?;
    let program = may_parser::parse(&source)
        .map_err(|e| LoadError::Compile(format!("{}: {e}", canonical.display())))?;

    let mut import_targets = HashMap::new();
    for stmt in &program.body.stmts {
        if let StmtKind::Import { path: import, .. } = &stmt.kind {
            let target = resolve_module(&canonical, import);
            let target_canon = std::fs::canonicalize(&target).unwrap_or_else(|_| target.clone());
            import_targets.insert(import.clone(), target_canon);
            collect_native(&target, visited, out)?;
        }
    }
    out.push(resolve::ModuleInput {
        path: canonical,
        program,
        import_targets,
    });
    Ok(())
}

/// Resolve an import path relative to the importing file, then across the
/// standard-library search path, appending `.may` when no extension is present.
fn resolve_module(importing: &Path, module: &str) -> PathBuf {
    let raw = Path::new(module);
    let with_ext = if raw.extension().is_some() {
        raw.to_path_buf()
    } else {
        raw.with_extension("may")
    };
    if with_ext.is_absolute() {
        return with_ext;
    }
    let relative = importing
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(&with_ext);
    if relative.exists() {
        return relative;
    }
    for dir in stdlib_dirs() {
        let candidate = dir.join(&with_ext);
        if candidate.exists() {
            return candidate;
        }
    }
    relative
}

/// Directories searched for `import`ed modules, in order.
fn stdlib_dirs() -> Vec<PathBuf> {
    if let Ok(env) = std::env::var("MAYLANG_STDLIB") {
        return env
            .split(':')
            .filter(|part| !part.is_empty())
            .map(PathBuf::from)
            .collect();
    }
    let mut dirs = vec![PathBuf::from("stdlib")];
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent();
        for _ in 0..4 {
            match dir {
                Some(current) => {
                    dirs.push(current.join("stdlib"));
                    dir = current.parent();
                }
                None => break,
            }
        }
    }
    if let Ok(home) = std::env::var("HOME") {
        dirs.push(PathBuf::from(home).join(".maylang").join("stdlib"));
    }
    dirs
}

/// Write the AArch64 "hello" ELF (Phase 7 scaffold).
fn emit_aarch64_hello(args: &[String]) -> i32 {
    let out = args
        .first()
        .cloned()
        .unwrap_or_else(|| "hello.aarch64".to_string());
    let bytes = may_native::aarch64_hello();
    if let Err(e) = std::fs::write(&out, &bytes) {
        eprintln!("maylang: cannot write {out}: {e}");
        return 1;
    }
    make_executable(&out);
    println!("wrote {out} (aarch64, {} bytes)", bytes.len());
    0
}

fn check_file(path: Option<&str>) -> i32 {
    let path = match path {
        Some(p) => p,
        None => {
            eprintln!("maylang: missing file path");
            return 2;
        }
    };
    // Check only the user's modules (no prelude) so dynamic helper code cannot
    // produce false positives; unknown helpers are treated as `Any`.
    let program = match collect_native_program(Path::new(path), false) {
        Ok(program) => program,
        Err(e) => {
            report_load_error(e);
            return 1;
        }
    };
    let diags = check::check(&program);
    for error in &diags.errors {
        eprintln!("{path}: {error}");
    }
    if diags.errors.is_empty() {
        println!("{path}: no issues found");
        0
    } else {
        eprintln!("{path}: {} issue(s)", diags.errors.len());
        1
    }
}

fn dump_tokens(path: Option<&str>) -> i32 {
    let (name, source) = match read_source(path) {
        Ok(v) => v,
        Err(code) => return code,
    };
    match may_lexer::tokenize(&source) {
        Ok(tokens) => {
            for token in tokens {
                println!("{:>4}: {:?}", token.line, token.kind);
            }
            0
        }
        Err(e) => {
            eprintln!("{name}: lex error: {e}");
            1
        }
    }
}

fn dump_ast(path: Option<&str>) -> i32 {
    let (name, source) = match read_source(path) {
        Ok(v) => v,
        Err(code) => return code,
    };
    match may_parser::parse(&source) {
        Ok(program) => {
            println!("{program:#?}");
            0
        }
        Err(e) => {
            eprintln!("{name}: parse error: {e}");
            1
        }
    }
}
