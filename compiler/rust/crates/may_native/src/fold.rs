//! Constant folding: a small, semantics-preserving optimiser pass that runs
//! after modules are merged and before code generation.
//!
//! Only folds operations whose result is a literal and cannot change runtime
//! behaviour. In particular, integer results outside the 61-bit immediate range
//! and division by zero are left alone so the runtime still raises the same
//! catchable faults.

use may_ast::*;

/// Fold constants throughout a program in place.
pub fn fold_program(program: &mut Program) {
    fold_block(&mut program.body);
}

fn fold_block(block: &mut Block) {
    for stmt in &mut block.stmts {
        fold_stmt(stmt);
    }
    if let Some(tail) = &mut block.tail {
        fold_expr(tail);
    }
}

fn fold_stmt(stmt: &mut Stmt) {
    match &mut stmt.kind {
        StmtKind::Let { value, .. } => {
            if let Some(v) = value {
                fold_expr(v);
            }
        }
        StmtKind::Fun { body, .. } => fold_block(body),
        StmtKind::While { cond, body } => {
            fold_expr(cond);
            fold_block(body);
        }
        StmtKind::For { iterable, body, .. } => {
            fold_expr(iterable);
            fold_block(body);
        }
        StmtKind::Return(value) => {
            if let Some(v) = value {
                fold_expr(v);
            }
        }
        StmtKind::Break | StmtKind::Continue | StmtKind::Import { .. } => {}
        StmtKind::Block(block) => fold_block(block),
        StmtKind::Expr { expr, .. } => fold_expr(expr),
    }
}

fn fold_expr(expr: &mut Expr) {
    // Recurse first (bottom-up).
    match expr {
        Expr::Literal(_) | Expr::Variable(_) => {}
        Expr::Assign { value, .. } => fold_expr(value),
        Expr::SetIndex { target, index, value } => {
            fold_expr(target);
            fold_expr(index);
            fold_expr(value);
        }
        Expr::SetProp { target, value, .. } => {
            fold_expr(target);
            fold_expr(value);
        }
        Expr::Unary { right, .. } => fold_expr(right),
        Expr::Try { expr } => fold_expr(expr),
        Expr::Binary { left, right, .. }
        | Expr::Logical { left, right, .. }
        | Expr::NilCoalesce { left, right }
        | Expr::Pipe { left, right } => {
            fold_expr(left);
            fold_expr(right);
        }
        Expr::Call { callee, args } => {
            fold_expr(callee);
            for a in args {
                fold_expr(a);
            }
        }
        Expr::Index { target, index } => {
            fold_expr(target);
            fold_expr(index);
        }
        Expr::Get { target, .. } | Expr::SafeGet { target, .. } => fold_expr(target),
        Expr::List(items) => {
            for it in items {
                fold_expr(it);
            }
        }
        Expr::Map(entries) => {
            for (k, v) in entries {
                fold_expr(k);
                fold_expr(v);
            }
        }
        Expr::If {
            cond,
            then_branch,
            else_branch,
        } => {
            fold_expr(cond);
            fold_block(then_branch);
            if let Some(b) = else_branch {
                fold_block(b);
            }
        }
        Expr::Unless {
            cond,
            body,
            else_branch,
        } => {
            fold_expr(cond);
            fold_block(body);
            if let Some(b) = else_branch {
                fold_block(b);
            }
        }
        Expr::May { body, fallback } => {
            fold_block(body);
            if let Some(b) = fallback {
                fold_block(b);
            }
        }
        Expr::Block(block) => fold_block(block),
        Expr::Match { scrutinee, arms } => {
            fold_expr(scrutinee);
            for arm in arms {
                if let Some(g) = &mut arm.guard {
                    fold_expr(g);
                }
                fold_expr(&mut arm.body);
            }
        }
        Expr::Lambda { body, .. } => fold_block(body),
        Expr::Range { start, end, .. } => {
            fold_expr(start);
            fold_expr(end);
        }
    }

    // Then try to fold this node.
    if let Some(folded) = try_fold(expr) {
        *expr = folded;
    }
}

fn try_fold(expr: &Expr) -> Option<Expr> {
    match expr {
        Expr::Unary { op, right } => {
            if let Expr::Literal(l) = right.as_ref() {
                match (op, l) {
                    (UnaryOp::Neg, Literal::Int(v)) if in_range(v.checked_neg()?) => {
                        Some(Expr::Literal(Literal::Int(v.checked_neg()?)))
                    }
                    (UnaryOp::Neg, Literal::Float(v)) => {
                        Some(Expr::Literal(Literal::Float(-v)))
                    }
                    (UnaryOp::Not, Literal::Bool(b)) => Some(Expr::Literal(Literal::Bool(!b))),
                    (UnaryOp::Not, Literal::Nil) => Some(Expr::Literal(Literal::Bool(true))),
                    _ => None,
                }
            } else {
                None
            }
        }
        Expr::Logical { op, left, right } => {
            let (Expr::Literal(a), Expr::Literal(b)) = (left.as_ref(), right.as_ref()) else {
                return None;
            };
            match (op, lit_bool(a), lit_bool(b)) {
                (LogicalOp::And, Some(x), Some(y)) => {
                    Some(Expr::Literal(Literal::Bool(x && y)))
                }
                (LogicalOp::Or, Some(x), Some(y)) => Some(Expr::Literal(Literal::Bool(x || y))),
                _ => None,
            }
        }
        Expr::Binary { op, left, right } => {
            let (Expr::Literal(a), Expr::Literal(b)) = (left.as_ref(), right.as_ref()) else {
                return None;
            };
            fold_binary(*op, a, b)
        }
        _ => None,
    }
}

fn lit_bool(l: &Literal) -> Option<bool> {
    match l {
        Literal::Bool(b) => Some(*b),
        Literal::Nil => Some(false),
        _ => None,
    }
}

fn fold_binary(op: BinaryOp, a: &Literal, b: &Literal) -> Option<Expr> {
    use BinaryOp::*;
    match (a, b) {
        (Literal::Int(x), Literal::Int(y)) => {
            let v = match op {
                Add => x.checked_add(*y)?,
                Sub => x.checked_sub(*y)?,
                Mul => x.checked_mul(*y)?,
                Div => x.checked_div(*y)?,
                Mod => x.checked_rem(*y)?,
                Pow => return None,
                Eq => return bool_lit(x == y),
                Ne => return bool_lit(x != y),
                Lt => return bool_lit(x < y),
                Le => return bool_lit(x <= y),
                Gt => return bool_lit(x > y),
                Ge => return bool_lit(x >= y),
            };
            if in_range(v) {
                Some(Expr::Literal(Literal::Int(v)))
            } else {
                None
            }
        }
        (Literal::Float(x), Literal::Float(y)) => match op {
            Add => Some(Expr::Literal(Literal::Float(x + y))),
            Sub => Some(Expr::Literal(Literal::Float(x - y))),
            Mul => Some(Expr::Literal(Literal::Float(x * y))),
            // Leave division by zero for the runtime fault.
            Div if *y != 0.0 => Some(Expr::Literal(Literal::Float(x / y))),
            Eq => bool_lit(x == y),
            Ne => bool_lit(x != y),
            Lt => bool_lit(x < y),
            Le => bool_lit(x <= y),
            Gt => bool_lit(x > y),
            Ge => bool_lit(x >= y),
            _ => None,
        },
        (Literal::Str(x), Literal::Str(y)) => match op {
            Add => Some(Expr::Literal(Literal::Str(format!("{x}{y}")))),
            Eq => bool_lit(x == y),
            Ne => bool_lit(x != y),
            Lt => bool_lit(x < y),
            Le => bool_lit(x <= y),
            Gt => bool_lit(x > y),
            Ge => bool_lit(x >= y),
            _ => None,
        },
        (Literal::Bool(x), Literal::Bool(y)) => match op {
            Eq => bool_lit(x == y),
            Ne => bool_lit(x != y),
            _ => None,
        },
        (Literal::Nil, Literal::Nil) => match op {
            Eq => bool_lit(true),
            Ne => bool_lit(false),
            _ => None,
        },
        _ => None,
    }
}

fn bool_lit(b: bool) -> Option<Expr> {
    Some(Expr::Literal(Literal::Bool(b)))
}

/// Whether an integer is representable as a tagged immediate (`n << 3`).
fn in_range(v: i64) -> bool {
    const LIMIT: i64 = 1 << 60;
    (-LIMIT..LIMIT).contains(&v)
}
