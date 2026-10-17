//! Module resolution and namespacing for native builds.
//!
//! Modules are still linked by textual inclusion, but every top-level name is
//! first rewritten to a unique `namespace::name`, and references (both local
//! and imported/qualified) are resolved to those mangled names. This removes
//! the old "one global namespace, first definition wins" behaviour: duplicate
//! names in different modules no longer silently collide.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use may_ast::*;

/// One parsed module plus the resolved canonical paths of its imports.
pub struct ModuleInput {
    pub path: PathBuf,
    pub program: Program,
    /// Import string -> canonical path of the target module.
    pub import_targets: HashMap<String, PathBuf>,
}

struct Ctx {
    /// Top-level definitions of the module being rewritten: name -> mangled.
    rename: HashMap<String, String>,
    /// Unqualified imported names: name -> mangled target.
    imports: HashMap<String, String>,
    /// Namespace aliases (and plain-import file stems): alias -> module index.
    namespaces: HashMap<String, usize>,
}

struct Resolver {
    namespaces: Vec<String>,
    defs: Vec<HashMap<String, bool>>,
}

/// Resolve names across `modules` (dependency order, entry last) and merge them
/// into one program. Import statements are consumed.
pub fn resolve(modules: Vec<ModuleInput>) -> Result<Program, String> {
    // Assign every module a unique namespace derived from its file stem.
    let mut used: HashSet<String> = HashSet::new();
    let mut namespaces = Vec::with_capacity(modules.len());
    for m in &modules {
        let stem = m
            .path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("module");
        let mut base: String = stem
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
            .collect();
        if base.is_empty() {
            base = "module".to_string();
        }
        let mut ns = base.clone();
        let mut n = 2;
        while !used.insert(ns.clone()) {
            ns = format!("{base}_{n}");
            n += 1;
        }
        namespaces.push(ns);
    }

    let mut path_to_idx: HashMap<PathBuf, usize> = HashMap::new();
    for (i, m) in modules.iter().enumerate() {
        path_to_idx.insert(m.path.clone(), i);
    }

    // Top-level definition names per module, mapped to whether they are
    // exported. Visibility is opt-in: a module that declares at least one `pub`
    // item exports *only* its `pub` items; a module with no `pub` at all keeps
    // its legacy behaviour (everything exported).
    let mut defs: Vec<HashMap<String, bool>> = Vec::with_capacity(modules.len());
    for m in &modules {
        let decls: Vec<(String, bool)> = m
            .program
            .body
            .stmts
            .iter()
            .filter_map(|stmt| match &stmt.kind {
                StmtKind::Fun { name, public, .. } | StmtKind::Let { name, public, .. } => {
                    Some((name.clone(), *public))
                }
                _ => None,
            })
            .collect();
        let any_pub = decls.iter().any(|(_, public)| *public);
        let mut map = HashMap::new();
        for (name, public) in decls {
            map.insert(name, public || !any_pub);
        }
        defs.push(map);
    }

    let mut merged_stmts: Vec<Stmt> = Vec::new();
    let count = modules.len();
    let mut entry_tail: Option<Expr> = None;
    let mut entry_tail_line = 0;

    for (i, m) in modules.iter().enumerate() {
        let ns = &namespaces[i];
        let mut rename = HashMap::new();
        for name in defs[i].keys() {
            rename.insert(name.clone(), format!("{ns}::{name}"));
        }

        let mut imports: HashMap<String, String> = HashMap::new();
        let mut aliases: HashMap<String, usize> = HashMap::new();
        for stmt in &m.program.body.stmts {
            let StmtKind::Import {
                path,
                names,
                alias,
            } = &stmt.kind
            else {
                continue;
            };
            let target_path = m
                .import_targets
                .get(path)
                .ok_or_else(|| format!("internal: unresolved import `{path}`"))?;
            let target = *path_to_idx
                .get(target_path)
                .ok_or_else(|| format!("internal: module `{path}` was not collected"))?;
            let target_ns = &namespaces[target];
            match names {
                Some(list) => {
                    for name in list {
                        match defs[target].get(name) {
                            None => {
                                return Err(format!(
                                    "module `{path}` has no top-level name `{name}`"
                                ));
                            }
                            Some(false) => {
                                return Err(format!(
                                    "`{name}` is private in module `{path}` (mark it `pub`)"
                                ));
                            }
                            Some(true) => {}
                        }
                        let mangled = format!("{target_ns}::{name}");
                        if let Some(prev) = imports.insert(name.clone(), mangled.clone()) {
                            if prev != mangled {
                                return Err(format!(
                                    "import of `{name}` in `{}` conflicts with another import",
                                    m.path.display()
                                ));
                            }
                        }
                    }
                }
                None => {
                    let key = match alias {
                        Some(a) => a.clone(),
                        None => target_ns.clone(),
                    };
                    aliases.insert(key, target);
                    if alias.is_none() {
                        for (name, public) in &defs[target] {
                            if !public {
                                continue;
                            }
                            let mangled = format!("{target_ns}::{name}");
                            if let Some(prev) = imports.insert(name.clone(), mangled.clone()) {
                                if prev != mangled {
                                    return Err(format!(
                                        "`{name}` imported from multiple modules in `{}`; use `as` to disambiguate",
                                        m.path.display()
                                    ));
                                }
                            }
                        }
                    }
                }
            }
        }

        let ctx = Ctx {
            rename,
            imports,
            namespaces: aliases.clone(),
        };
        let resolver = Resolver {
            namespaces: namespaces.clone(),
            defs: defs.clone(),
        };
        let mut scope: Vec<HashSet<String>> = vec![HashSet::new()];
        let (stmts, tail, tail_line) = rewrite_program(&ctx, &resolver, &m.program, &mut scope)?;

        merged_stmts.extend(stmts);
        if i + 1 == count {
            entry_tail = tail;
            entry_tail_line = tail_line;
        } else if let Some(expr) = tail {
            merged_stmts.push(Stmt::new(
                StmtKind::Expr { expr, semi: true },
                tail_line,
            ));
        }
    }

    Ok(Program::new(Block::new(
        merged_stmts,
        entry_tail,
        entry_tail_line,
    )))
}

fn rewrite_program(
    ctx: &Ctx,
    r: &Resolver,
    program: &Program,
    scope: &mut Vec<HashSet<String>>,
) -> Result<(Vec<Stmt>, Option<Expr>, u32), String> {
    let mut out = Vec::new();
    for stmt in &program.body.stmts {
        if let Some(stmt) = rewrite_stmt(ctx, r, stmt, scope, true)? {
            out.push(stmt);
        }
    }
    let tail = match &program.body.tail {
        Some(expr) => Some(rewrite_expr(ctx, r, expr, scope)?),
        None => None,
    };
    Ok((out, tail, program.body.tail_line))
}

/// Rewrite a statement. Returns `None` for consumed `import` declarations.
fn rewrite_stmt(
    ctx: &Ctx,
    r: &Resolver,
    stmt: &Stmt,
    scope: &mut Vec<HashSet<String>>,
    top_level: bool,
) -> Result<Option<Stmt>, String> {
    let kind = match &stmt.kind {
        StmtKind::Import { .. } => return Ok(None),
        StmtKind::Fun {
            name,
            params,
            body,
            public,
            type_params,
            ret,
        } => {
            let bound = if top_level {
                ctx.rename
                    .get(name)
                    .cloned()
                    .unwrap_or_else(|| name.clone())
            } else {
                name.clone()
            };
            scope.push(params.iter().map(|p| p.name.clone()).collect());
            let body = rewrite_block(ctx, r, body, scope)?;
            scope.pop();
            StmtKind::Fun {
                name: bound,
                params: params.clone(),
                body,
                public: *public,
                type_params: type_params.clone(),
                ret: ret.clone(),
            }
        }
        StmtKind::Let {
            name,
            mutable,
            type_hint,
            value,
            public,
        } => {
            let value = match value {
                Some(expr) => Some(rewrite_expr(ctx, r, expr, scope)?),
                None => None,
            };
            if top_level {
                let bound = ctx
                    .rename
                    .get(name)
                    .cloned()
                    .unwrap_or_else(|| name.clone());
                StmtKind::Let {
                    name: bound,
                    mutable: *mutable,
                    type_hint: type_hint.clone(),
                    value,
                    public: *public,
                }
            } else {
                scope.last_mut().unwrap().insert(name.clone());
                StmtKind::Let {
                    name: name.clone(),
                    mutable: *mutable,
                    type_hint: type_hint.clone(),
                    value,
                    public: *public,
                }
            }
        }
        StmtKind::While { cond, body } => {
            let cond = rewrite_expr(ctx, r, cond, scope)?;
            let body = rewrite_block(ctx, r, body, scope)?;
            StmtKind::While { cond, body }
        }
        StmtKind::For {
            name,
            iterable,
            body,
        } => {
            let iterable = rewrite_expr(ctx, r, iterable, scope)?;
            scope.push(HashSet::from([name.clone()]));
            let body = rewrite_block(ctx, r, body, scope)?;
            scope.pop();
            StmtKind::For {
                name: name.clone(),
                iterable,
                body,
            }
        }
        StmtKind::Return(value) => {
            let value = match value {
                Some(expr) => Some(rewrite_expr(ctx, r, expr, scope)?),
                None => None,
            };
            StmtKind::Return(value)
        }
        StmtKind::Break => StmtKind::Break,
        StmtKind::Continue => StmtKind::Continue,
        StmtKind::Block(block) => {
            scope.push(HashSet::new());
            let block = rewrite_block(ctx, r, block, scope)?;
            scope.pop();
            StmtKind::Block(block)
        }
        StmtKind::Expr { expr, semi } => StmtKind::Expr {
            expr: rewrite_expr(ctx, r, expr, scope)?,
            semi: *semi,
        },
    };
    Ok(Some(Stmt::new(kind, stmt.line)))
}

fn rewrite_block(
    ctx: &Ctx,
    r: &Resolver,
    block: &Block,
    scope: &mut Vec<HashSet<String>>,
) -> Result<Block, String> {
    scope.push(HashSet::new());
    let mut stmts = Vec::new();
    for stmt in &block.stmts {
        if let Some(stmt) = rewrite_stmt(ctx, r, stmt, scope, false)? {
            stmts.push(stmt);
        }
    }
    let tail = match &block.tail {
        Some(expr) => Some(Box::new(rewrite_expr(ctx, r, expr, scope)?)),
        None => None,
    };
    scope.pop();
    Ok(Block {
        stmts,
        tail,
        tail_line: block.tail_line,
    })
}

fn is_local(scope: &[HashSet<String>], name: &str) -> bool {
    scope.iter().rev().any(|s| s.contains(name))
}

fn resolve_name(ctx: &Ctx, scope: &[HashSet<String>], name: &str) -> String {
    if is_local(scope, name) {
        return name.to_string();
    }
    if let Some(m) = ctx.rename.get(name) {
        return m.clone();
    }
    if let Some(m) = ctx.imports.get(name) {
        return m.clone();
    }
    name.to_string()
}

/// If `target` is a bare namespace alias and `member` is one of its exported
/// top-level names, return the mangled `ns::member`. Errors when the alias
/// refers to a real module but the member is private or absent.
fn namespaced_member(
    ctx: &Ctx,
    r: &Resolver,
    scope: &[HashSet<String>],
    target: &Expr,
    member: &str,
) -> Result<Option<String>, String> {
    if let Expr::Variable(a) = target {
        if !is_local(scope, a) {
            if let Some(&idx) = ctx.namespaces.get(a) {
                return match r.defs[idx].get(member) {
                    Some(true) => Ok(Some(format!("{}::{}", r.namespaces[idx], member))),
                    Some(false) => Err(format!(
                        "`{member}` is private in module `{a}` (mark it `pub`)"
                    )),
                    None => Err(format!("module `{a}` has no top-level name `{member}`")),
                };
            }
        }
    }
    Ok(None)
}

fn rewrite_expr(
    ctx: &Ctx,
    r: &Resolver,
    expr: &Expr,
    scope: &mut Vec<HashSet<String>>,
) -> Result<Expr, String> {
    Ok(match expr {
        Expr::Literal(l) => Expr::Literal(l.clone()),
        Expr::Variable(name) => Expr::Variable(resolve_name(ctx, scope, name)),
        Expr::Assign { name, value } => Expr::Assign {
            name: resolve_name(ctx, scope, name),
            value: Box::new(rewrite_expr(ctx, r, value, scope)?),
        },
        Expr::SetIndex {
            target,
            index,
            value,
        } => Expr::SetIndex {
            target: Box::new(rewrite_expr(ctx, r, target, scope)?),
            index: Box::new(rewrite_expr(ctx, r, index, scope)?),
            value: Box::new(rewrite_expr(ctx, r, value, scope)?),
        },
        Expr::SetProp {
            target,
            name,
            value,
        } => {
            if let Some(mangled) = namespaced_member(ctx, r, scope, target, name)? {
                Expr::Assign {
                    name: mangled,
                    value: Box::new(rewrite_expr(ctx, r, value, scope)?),
                }
            } else {
                Expr::SetProp {
                    target: Box::new(rewrite_expr(ctx, r, target, scope)?),
                    name: name.clone(),
                    value: Box::new(rewrite_expr(ctx, r, value, scope)?),
                }
            }
        }
        Expr::Unary { op, right } => Expr::Unary {
            op: *op,
            right: Box::new(rewrite_expr(ctx, r, right, scope)?),
        },
        Expr::Try { expr } => Expr::Try {
            expr: Box::new(rewrite_expr(ctx, r, expr, scope)?),
        },
        Expr::Binary { op, left, right } => Expr::Binary {
            op: *op,
            left: Box::new(rewrite_expr(ctx, r, left, scope)?),
            right: Box::new(rewrite_expr(ctx, r, right, scope)?),
        },
        Expr::Logical { op, left, right } => Expr::Logical {
            op: *op,
            left: Box::new(rewrite_expr(ctx, r, left, scope)?),
            right: Box::new(rewrite_expr(ctx, r, right, scope)?),
        },
        Expr::Pipe { left, right } => Expr::Pipe {
            left: Box::new(rewrite_expr(ctx, r, left, scope)?),
            right: Box::new(rewrite_expr(ctx, r, right, scope)?),
        },
        Expr::NilCoalesce { left, right } => Expr::NilCoalesce {
            left: Box::new(rewrite_expr(ctx, r, left, scope)?),
            right: Box::new(rewrite_expr(ctx, r, right, scope)?),
        },
        Expr::Call { callee, args } => Expr::Call {
            callee: Box::new(rewrite_expr(ctx, r, callee, scope)?),
            args: args
                .iter()
                .map(|a| rewrite_expr(ctx, r, a, scope))
                .collect::<Result<_, _>>()?,
        },
        Expr::Index { target, index } => Expr::Index {
            target: Box::new(rewrite_expr(ctx, r, target, scope)?),
            index: Box::new(rewrite_expr(ctx, r, index, scope)?),
        },
        Expr::Get { target, name } => {
            if let Some(mangled) = namespaced_member(ctx, r, scope, target, name)? {
                Expr::Variable(mangled)
            } else {
                Expr::Get {
                    target: Box::new(rewrite_expr(ctx, r, target, scope)?),
                    name: name.clone(),
                }
            }
        }
        Expr::SafeGet { target, name } => Expr::SafeGet {
            target: Box::new(rewrite_expr(ctx, r, target, scope)?),
            name: name.clone(),
        },
        Expr::List(items) => Expr::List(
            items
                .iter()
                .map(|e| rewrite_expr(ctx, r, e, scope))
                .collect::<Result<_, _>>()?,
        ),
        Expr::Map(entries) => Expr::Map(
            entries
                .iter()
                .map(|(k, v)| Ok((rewrite_expr(ctx, r, k, scope)?, rewrite_expr(ctx, r, v, scope)?)))
                .collect::<Result<_, String>>()?,
        ),
        Expr::If {
            cond,
            then_branch,
            else_branch,
        } => Expr::If {
            cond: Box::new(rewrite_expr(ctx, r, cond, scope)?),
            then_branch: Box::new(rewrite_block(ctx, r, then_branch, scope)?),
            else_branch: match else_branch {
                Some(b) => Some(Box::new(rewrite_block(ctx, r, b, scope)?)),
                None => None,
            },
        },
        Expr::Unless {
            cond,
            body,
            else_branch,
        } => Expr::Unless {
            cond: Box::new(rewrite_expr(ctx, r, cond, scope)?),
            body: Box::new(rewrite_block(ctx, r, body, scope)?),
            else_branch: match else_branch {
                Some(b) => Some(Box::new(rewrite_block(ctx, r, b, scope)?)),
                None => None,
            },
        },
        Expr::May { body, fallback } => Expr::May {
            body: Box::new(rewrite_block(ctx, r, body, scope)?),
            fallback: match fallback {
                Some(b) => Some(Box::new(rewrite_block(ctx, r, b, scope)?)),
                None => None,
            },
        },
        Expr::Block(block) => Expr::Block(rewrite_block(ctx, r, block, scope)?),
        Expr::Match { scrutinee, arms } => {
            let scrutinee = Box::new(rewrite_expr(ctx, r, scrutinee, scope)?);
            let mut new_arms = Vec::with_capacity(arms.len());
            for arm in arms {
                scope.push(HashSet::new());
                if let Pattern::Binding(name) = &arm.pattern {
                    scope.last_mut().unwrap().insert(name.clone());
                }
                let guard = match &arm.guard {
                    Some(g) => Some(rewrite_expr(ctx, r, g, scope)?),
                    None => None,
                };
                let body = rewrite_expr(ctx, r, &arm.body, scope)?;
                scope.pop();
                new_arms.push(MatchArm {
                    pattern: arm.pattern.clone(),
                    guard,
                    body,
                });
            }
            Expr::Match {
                scrutinee,
                arms: new_arms,
            }
        }
        Expr::Lambda { params, body } => {
            scope.push(params.iter().map(|p| p.name.clone()).collect());
            let body = rewrite_block(ctx, r, body, scope)?;
            scope.pop();
            Expr::Lambda {
                params: params.clone(),
                body: Box::new(body),
            }
        }
        Expr::Range {
            start,
            end,
            inclusive,
        } => Expr::Range {
            start: Box::new(rewrite_expr(ctx, r, start, scope)?),
            end: Box::new(rewrite_expr(ctx, r, end, scope)?),
            inclusive: *inclusive,
        },
    })
}

/// The file stem of a path, used to derive a default namespace.
#[allow(dead_code)]
pub fn stem_of(path: &Path) -> String {
    path.file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("module")
        .to_string()
}
