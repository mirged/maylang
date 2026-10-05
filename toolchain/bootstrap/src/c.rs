//! GNU C emission. Variables captured by closures are shared heap cells.
use may_ast::*;
use std::collections::{HashMap, HashSet};

#[path = "../../legacy-rust/crates/may_native/src/capture.rs"]
mod capture;

pub fn quote(s: &str) -> String {
    let mut out = String::from("\"");
    for b in s.bytes() {
        out.push_str(&format!("\\{b:03o}"));
    }
    out.push('"');
    out
}

#[derive(Default)]
struct C {
    next: usize,
    globals: HashMap<String, String>,
    scopes: Vec<HashMap<String, String>>,
    captured: HashSet<String>,
    functions: Vec<String>,
    prototypes: Vec<String>,
    loops: Vec<String>,
}

impl C {
    fn id(&mut self) -> String {
        self.next += 1;
        format!("v{}", self.next)
    }
    fn pointer(&self, name: &str) -> Option<String> {
        self.scopes
            .iter()
            .rev()
            .find_map(|s| s.get(name))
            .or_else(|| self.globals.get(name))
            .cloned()
    }
    fn binding(&mut self, name: &str, value: &str) -> String {
        let id = self.id();
        self.scopes
            .last_mut()
            .unwrap()
            .insert(name.into(), id.clone());
        if self.captured.contains(name) {
            format!("V *{id}=cell({value});\n")
        } else {
            format!("V {id}_value={value}; V *{id}=&{id}_value;\n")
        }
    }
    fn function(&mut self, params: &[Param], body: &Block) -> String {
        let id = self.id();
        let mut captures: Vec<_> = capture::free_vars(params, body)
            .into_iter()
            .filter_map(|n| {
                self.scopes
                    .iter()
                    .rev()
                    .find_map(|s| s.get(&n))
                    .map(|p| (n, p.clone()))
            })
            .collect();
        captures.sort();
        let outer_scopes = std::mem::take(&mut self.scopes);
        let outer_captured = std::mem::replace(&mut self.captured, capture::captured_names(body));
        let outer_loops = std::mem::take(&mut self.loops);
        self.scopes.push(HashMap::new());
        for (i, (name, _)) in captures.iter().enumerate() {
            self.scopes[0].insert(name.clone(), format!("cap[{i}]"));
        }
        self.prototypes
            .push(format!("static V {id}(V **cap, int argc, V *args);\n"));
        let mut code =
            format!("static V {id}(V **cap, int argc, V *args) {{ Handler *saved=handler;\n");
        for (i, param) in params.iter().enumerate() {
            code.push_str(&self.binding(&param.name, &format!("args[{i}]")));
        }
        code.push_str(&self.block(body, true));
        code.push_str("}\n");
        self.functions.push(code);
        self.scopes = outer_scopes;
        self.captured = outer_captured;
        self.loops = outer_loops;
        let pointers = captures
            .iter()
            .map(|(_, p)| p.as_str())
            .collect::<Vec<_>>()
            .join(",");
        format!(
            "closure({id},{},{},(V*[]){{{pointers}}})",
            params.len(),
            captures.len()
        )
    }
    fn block(&mut self, b: &Block, returns: bool) -> String {
        self.scopes.push(HashMap::new());
        let mut out = String::new();
        for s in &b.stmts {
            out.push_str(&self.stmt(s));
        }
        let tail = b
            .tail
            .as_ref()
            .map(|e| self.expr(e))
            .unwrap_or_else(|| "nil".into());
        if returns {
            out.push_str(&format!("V result={tail}; handler=saved; return result;\n"));
        } else {
            out.push_str(&format!("{tail};\n"));
        }
        self.scopes.pop();
        out
    }
    fn block_expr(&mut self, b: &Block) -> String {
        format!("({{ {} }})", self.block(b, false))
    }
    fn stmt(&mut self, s: &Stmt) -> String {
        match &s.kind {
            StmtKind::Let {
                name,
                value,
                mutable,
                ..
            } => {
                let value = value
                    .as_ref()
                    .map(|v| self.expr(v))
                    .unwrap_or_else(|| "nil".into());
                if self.scopes.is_empty() {
                    format!("*{}={value};\n", self.globals[name])
                } else {
                    // Mutable values must also survive setjmp/longjmp.
                    if *mutable {
                        self.captured.insert(name.clone());
                    }
                    self.binding(name, &value)
                }
            }
            StmtKind::Fun {
                name, params, body, ..
            } => {
                if self.scopes.is_empty() {
                    let value = self.function(params, body);
                    format!("*{}={value};\n", self.globals[name])
                } else {
                    // A nested function can capture its own binding for recursion.
                    self.captured.insert(name.clone());
                    let binding = self.binding(name, "nil");
                    let value = self.function(params, body);
                    format!("{binding} *{}={value};\n", self.pointer(name).unwrap())
                }
            }
            StmtKind::Expr { expr, .. } => format!("{};\n", self.expr(expr)),
            StmtKind::Block(b) => format!("{{ {} }}\n", self.block(b, false)),
            StmtKind::Return(e) => {
                let value = e
                    .as_ref()
                    .map(|e| self.expr(e))
                    .unwrap_or_else(|| "nil".into());
                format!("{{ V result={value}; handler=saved; return result; }}\n")
            }
            StmtKind::While { cond, body } => {
                let cond = self.expr(cond);
                let h = self.id();
                self.loops.push(h.clone());
                let body = self.block(body, false);
                self.loops.pop();
                format!("{{ Handler *{h}=handler; while(truth({cond})) {{ {body} }} }}\n")
            }
            StmtKind::For {
                name,
                iterable,
                body,
            } => {
                let iterable = self.expr(iterable);
                let list = self.id();
                let i = self.id();
                let h = self.id();
                self.scopes.push(HashMap::new());
                let binding = self.binding(name, &format!("iter({list},{i})"));
                self.loops.push(h.clone());
                let body = self.block(body, false);
                self.loops.pop();
                self.scopes.pop();
                format!("{{ V {list}={iterable}; Handler *{h}=handler; for(size_t {i}=0; {i}<length({list}); ++{i}) {{ {binding} {body} }} }}\n")
            }
            StmtKind::Break | StmtKind::Continue => {
                let h = self.loops.last().expect("loop control outside a loop");
                let control = if matches!(s.kind, StmtKind::Break) {
                    "break"
                } else {
                    "continue"
                };
                format!("handler={h}; {control};\n")
            }
            StmtKind::Import { .. } => unreachable!("imports expanded by loader"),
        }
    }
    // Evaluate operands explicitly: C function arguments have unspecified order.
    fn invoke(&mut self, function: &str, operands: Vec<String>) -> String {
        let mut code = String::from("({ ");
        let mut names = Vec::new();
        for value in operands {
            let id = self.id();
            code.push_str(&format!("V {id}={value}; "));
            names.push(id);
        }
        code.push_str(&format!("{function}({}); }})", names.join(",")));
        code
    }
    fn array(&mut self, values: &[Expr], prefix: &str) -> String {
        let id = self.id();
        let mut code = format!("({{ V {id}[{}]; ", values.len().max(1));
        for (i, e) in values.iter().enumerate() {
            code.push_str(&format!("{id}[{i}]={}; ", self.expr(e)));
        }
        code.push_str(&format!("{prefix},{},{id}); }})", values.len()));
        code
    }
    fn expr(&mut self, e: &Expr) -> String {
        match e {
            Expr::Literal(l) => match l {
                Literal::Nil => "nil".into(),
                Literal::Bool(b) => format!("boolean({})", i32::from(*b)),
                Literal::Int(n) => format!("integer((int64_t)UINT64_C({}))", *n as u64),
                Literal::Float(n) => format!("floating({n:?})"),
                Literal::Str(s) => format!("S({},{})", quote(s), s.len()),
            },
            Expr::Variable(n) => self
                .pointer(n)
                .map(|p| format!("(*{p})"))
                .unwrap_or_else(|| format!("primitive({})", quote(n))),
            Expr::Assign { name, value } => {
                let value = self.expr(value);
                format!(
                    "(*{}={value})",
                    self.pointer(name).expect("assignment to unknown variable")
                )
            }
            Expr::Unary { op, right } => {
                let right = self.expr(right);
                match op {
                    UnaryOp::Not => format!("boolean(!truth({right}))"),
                    UnaryOp::Neg => format!("negate({right})"),
                }
            }
            Expr::Binary { op, left, right } => {
                let op = match op {
                    BinaryOp::Add => "+",
                    BinaryOp::Sub => "-",
                    BinaryOp::Mul => "*",
                    BinaryOp::Div => "/",
                    BinaryOp::Mod => "%",
                    BinaryOp::Pow => "**",
                    BinaryOp::Eq => "==",
                    BinaryOp::Ne => "!=",
                    BinaryOp::Lt => "<",
                    BinaryOp::Le => "<=",
                    BinaryOp::Gt => ">",
                    BinaryOp::Ge => ">=",
                };
                let a = self.expr(left);
                let b = self.expr(right);
                self.invoke(
                    &format!(
                        "binary_{}",
                        match op {
                            "+" => "add",
                            "-" => "sub",
                            "*" => "mul",
                            "/" => "div",
                            "%" => "mod",
                            "**" => "pow",
                            "==" => "eq",
                            "!=" => "ne",
                            "<" => "lt",
                            "<=" => "le",
                            ">" => "gt",
                            _ => "ge",
                        }
                    ),
                    vec![a, b],
                )
            }
            Expr::Logical { op, left, right } => {
                let a = self.expr(left);
                let b = self.expr(right);
                format!(
                    "boolean(truth({a}) {} truth({b}))",
                    if *op == LogicalOp::And { "&&" } else { "||" }
                )
            }
            Expr::NilCoalesce { left, right } => {
                let a = self.expr(left);
                let b = self.expr(right);
                let id = self.id();
                format!("({{ V {id}={a}; {id}.tag==2 ? {b} : {id}; }})")
            }
            Expr::Call { callee, args } => {
                let callee = self.expr(callee);
                let id = self.id();
                let call = self.array(args, &format!("call({id}"));
                format!("({{ V {id}={callee}; {call}; }})")
            }
            Expr::Pipe { left, right } => {
                let mut args = vec![(**left).clone()];
                let callee = if let Expr::Call { callee, args: rest } = &**right {
                    args.extend(rest.clone());
                    (**callee).clone()
                } else {
                    (**right).clone()
                };
                self.expr(&Expr::Call {
                    callee: Box::new(callee),
                    args,
                })
            }
            Expr::List(items) => self.array(items, "list(5"),
            Expr::Map(entries) => {
                let items = entries
                    .iter()
                    .flat_map(|(k, v)| [k.clone(), v.clone()])
                    .collect::<Vec<_>>();
                self.array(&items, "list(7")
            }
            Expr::Index {
                target,
                index: get_index,
            } => {
                let a = self.expr(target);
                let b = self.expr(get_index);
                self.invoke("get_index", vec![a, b])
            }
            Expr::Get { target, name } | Expr::SafeGet { target, name } => {
                let a = self.expr(target);
                let key = format!("S({},{})", quote(name), name.len());
                self.invoke(
                    if matches!(e, Expr::SafeGet { .. }) {
                        "safe_index"
                    } else {
                        "get_index"
                    },
                    vec![a, key],
                )
            }
            Expr::SetIndex {
                target,
                index: get_index,
                value,
            } => {
                let a = self.expr(target);
                let b = self.expr(get_index);
                let c = self.expr(value);
                self.invoke("set_index", vec![a, b, c])
            }
            Expr::SetProp {
                target,
                name,
                value,
            } => {
                let a = self.expr(target);
                let b = format!("S({},{})", quote(name), name.len());
                let c = self.expr(value);
                self.invoke("set_index", vec![a, b, c])
            }
            Expr::Block(b) => self.block_expr(b),
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
                let cond = self.expr(cond);
                let a = self.block_expr(then_branch);
                let b = else_branch
                    .as_ref()
                    .map(|b| self.block_expr(b))
                    .unwrap_or_else(|| "nil".into());
                format!(
                    "({}truth({cond}) ? {a} : {b})",
                    if matches!(e, Expr::Unless { .. }) {
                        "!"
                    } else {
                        ""
                    }
                )
            }
            Expr::Lambda { params, body } => self.function(params, body),
            Expr::Range {
                start,
                end,
                inclusive,
            } => {
                let a = self.expr(start);
                let b = self.expr(end);
                self.invoke(
                    if *inclusive {
                        "range_inclusive"
                    } else {
                        "range_exclusive"
                    },
                    vec![a, b],
                )
            }
            Expr::May { body, fallback } => {
                let id = self.id();
                let a = self.block_expr(body);
                self.scopes
                    .push(HashMap::from([("err".into(), format!("&{id}->error"))]));
                let b = fallback
                    .as_ref()
                    .map(|b| self.block_expr(b))
                    .unwrap_or_else(|| "nil".into());
                self.scopes.pop();
                format!("({{ Handler *{id}=allocate(sizeof(Handler)); {id}->previous=handler; handler={id}; V result; if(setjmp({id}->jump)==0) {{ result={a}; }} else {{ handler={id}->previous; result={b}; }} handler={id}->previous; result; }})")
            }
            Expr::Try { expr } => {
                let value = self.expr(expr);
                let id = self.id();
                format!("({{ V {id}={value}; V ok=safe_index({id},S(\"ok\",2)); if({id}.tag==2 || (ok.tag!=2 && !truth(ok))) {{ handler=saved; return {id}; }} safe_index({id},S(\"value\",5)); }})")
            }
            Expr::Match { scrutinee, arms } => {
                let value = self.expr(scrutinee);
                let id = self.id();
                let result = self.id();
                let mut code = format!("({{ V {id}={value}, {result}=nil; int matched=0; ");
                for arm in arms {
                    self.scopes.push(HashMap::new());
                    let (condition, binding) = match &arm.pattern {
                        Pattern::Wildcard => ("1".into(), String::new()),
                        Pattern::Binding(n) => ("1".into(), self.binding(n, &id)),
                        Pattern::Literal(l) => (
                            format!("equal({id},{})", self.expr(&Expr::Literal(l.clone()))),
                            String::new(),
                        ),
                    };
                    let guard = arm
                        .guard
                        .as_ref()
                        .map(|g| format!("truth({})", self.expr(g)))
                        .unwrap_or_else(|| "1".into());
                    let value = self.expr(&arm.body);
                    code.push_str(&format!("if(!matched && ({condition})) {{ {binding} if({guard}) {{ matched=1; {result}={value}; }} }} "));
                    self.scopes.pop();
                }
                code.push_str(&format!("{result}; }})"));
                code
            }
        }
    }
}

pub fn emit(program: &Program) -> String {
    let mut c = C::default();
    let mut globals = String::new();
    for s in &program.body.stmts {
        if let StmtKind::Let { name, .. } | StmtKind::Fun { name, .. } = &s.kind {
            let id = c.id();
            globals.push_str(&format!(
                "static V {id}_value; static V *{id}=&{id}_value;\n"
            ));
            c.globals.insert(name.clone(), id);
        }
    }
    let mut initializers = String::new();
    let mut main = String::new();
    for s in &program.body.stmts {
        let code = c.stmt(s);
        if matches!(s.kind, StmtKind::Fun { .. }) {
            initializers.push_str(&code);
        } else {
            main.push_str(&code);
        }
    }
    format!("{}\n{globals}\n{}\n{}\nint main(int argc,char **argv) {{ process_argc=argc; process_argv=argv; Handler *saved=handler; {initializers} {main} return 0; }}\n",include_str!("runtime.c"),c.prototypes.join(""),c.functions.join(""))
}
