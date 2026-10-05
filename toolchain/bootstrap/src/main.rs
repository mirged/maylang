//! Source-only stage zero: Maylang -> GNU C -> a native executable.
use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use may_ast::{Block, Program, Stmt, StmtKind};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
mod c;
#[path = "../../legacy-rust/crates/may_cli/src/resolve.rs"]
mod resolve;

fn load(
    path: &Path,
    seen: &mut HashSet<PathBuf>,
    modules: &mut Vec<resolve::ModuleInput>,
) -> Result<()> {
    let path = fs::canonicalize(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if !seen.insert(path.clone()) {
        return Ok(());
    }
    let source = fs::read_to_string(&path)?;
    let program = may_parser::parse(&source).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut import_targets = HashMap::new();
    for stmt in &program.body.stmts {
        if let StmtKind::Import { path: import, .. } = &stmt.kind {
            let mut target = path.parent().unwrap().join(import);
            if target.extension().is_none() {
                target.set_extension("may");
            }
            import_targets.insert(import.clone(), fs::canonicalize(&target)?);
            load(&target, seen, modules)?;
        }
    }
    modules.push(resolve::ModuleInput {
        path,
        program,
        import_targets,
    });
    Ok(())
}

fn run() -> Result<()> {
    if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        return Err("bootstrap requires x86-64 Linux".into());
    }
    let mut args = std::env::args_os().skip(1);
    let mut source = None;
    let mut output = None;
    let mut emit_c = false;
    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("-h" | "--help") => {
                println!("Usage: may-bootstrap [--emit-c] <source.may> [-o <output>]\nRequires x86-64 Linux and a GNU C compiler (CC or cc).");
                return Ok(());
            }
            Some("-o") => output = Some(PathBuf::from(args.next().ok_or("-o requires a path")?)),
            Some("--emit-c") => emit_c = true,
            Some(option) if option.starts_with('-') => {
                return Err(format!("unknown option: {option}").into())
            }
            _ if source.is_none() => source = Some(PathBuf::from(arg)),
            _ => return Err("expected one source file".into()),
        }
    }
    let source = source.ok_or("expected a source file; use --help")?;
    let output = output.unwrap_or_else(|| {
        if emit_c {
            source.with_extension("c")
        } else if source.extension().is_some_and(|ext| ext == "may") {
            source.with_extension("")
        } else {
            PathBuf::from(format!("{}.out", source.display()))
        }
    });
    if output == source
        || (output.exists() && fs::canonicalize(&output)? == fs::canonicalize(&source)?)
    {
        return Err("output would overwrite the source".into());
    }
    let mut modules = Vec::new();
    load(&source, &mut HashSet::new(), &mut modules)?;
    let mut program = resolve::resolve(modules)?;
    if let Some(expr) = program.body.tail.take() {
        program.body.stmts.push(Stmt::new(
            StmtKind::Expr {
                expr: *expr,
                semi: true,
            },
            program.body.tail_line,
        ));
    }
    let mut stmts = program.body.stmts;
    // Add each library helper once; user modules are already namespaced.
    let mut defined: HashSet<_> = stmts
        .iter()
        .filter_map(|s| {
            if let StmtKind::Fun { name, .. } = &s.kind {
                Some(name.clone())
            } else {
                None
            }
        })
        .collect();
    for source in [
        include_str!("../../mayc/native.may"),
        include_str!("../../../stdlib/prelude.may"),
    ] {
        for stmt in may_parser::parse(source)?.body.stmts {
            if let StmtKind::Fun { name, .. } = &stmt.kind {
                if defined.insert(name.clone()) {
                    stmts.push(stmt);
                }
            }
        }
    }
    let program = Program::new(Block::new(stmts, None, 0));
    let code = c::emit(&program);
    if emit_c {
        fs::write(&output, code)?;
    } else {
        // A private scratch directory prevents parallel builds from colliding.
        let scratch = std::env::temp_dir().join(format!("may-bootstrap-{}", std::process::id()));
        fs::create_dir(&scratch)?;
        let c_source = scratch.join("main.c");
        fs::write(&c_source, code)?;
        let compiled = Command::new(std::env::var_os("CC").unwrap_or_else(|| "cc".into()))
            .args(["-std=gnu11", "-O0", "-w"])
            .arg(&c_source)
            .arg("-lm")
            .arg("-o")
            .arg(scratch.join("program"))
            .status();
        let result = match compiled {
            Ok(status) if status.success() => {
                fs::copy(scratch.join("program"), &output).map(|_| ())
            }
            Ok(_) => Err(std::io::Error::other("C compiler failed")),
            Err(error) => Err(error),
        };
        fs::remove_dir_all(&scratch)?;
        result?;
        fs::set_permissions(&output, fs::Permissions::from_mode(0o755))?;
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("may-bootstrap: {error}");
        std::process::exit(1);
    }
}
