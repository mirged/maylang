//! Free-variable analysis for native closures.
//!
//! Before compiling a function we need to know which of its locals are captured
//! by nested lambdas / functions, so they can be boxed into heap cells. And when
//! creating a closure we need its list of free variables.

use std::collections::HashSet;

use may_ast::*;

/// Free variables of a lambda/function body, excluding its parameters and any
/// names it binds itself.
pub fn free_vars(params: &[Param], body: &Block) -> HashSet<String> {
    let mut bound: HashSet<String> = params.iter().map(|p| p.name.clone()).collect();
    let mut out = HashSet::new();
    free_block(body, &mut bound, &mut out);
    out
}

/// Names that a function's body captures from its enclosing scope (i.e. the
/// union of the free variables of every nested lambda/function).
pub fn captured_names(body: &Block) -> HashSet<String> {
    let mut out = HashSet::new();
    scan_block(body, &mut out);
    out
}

fn free_block(block: &Block, bound: &mut HashSet<String>, out: &mut HashSet<String>) {
    for stmt in &block.stmts {
        free_stmt(stmt, bound, out);
    }
    if let Some(tail) = &block.tail {
        free_expr(tail, bound, out);
    }
}

fn scoped_block(block: &Block, bound: &HashSet<String>, out: &mut HashSet<String>) {
    let mut inner = bound.clone();
    free_block(block, &mut inner, out);
}

fn free_stmt(stmt: &Stmt, bound: &mut HashSet<String>, out: &mut HashSet<String>) {
    match &stmt.kind {
        StmtKind::Let { name, value, .. } => {
            if let Some(value) = value {
                free_expr(value, bound, out);
            }
            bound.insert(name.clone());
        }
        StmtKind::Fun {
            name, params, body, ..
        } => {
            for v in free_vars(params, body) {
                if !bound.contains(&v) {
                    out.insert(v);
                }
            }
            bound.insert(name.clone());
        }
        StmtKind::While { cond, body } => {
            free_expr(cond, bound, out);
            scoped_block(body, bound, out);
        }
        StmtKind::For {
            name,
            iterable,
            body,
        } => {
            free_expr(iterable, bound, out);
            let mut inner = bound.clone();
            inner.insert(name.clone());
            free_block(body, &mut inner, out);
        }
        StmtKind::Return(value) => {
            if let Some(value) = value {
                free_expr(value, bound, out);
            }
        }
        StmtKind::Break | StmtKind::Continue | StmtKind::Import { .. } => {}
        StmtKind::Block(block) => scoped_block(block, bound, out),
        StmtKind::Expr { expr, .. } => free_expr(expr, bound, out),
    }
}

fn free_expr(expr: &Expr, bound: &HashSet<String>, out: &mut HashSet<String>) {
    match expr {
        Expr::Literal(_) => {}
        Expr::Variable(name) => {
            if !bound.contains(name) {
                out.insert(name.clone());
            }
        }
        Expr::Assign { name, value } => {
            if !bound.contains(name) {
                out.insert(name.clone());
            }
            free_expr(value, bound, out);
        }
        Expr::SetIndex {
            target,
            index,
            value,
        } => {
            free_expr(target, bound, out);
            free_expr(index, bound, out);
            free_expr(value, bound, out);
        }
        Expr::SetProp {
            target,
            name,
            value,
        } => {
            free_expr(target, bound, out);
            if !bound.contains(name) {
                // property names are string keys, not variable reads
            }
            free_expr(value, bound, out);
        }
        Expr::Unary { right, .. } => free_expr(right, bound, out),
        Expr::Try { expr } => free_expr(expr, bound, out),
        Expr::Binary { left, right, .. }
        | Expr::Logical { left, right, .. }
        | Expr::NilCoalesce { left, right }
        | Expr::Pipe { left, right } => {
            free_expr(left, bound, out);
            free_expr(right, bound, out);
        }
        Expr::Call { callee, args } => {
            free_expr(callee, bound, out);
            for arg in args {
                free_expr(arg, bound, out);
            }
        }
        Expr::Index { target, index } => {
            free_expr(target, bound, out);
            free_expr(index, bound, out);
        }
        Expr::Get { target, .. } => free_expr(target, bound, out),
        Expr::SafeGet { target, .. } => free_expr(target, bound, out),
        Expr::List(items) => {
            for item in items {
                free_expr(item, bound, out);
            }
        }
        Expr::Map(entries) => {
            for (key, value) in entries {
                free_expr(key, bound, out);
                free_expr(value, bound, out);
            }
        }
        Expr::If {
            cond,
            then_branch,
            else_branch,
        } => {
            free_expr(cond, bound, out);
            scoped_block(then_branch, bound, out);
            if let Some(block) = else_branch {
                scoped_block(block, bound, out);
            }
        }
        Expr::Unless {
            cond,
            body,
            else_branch,
        } => {
            free_expr(cond, bound, out);
            scoped_block(body, bound, out);
            if let Some(block) = else_branch {
                scoped_block(block, bound, out);
            }
        }
        Expr::May { body, fallback } => {
            scoped_block(body, bound, out);
            if let Some(fallback) = fallback {
                scoped_block(fallback, bound, out);
            }
        }
        Expr::Block(block) => scoped_block(block, bound, out),
        Expr::Match { scrutinee, arms } => {
            free_expr(scrutinee, bound, out);
            for arm in arms {
                let mut inner = bound.clone();
                if let Pattern::Binding(name) = &arm.pattern {
                    inner.insert(name.clone());
                }
                if let Some(guard) = &arm.guard {
                    free_expr(guard, &inner, out);
                }
                free_expr(&arm.body, &inner, out);
            }
        }
        Expr::Lambda { params, body } => {
            for v in free_vars(params, body) {
                if !bound.contains(&v) {
                    out.insert(v);
                }
            }
        }
        Expr::Range { start, end, .. } => {
            free_expr(start, bound, out);
            free_expr(end, bound, out);
        }
    }
}

/// Walk a body looking for nested functionals and union their free variables.
fn scan_block(block: &Block, out: &mut HashSet<String>) {
    for stmt in &block.stmts {
        scan_stmt(stmt, out);
    }
    if let Some(tail) = &block.tail {
        scan_expr(tail, out);
    }
}

fn scan_stmt(stmt: &Stmt, out: &mut HashSet<String>) {
    match &stmt.kind {
        StmtKind::Fun { params, body, .. } => {
            out.extend(free_vars(params, body));
            scan_block(body, out);
        }
        StmtKind::Let { value, .. } => {
            if let Some(value) = value {
                scan_expr(value, out);
            }
        }
        StmtKind::While { cond, body } => {
            scan_expr(cond, out);
            scan_block(body, out);
        }
        StmtKind::For { iterable, body, .. } => {
            scan_expr(iterable, out);
            scan_block(body, out);
        }
        StmtKind::Return(value) => {
            if let Some(value) = value {
                scan_expr(value, out);
            }
        }
        StmtKind::Break | StmtKind::Continue | StmtKind::Import { .. } => {}
        StmtKind::Block(block) => scan_block(block, out),
        StmtKind::Expr { expr, .. } => scan_expr(expr, out),
    }
}

fn scan_expr(expr: &Expr, out: &mut HashSet<String>) {
    match expr {
        Expr::Lambda { params, body } => {
            out.extend(free_vars(params, body));
            scan_block(body, out);
        }
        Expr::Literal(_) | Expr::Variable(_) => {}
        Expr::Assign { value, .. } => scan_expr(value, out),
        Expr::SetIndex {
            target,
            index,
            value,
        } => {
            scan_expr(target, out);
            scan_expr(index, out);
            scan_expr(value, out);
        }
        Expr::SetProp { target, value, .. } => {
            scan_expr(target, out);
            scan_expr(value, out);
        }
        Expr::Unary { right, .. } => scan_expr(right, out),
        Expr::Try { expr } => scan_expr(expr, out),
        Expr::Binary { left, right, .. }
        | Expr::Logical { left, right, .. }
        | Expr::NilCoalesce { left, right }
        | Expr::Pipe { left, right } => {
            scan_expr(left, out);
            scan_expr(right, out);
        }
        Expr::Call { callee, args } => {
            scan_expr(callee, out);
            for arg in args {
                scan_expr(arg, out);
            }
        }
        Expr::Index { target, index } => {
            scan_expr(target, out);
            scan_expr(index, out);
        }
        Expr::Get { target, .. } | Expr::SafeGet { target, .. } => scan_expr(target, out),
        Expr::List(items) => {
            for item in items {
                scan_expr(item, out);
            }
        }
        Expr::Map(entries) => {
            for (key, value) in entries {
                scan_expr(key, out);
                scan_expr(value, out);
            }
        }
        Expr::If {
            cond,
            then_branch,
            else_branch,
        }
        | Expr::Unless {
            cond,
            body: then_branch,
            else_branch,
        } => {
            scan_expr(cond, out);
            scan_block(then_branch, out);
            if let Some(block) = else_branch {
                scan_block(block, out);
            }
        }
        Expr::May { body, fallback } => {
            scan_block(body, out);
            if let Some(fallback) = fallback {
                scan_block(fallback, out);
            }
        }
        Expr::Block(block) => scan_block(block, out),
        Expr::Match { scrutinee, arms } => {
            scan_expr(scrutinee, out);
            for arm in arms {
                if let Some(guard) = &arm.guard {
                    scan_expr(guard, out);
                }
                scan_expr(&arm.body, out);
            }
        }
        Expr::Range { start, end, .. } => {
            scan_expr(start, out);
            scan_expr(end, out);
        }
    }
}
