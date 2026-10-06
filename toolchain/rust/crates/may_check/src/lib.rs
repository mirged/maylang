//! A gradual, unification-based static checker for Maylang.
//!
//! The runtime is dynamically typed and heavily overloaded, so this pass is
//! deliberately permissive: anything it cannot determine is `Any`, which
//! unifies with everything and never produces a diagnostic. It reports definite
//! mistakes and uses HM-style unification to check parametric types and generic
//! function calls:
//!
//! * reassigning an immutable `let`,
//! * `break`/`continue` outside a loop, `return` outside a function,
//! * arithmetic/comparison between definitely-incompatible operands,
//! * calling something that is definitely not callable, wrong arity,
//! * argument/return types that cannot unify with the declared signature,
//! * mismatches between a `let` annotation and its initializer.

use std::collections::HashMap;

use may_ast::*;

#[derive(Debug, Clone, PartialEq)]
pub enum Ty {
    Int,
    Float,
    Str,
    Bool,
    Nil,
    List(Box<Ty>),
    Map(Box<Ty>, Box<Ty>),
    Option(Box<Ty>),
    Fn(Vec<Ty>, Box<Ty>),
    /// An inference variable.
    Var(u32),
    /// Unknown / unprovable; unifies with anything.
    Any,
}

impl Ty {
    fn is_any(&self) -> bool {
        matches!(self, Ty::Any)
    }
    fn is_numeric(&self) -> bool {
        matches!(self, Ty::Int | Ty::Float)
    }
    fn name(&self) -> String {
        match self {
            Ty::Int => "Int".into(),
            Ty::Float => "Float".into(),
            Ty::Str => "Str".into(),
            Ty::Bool => "Bool".into(),
            Ty::Nil => "Nil".into(),
            Ty::List(t) => format!("List<{}>", t.name()),
            Ty::Map(k, v) => format!("Map<{}, {}>", k.name(), v.name()),
            Ty::Option(t) => format!("{}?", t.name()),
            Ty::Fn(p, r) => format!(
                "({}) -> {}",
                p.iter().map(Ty::name).collect::<Vec<_>>().join(", "),
                r.name()
            ),
            Ty::Var(_) => "_".into(),
            Ty::Any => "Any".into(),
        }
    }
}

#[derive(Clone)]
struct Scheme {
    vars: Vec<u32>,
    ty: Ty,
}

#[derive(Default)]
pub struct Diagnostics {
    pub errors: Vec<String>,
}

impl Diagnostics {
    fn error(&mut self, line: u32, message: impl Into<String>) {
        self.errors.push(format!("line {line}: {}", message.into()));
    }
}

/// Check a whole (already resolved) program. Returns diagnostics.
pub fn check(program: &Program) -> Diagnostics {
    let mut cx = Cx {
        diags: Diagnostics::default(),
        subst: HashMap::new(),
        next_var: 0,
        scopes: vec![HashMap::new()],
        schemes: HashMap::new(),
        in_loop: 0,
        in_fn: false,
    };

    // Pass 1: signatures for every top-level function (so calls can be checked
    // regardless of declaration order), and fresh types for globals.
    for stmt in &program.body.stmts {
        match &stmt.kind {
            StmtKind::Fun {
                name,
                params,
                type_params,
                ret,
                ..
            } => {
                let scheme = build_scheme(&mut cx, type_params, params, ret.as_deref());
                cx.schemes.insert(name.clone(), scheme);
            }
            StmtKind::Let {
                name,
                mutable,
                type_hint,
                ..
            } => {
                let ty = type_hint
                    .as_deref()
                    .map(|s| parse_type(s, &HashMap::new()))
                    .unwrap_or(Ty::Any);
                cx.scopes[0].insert(name.clone(), (ty, *mutable));
            }
            _ => {}
        }
    }

    // Pass 2: bodies and top-level statements, in program order.
    for stmt in &program.body.stmts {
        match &stmt.kind {
            StmtKind::Fun {
                name,
                params,
                body,
                type_params,
                ret,
                ..
            } => {
                let scheme = cx.schemes.get(name).cloned().unwrap();
                let erase: HashMap<String, Ty> =
                    type_params.iter().map(|t| (t.clone(), Ty::Any)).collect();
                cx.scopes.push(HashMap::new());
                for (i, p) in params.iter().enumerate() {
                    let ty = p
                        .type_hint
                        .as_deref()
                        .map(|s| parse_type(s, &erase))
                        .unwrap_or_else(|| scheme.param(i));
                    cx.declare(&p.name, ty, true);
                }
                let saved_fn = cx.in_fn;
                let saved_loop = cx.in_loop;
                cx.in_fn = true;
                cx.in_loop = 0;
                let body_ty = cx.block_ty(body);
                cx.in_fn = saved_fn;
                cx.in_loop = saved_loop;
                cx.scopes.pop();
                let declared_ret = match ret {
                    Some(r) => parse_type(r, &erase),
                    None => scheme.ret(),
                };
                cx.expect(&declared_ret, &body_ty, stmt.line, "return type");
            }
            StmtKind::Let { name, value, .. } => {
                if let Some(v) = value {
                    let ty = cx.expr(v, stmt.line);
                    if let Some((ann, mut_)) = cx.scopes[0].get(name).cloned() {
                        if !ann.is_any() {
                            cx.expect(&ann, &ty, stmt.line, "initializer");
                            cx.scopes[0].insert(name.clone(), (ann, mut_));
                        } else {
                            cx.scopes[0].insert(name.clone(), (ty, mut_));
                        }
                    }
                }
            }
            StmtKind::Import { .. } => {}
            other => cx.stmt(&Stmt::new(other.clone(), stmt.line)),
        }
    }

    if let Some(tail) = &program.body.tail {
        cx.expr(tail, program.body.tail_line);
    }

    cx.diags
}

struct Cx {
    diags: Diagnostics,
    subst: HashMap<u32, Ty>,
    next_var: u32,
    scopes: Vec<HashMap<String, (Ty, bool)>>,
    schemes: HashMap<String, Scheme>,
    in_loop: u32,
    in_fn: bool,
}

impl Scheme {
    fn param(&self, i: usize) -> Ty {
        match &self.ty {
            Ty::Fn(p, _) => p.get(i).cloned().unwrap_or(Ty::Any),
            _ => Ty::Any,
        }
    }
    fn ret(&self) -> Ty {
        match &self.ty {
            Ty::Fn(_, r) => (**r).clone(),
            _ => Ty::Any,
        }
    }
}

fn build_scheme(
    cx: &mut Cx,
    type_params: &[String],
    params: &[Param],
    ret: Option<&str>,
) -> Scheme {
    let mut vars = Vec::new();
    let mut map: HashMap<String, Ty> = HashMap::new();
    for t in type_params {
        let v = cx.fresh();
        vars.push(match v {
            Ty::Var(id) => id,
            _ => 0,
        });
        map.insert(t.clone(), v);
    }
    let param_tys = params
        .iter()
        .map(|p| {
            p.type_hint
                .as_deref()
                .map(|s| parse_type(s, &map))
                .unwrap_or(Ty::Any)
        })
        .collect();
    // Without an explicit `->`, the return type is an inference variable that
    // the body constrains, so call sites still see a useful type.
    let ret_ty = ret
        .map(|s| parse_type(s, &map))
        .unwrap_or_else(|| cx.fresh());
    Scheme {
        vars,
        ty: Ty::Fn(param_tys, Box::new(ret_ty)),
    }
}

impl Cx {
    fn fresh(&mut self) -> Ty {
        let id = self.next_var;
        self.next_var += 1;
        Ty::Var(id)
    }

    fn instantiate(&mut self, scheme: &Scheme) -> Ty {
        let mut repl: HashMap<u32, Ty> = HashMap::new();
        for v in &scheme.vars {
            let nv = self.fresh();
            repl.insert(*v, nv);
        }
        substitute(&scheme.ty, &repl)
    }

    fn resolve(&self, ty: &Ty) -> Ty {
        let mut t = ty.clone();
        while let Ty::Var(id) = t {
            match self.subst.get(&id) {
                Some(next) => t = next.clone(),
                None => break,
            }
        }
        t
    }

    fn occurs(&self, id: u32, ty: &Ty) -> bool {
        match self.resolve(ty) {
            Ty::Var(o) => o == id,
            Ty::List(t) | Ty::Option(t) => self.occurs(id, &t),
            Ty::Map(k, v) => self.occurs(id, &k) || self.occurs(id, &v),
            Ty::Fn(p, r) => p.iter().any(|t| self.occurs(id, t)) || self.occurs(id, &r),
            _ => false,
        }
    }

    fn bind(&mut self, id: u32, ty: Ty) -> Result<(), String> {
        if let Ty::Var(o) = self.resolve(&ty) {
            if o == id {
                return Ok(());
            }
        }
        if self.occurs(id, &ty) {
            return Err(format!(
                "cannot construct the infinite type `{}`",
                ty.name()
            ));
        }
        self.subst.insert(id, ty);
        Ok(())
    }

    /// Unify two types, returning an error message on a definite mismatch.
    fn unify(&mut self, a: &Ty, b: &Ty) -> Result<(), String> {
        let a = self.resolve(a);
        let b = self.resolve(b);
        match (a, b) {
            (Ty::Any, _) | (_, Ty::Any) => Ok(()),
            (Ty::Var(x), Ty::Var(y)) if x == y => Ok(()),
            (Ty::Var(x), t) => self.bind(x, t),
            (t, Ty::Var(y)) => self.bind(y, t),
            (Ty::Int, Ty::Int)
            | (Ty::Float, Ty::Float)
            | (Ty::Str, Ty::Str)
            | (Ty::Bool, Ty::Bool)
            | (Ty::Nil, Ty::Nil) => Ok(()),
            (Ty::List(x), Ty::List(y)) | (Ty::Option(x), Ty::Option(y)) => self.unify(&x, &y),
            (Ty::Map(k1, v1), Ty::Map(k2, v2)) => {
                self.unify(&k1, &k2)?;
                self.unify(&v1, &v2)
            }
            (Ty::Fn(p1, r1), Ty::Fn(p2, r2)) if p1.len() == p2.len() => {
                for (x, y) in p1.iter().zip(p2.iter()) {
                    self.unify(x, y)?;
                }
                self.unify(&r1, &r2)
            }
            (x, y) => Err(format!(
                "type mismatch: expected `{}`, found `{}`",
                x.name(),
                y.name()
            )),
        }
    }

    fn expect(&mut self, expected: &Ty, actual: &Ty, line: u32, what: &str) {
        let snapshot = self.subst.clone();
        if let Err(msg) = self.unify(expected, actual) {
            self.subst = snapshot;
            self.diags.error(line, format!("{what} {msg}"));
        }
    }

    fn declare(&mut self, name: &str, ty: Ty, mutable: bool) {
        self.scopes
            .last_mut()
            .unwrap()
            .insert(name.into(), (ty, mutable));
    }

    fn lookup(&self, name: &str) -> Option<Ty> {
        self.scopes
            .iter()
            .rev()
            .find_map(|s| s.get(name).map(|(t, _)| t.clone()))
    }

    fn block(&mut self, block: &Block) {
        self.scopes.push(HashMap::new());
        for stmt in &block.stmts {
            self.stmt(stmt);
        }
        if let Some(tail) = &block.tail {
            self.expr(tail, block.tail_line);
        }
        self.scopes.pop();
    }

    fn block_ty(&mut self, block: &Block) -> Ty {
        self.scopes.push(HashMap::new());
        for stmt in &block.stmts {
            self.stmt(stmt);
        }
        let ty = match &block.tail {
            Some(t) => self.expr(t, block.tail_line),
            None => Ty::Any,
        };
        self.scopes.pop();
        ty
    }

    fn stmt(&mut self, stmt: &Stmt) {
        let line = stmt.line;
        match &stmt.kind {
            StmtKind::Let {
                name,
                mutable,
                type_hint,
                value,
                ..
            } => {
                let ann = type_hint
                    .as_deref()
                    .map(|s| parse_type(s, &HashMap::new()))
                    .unwrap_or(Ty::Any);
                let ty = match value {
                    Some(v) => {
                        let vt = self.expr(v, line);
                        self.expect(&ann, &vt, line, "initializer");
                        if ann.is_any() {
                            vt
                        } else {
                            ann
                        }
                    }
                    None => ann,
                };
                self.declare(name, ty, *mutable);
            }
            StmtKind::Fun {
                name,
                params,
                body,
                type_params,
                ..
            } => {
                let erase: HashMap<String, Ty> =
                    type_params.iter().map(|t| (t.clone(), Ty::Any)).collect();
                let mut ptypes = Vec::new();
                self.scopes.push(HashMap::new());
                for p in params {
                    let ty = p
                        .type_hint
                        .as_deref()
                        .map(|s| parse_type(s, &erase))
                        .unwrap_or(Ty::Any);
                    ptypes.push(ty.clone());
                    self.declare(&p.name, ty, true);
                }
                let saved_fn = self.in_fn;
                let saved_loop = self.in_loop;
                self.in_fn = true;
                self.in_loop = 0;
                self.block(body);
                self.in_fn = saved_fn;
                self.in_loop = saved_loop;
                self.scopes.pop();
                self.declare(name, Ty::Fn(ptypes, Box::new(Ty::Any)), false);
            }
            StmtKind::While { cond, body } => {
                self.expr(cond, line);
                self.in_loop += 1;
                self.block(body);
                self.in_loop -= 1;
            }
            StmtKind::For {
                name,
                iterable,
                body,
            } => {
                let tmp = self.expr(iterable, line);
                let it = self.resolve(&tmp);
                let elem = match it {
                    Ty::List(inner) => *inner,
                    _ => Ty::Any,
                };
                self.in_loop += 1;
                self.scopes.push(HashMap::new());
                self.declare(name, elem, true);
                for s in &body.stmts {
                    self.stmt(s);
                }
                if let Some(t) = &body.tail {
                    self.expr(t, body.tail_line);
                }
                self.scopes.pop();
                self.in_loop -= 1;
            }
            StmtKind::Return(value) => {
                if !self.in_fn {
                    self.diags.error(line, "`return` outside a function");
                }
                if let Some(v) = value {
                    self.expr(v, line);
                }
            }
            StmtKind::Break => {
                if self.in_loop == 0 {
                    self.diags.error(line, "`break` outside a loop");
                }
            }
            StmtKind::Continue => {
                if self.in_loop == 0 {
                    self.diags.error(line, "`continue` outside a loop");
                }
            }
            StmtKind::Block(block) => self.block(block),
            StmtKind::Import { .. } => {}
            StmtKind::Expr { expr, .. } => {
                self.expr(expr, line);
            }
        }
    }

    fn expr(&mut self, expr: &Expr, line: u32) -> Ty {
        match expr {
            Expr::Literal(l) => match l {
                Literal::Nil => Ty::Nil,
                Literal::Bool(_) => Ty::Bool,
                Literal::Int(_) => Ty::Int,
                Literal::Float(_) => Ty::Float,
                Literal::Str(_) => Ty::Str,
            },
            Expr::Variable(name) => {
                if let Some(t) = self.lookup(name) {
                    return t;
                }
                if let Some(scheme) = self.schemes.get(name).cloned() {
                    return self.instantiate(&scheme);
                }
                Ty::Any
            }
            Expr::Assign { name, value } => {
                let vt = self.expr(value, line);
                let found = self
                    .scopes
                    .iter()
                    .rev()
                    .find_map(|s| s.get(name).cloned());
                if let Some((ann, mutable)) = found {
                    if !mutable {
                        let short = name.rsplit("::").next().unwrap_or(name);
                        self.diags
                            .error(line, format!("cannot assign to immutable `{short}`"));
                    }
                    self.expect(&ann, &vt, line, "assignment");
                }
                vt
            }
            Expr::SetIndex {
                target,
                index,
                value,
            } => {
                let ttv = self.expr(target, line);
                let itv = self.expr(index, line);
                let vt = self.expr(value, line);
                let tt = self.resolve(&ttv);
                let it = self.resolve(&itv);
                match tt {
                    Ty::List(elem) => {
                        self.expect(&Ty::Int, &it, line, "index");
                        self.expect(&elem, &vt, line, "element");
                    }
                    Ty::Map(k, v) => {
                        self.expect(&k, &it, line, "key");
                        self.expect(&v, &vt, line, "value");
                    }
                    _ => {}
                }
                Ty::Any
            }
            Expr::SetProp { target, value, .. } => {
                self.expr(target, line);
                self.expr(value, line);
                Ty::Any
            }
            Expr::Try { expr } => {
                self.expr(expr, line);
                Ty::Any
            }
            Expr::Unary { op, right } => {
                let rtv = self.expr(right, line);
                let rt = self.resolve(&rtv);
                match op {
                    UnaryOp::Neg => {
                        if !rt.is_any() && !rt.is_numeric() && !matches!(rt, Ty::Var(_)) {
                            self.diags
                                .error(line, format!("cannot negate `{}`", rt.name()));
                        }
                        rt
                    }
                    UnaryOp::Not => Ty::Bool,
                }
            }
            Expr::Binary { op, left, right } => {
                let ltv = self.expr(left, line);
                let rtv = self.expr(right, line);
                let lt = self.resolve(&ltv);
                let rt = self.resolve(&rtv);
                self.binary(*op, &lt, &rt, line)
            }
            Expr::Logical { .. } => {
                if let Expr::Logical { left, right, .. } = expr {
                    self.expr(left, line);
                    self.expr(right, line);
                }
                Ty::Bool
            }
            Expr::NilCoalesce { left, right } => {
                self.expr(left, line);
                self.expr(right, line)
            }
            Expr::Pipe { left, right } => {
                let lt = self.expr(left, line);
                match right.as_ref() {
                    Expr::Call { callee, args } => {
                        self.report_call(callee, args, line, Some(lt))
                    }
                    Expr::Variable(name) => {
                        let callee = Expr::Variable(name.clone());
                        self.report_call(&callee, &[], line, Some(lt))
                    }
                    _ => Ty::Any,
                }
            }
            Expr::Call { callee, args } => self.report_call(callee, args, line, None),
            Expr::Index { target, index } => {
                let ttv2 = self.expr(target, line);
                let itv2 = self.expr(index, line);
                let tt = self.resolve(&ttv2);
                let it = self.resolve(&itv2);
                match tt {
                    Ty::List(inner) => {
                        self.expect(&Ty::Int, &it, line, "index");
                        *inner
                    }
                    Ty::Map(_, v) => *v,
                    Ty::Str => Ty::Str,
                    _ => Ty::Any,
                }
            }
            Expr::Get { target, .. } | Expr::SafeGet { target, .. } => {
                self.expr(target, line);
                Ty::Any
            }
            Expr::List(items) => {
                let elem = self.fresh();
                for it in items {
                    let t = self.expr(it, line);
                    let _ = self.unify(&elem, &t);
                }
                Ty::List(Box::new(elem))
            }
            Expr::Map(entries) => {
                let k = self.fresh();
                let v = self.fresh();
                for (key, value) in entries {
                    let kt = self.expr(key, line);
                    let vt = self.expr(value, line);
                    let _ = self.unify(&k, &kt);
                    let _ = self.unify(&v, &vt);
                }
                Ty::Map(Box::new(k), Box::new(v))
            }
            Expr::If {
                cond,
                then_branch,
                else_branch,
            } => {
                self.expr(cond, line);
                let tt = self.block_ty(then_branch);
                match else_branch {
                    Some(b) => {
                        let et = self.block_ty(b);
                        let _ = self.unify(&tt, &et);
                        tt
                    }
                    None => Ty::Any,
                }
            }
            Expr::Unless {
                cond,
                body,
                else_branch,
            } => {
                self.expr(cond, line);
                let tt = self.block_ty(body);
                match else_branch {
                    Some(b) => {
                        let et = self.block_ty(b);
                        let _ = self.unify(&tt, &et);
                        tt
                    }
                    None => Ty::Any,
                }
            }
            Expr::May { body, fallback } => {
                let bt = self.block_ty(body);
                match fallback {
                    Some(b) => {
                        let ft = self.block_ty(b);
                        let _ = self.unify(&bt, &ft);
                        bt
                    }
                    None => bt,
                }
            }
            Expr::Block(block) => self.block_ty(block),
            Expr::Match { scrutinee, arms } => {
                self.expr(scrutinee, line);
                let result = self.fresh();
                for arm in arms {
                    self.scopes.push(HashMap::new());
                    if let Pattern::Binding(n) = &arm.pattern {
                        self.declare(n, Ty::Any, true);
                    }
                    if let Some(g) = &arm.guard {
                        self.expr(g, line);
                    }
                    let bt = self.expr(&arm.body, line);
                    let _ = self.unify(&result, &bt);
                    self.scopes.pop();
                }
                result
            }
            Expr::Lambda { params, body } => {
                self.scopes.push(HashMap::new());
                let mut ptypes = Vec::new();
                for p in params {
                    let ty = p
                        .type_hint
                        .as_deref()
                        .map(|s| parse_type(s, &HashMap::new()))
                        .unwrap_or_else(|| self.fresh());
                    ptypes.push(ty.clone());
                    self.declare(&p.name, ty, true);
                }
                let saved_fn = self.in_fn;
                let saved_loop = self.in_loop;
                self.in_fn = true;
                self.in_loop = 0;
                let rt = self.block_ty(body);
                self.in_fn = saved_fn;
                self.in_loop = saved_loop;
                self.scopes.pop();
                Ty::Fn(ptypes, Box::new(rt))
            }
            Expr::Range { start, end, .. } => {
                self.expr(start, line);
                self.expr(end, line);
                Ty::List(Box::new(Ty::Int))
            }
        }
    }

    fn report_call(
        &mut self,
        callee: &Expr,
        args: &[Expr],
        line: u32,
        piped: Option<Ty>,
    ) -> Ty {
        let ctv = self.expr(callee, line);
        let ct = self.resolve(&ctv);
        let mut arg_tys: Vec<Ty> = Vec::new();
        if let Some(t) = piped {
            arg_tys.push(t);
        }
        for a in args {
            arg_tys.push(self.expr(a, line));
        }
        match ct {
            Ty::Fn(params, ret) => {
                if params.len() != arg_tys.len() {
                    self.diags.error(
                        line,
                        format!(
                            "function expects {} argument(s), got {}",
                            params.len(),
                            arg_tys.len()
                        ),
                    );
                    return Ty::Any;
                }
                for (i, (p, a)) in params.iter().zip(arg_tys.iter()).enumerate() {
                    let snapshot = self.subst.clone();
                    if self.unify(p, a).is_err() {
                        self.subst = snapshot;
                        let pp = self.resolve(p);
                        let aa = self.resolve(a);
                        self.diags.error(
                            line,
                            format!(
                                "argument {} type mismatch: expected `{}`, found `{}`",
                                i + 1,
                                pp.name(),
                                aa.name()
                            ),
                        );
                    }
                }
                *ret
            }
            Ty::Any | Ty::Var(_) => Ty::Any,
            Ty::List(_) | Ty::Map(_, _) => Ty::Any,
            other => {
                self.diags.error(
                    line,
                    format!("cannot call a value of type `{}`", other.name()),
                );
                Ty::Any
            }
        }
    }

    fn binary(&mut self, op: BinaryOp, lt: &Ty, rt: &Ty, line: u32) -> Ty {
        use BinaryOp::*;
        match op {
            Add => {
                if lt.is_any() || rt.is_any() || matches!(lt, Ty::Var(_)) || matches!(rt, Ty::Var(_))
                {
                    return Ty::Any;
                }
                if matches!(lt, Ty::Str) || matches!(rt, Ty::Str) {
                    return Ty::Str;
                }
                if let (Ty::List(a), Ty::List(b)) = (lt, rt) {
                    let elem = (**a).clone();
                    let _ = self.unify(&elem, b);
                    return Ty::List(Box::new(elem));
                }
                if lt.is_numeric() && rt.is_numeric() {
                    return numeric(lt, rt);
                }
                self.diags.error(
                    line,
                    format!("cannot add `{}` and `{}`", lt.name(), rt.name()),
                );
                Ty::Any
            }
            Sub | Mul | Div | Mod | Pow => {
                if lt.is_any() || rt.is_any() || matches!(lt, Ty::Var(_)) || matches!(rt, Ty::Var(_))
                {
                    return Ty::Any;
                }
                if lt.is_numeric() && rt.is_numeric() {
                    return numeric(lt, rt);
                }
                self.diags.error(
                    line,
                    format!(
                        "operator requires numbers, got `{}` and `{}`",
                        lt.name(),
                        rt.name()
                    ),
                );
                Ty::Any
            }
            Eq | Ne | Lt | Le | Gt | Ge => {
                if !lt.is_any()
                    && !rt.is_any()
                    && !matches!(lt, Ty::Var(_))
                    && !matches!(rt, Ty::Var(_))
                    && !comparable(lt, rt)
                {
                    self.diags.error(
                        line,
                        format!("cannot compare `{}` and `{}`", lt.name(), rt.name()),
                    );
                }
                Ty::Bool
            }
        }
    }
}

fn numeric(a: &Ty, b: &Ty) -> Ty {
    if matches!(a, Ty::Float) || matches!(b, Ty::Float) {
        Ty::Float
    } else {
        Ty::Int
    }
}

fn comparable(a: &Ty, b: &Ty) -> bool {
    if a.is_numeric() && b.is_numeric() {
        return true;
    }
    a == b
}

fn substitute(ty: &Ty, repl: &HashMap<u32, Ty>) -> Ty {
    match ty {
        Ty::Var(id) => repl.get(id).cloned().unwrap_or(Ty::Var(*id)),
        Ty::List(t) => Ty::List(Box::new(substitute(t, repl))),
        Ty::Option(t) => Ty::Option(Box::new(substitute(t, repl))),
        Ty::Map(k, v) => Ty::Map(
            Box::new(substitute(k, repl)),
            Box::new(substitute(v, repl)),
        ),
        Ty::Fn(p, r) => Ty::Fn(
            p.iter().map(|t| substitute(t, repl)).collect(),
            Box::new(substitute(r, repl)),
        ),
        other => other.clone(),
    }
}

/// Parse a canonical type string (as produced by the parser) into a [`Ty`].
/// Unknown identifiers become `Any`; `generics` maps type-parameter names.
pub fn parse_type(s: &str, generics: &HashMap<String, Ty>) -> Ty {
    let s = s.trim();
    if let Some(inner) = s.strip_suffix('?') {
        return Ty::Option(Box::new(parse_type(inner, generics)));
    }
    // Function types: `(A,B)->C`
    if let Some(idx) = find_arrow(s) {
        let (params, ret) = s.split_at(idx);
        let params = params.trim();
        let ret = &ret[2..];
        let inner = params
            .strip_prefix('(')
            .and_then(|p| p.strip_suffix(')'))
            .unwrap_or(params);
        let ptypes = if inner.trim().is_empty() {
            Vec::new()
        } else {
            split_top(inner, ',')
                .iter()
                .map(|p| parse_type(p, generics))
                .collect()
        };
        return Ty::Fn(ptypes, Box::new(parse_type(ret, generics)));
    }
    if let Some(lt) = s.find('<') {
        if let Some(gt) = s.rfind('>') {
            if gt > lt {
                let name = s[..lt].trim();
                let args = split_top(&s[lt + 1..gt], ',');
                let arg_tys: Vec<Ty> = args.iter().map(|a| parse_type(a, generics)).collect();
                return match name {
                    "List" | "Iterable" => {
                        Ty::List(Box::new(arg_tys.into_iter().next().unwrap_or(Ty::Any)))
                    }
                    "Option" => Ty::Option(Box::new(
                        arg_tys.into_iter().next().unwrap_or(Ty::Any),
                    )),
                    "Map" => {
                        let mut it = arg_tys.into_iter();
                        let k = it.next().unwrap_or(Ty::Any);
                        let v = it.next().unwrap_or(Ty::Any);
                        Ty::Map(Box::new(k), Box::new(v))
                    }
                    _ => Ty::Any,
                };
            }
        }
    }
    if let Some(t) = generics.get(s) {
        return t.clone();
    }
    match s {
        "Int" | "Integer" => Ty::Int,
        "Float" => Ty::Float,
        "Str" | "String" => Ty::Str,
        "Bool" => Ty::Bool,
        "Nil" => Ty::Nil,
        "List" => Ty::List(Box::new(Ty::Any)),
        "Map" => Ty::Map(Box::new(Ty::Any), Box::new(Ty::Any)),
        "Function" | "Fn" => Ty::Fn(Vec::new(), Box::new(Ty::Any)),
        _ => Ty::Any,
    }
}

fn find_arrow(s: &str) -> Option<usize> {
    let bytes = s.as_bytes();
    let mut depth = 0i32;
    let mut i = 0;
    while i + 1 < bytes.len() {
        match bytes[i] {
            b'<' | b'(' => depth += 1,
            b'>' | b')' => depth -= 1,
            b'-' if bytes[i + 1] == b'>' && depth == 0 => return Some(i),
            _ => {}
        }
        i += 1;
    }
    None
}

fn split_top(s: &str, sep: char) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut cur = String::new();
    for c in s.chars() {
        match c {
            '<' | '(' => {
                depth += 1;
                cur.push(c);
            }
            '>' | ')' => {
                depth -= 1;
                cur.push(c);
            }
            c if c == sep && depth == 0 => {
                out.push(cur.trim().to_string());
                cur.clear();
            }
            c => cur.push(c),
        }
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    out
}
