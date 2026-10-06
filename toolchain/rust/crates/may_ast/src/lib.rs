//! Abstract Syntax Tree for Maylang.
//!
//! The tree is deliberately simple: an expression-oriented core with a handful
//! of statement forms layered on top. Optional type hints (`let x: Int = 1`)
//! are preserved so tooling can use them, but the runtime ignores them.

/// A parsed source file: a sequence of statements with an optional trailing
/// expression (the value of the program).
#[derive(Debug, Clone, PartialEq)]
pub struct Program {
    pub body: Block,
}

impl Program {
    pub fn new(body: Block) -> Self {
        Program { body }
    }
}

/// An expression-oriented block: statements plus an optional result.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Block {
    pub stmts: Vec<Stmt>,
    pub tail: Option<Box<Expr>>,
    /// Source line of the trailing expression (0 when there is none).
    pub tail_line: u32,
}

impl Block {
    pub fn new(stmts: Vec<Stmt>, tail: Option<Expr>, tail_line: u32) -> Self {
        Block {
            stmts,
            tail: tail.map(Box::new),
            tail_line,
        }
    }
}

/// A function parameter with an optional type hint.
#[derive(Debug, Clone, PartialEq)]
pub struct Param {
    pub name: String,
    pub type_hint: Option<String>,
}

/// A statement plus its source line.
#[derive(Debug, Clone, PartialEq)]
pub struct Stmt {
    pub kind: StmtKind,
    pub line: u32,
}

impl Stmt {
    pub fn new(kind: StmtKind, line: u32) -> Self {
        Stmt { kind, line }
    }
}

/// Statements.
#[derive(Debug, Clone, PartialEq)]
pub enum StmtKind {
    /// `let x = e;` / `mut x: Int = e;`
    Let {
        name: String,
        mutable: bool,
        type_hint: Option<String>,
        value: Option<Expr>,
        /// `pub let x = e;` — exported for `from ... import` / qualified access.
        public: bool,
    },
    /// `fun name(params) { body }`
    Fun {
        name: String,
        params: Vec<Param>,
        body: Block,
        /// `pub fun name(...)` — exported for `from ... import` / qualified access.
        public: bool,
        /// Generic type parameters: `fun name<T, U>(...)`.
        type_params: Vec<String>,
        /// Optional declared return type: `fun name(...) -> T { ... }`.
        ret: Option<String>,
    },
    /// `while (cond) { body }`
    While { cond: Expr, body: Block },
    /// `for name in iterable { body }`
    For {
        name: String,
        iterable: Expr,
        body: Block,
    },
    /// `return e;`
    Return(Option<Expr>),
    /// `break;`
    Break,
    /// `continue;`
    Continue,
    /// A nested block used as a statement.
    Block(Block),
    /// `import "path";`, `import "path" as name;` or `from "path" import a, b;`
    Import {
        path: String,
        names: Option<Vec<String>>,
        /// Namespace alias for `import "path" as name;` (qualified access only).
        alias: Option<String>,
    },
    /// An expression used as a statement. `semi` records whether it was
    /// terminated by `;` (relevant for block tail detection).
    Expr { expr: Expr, semi: bool },
}

/// Literals.
#[derive(Debug, Clone, PartialEq)]
pub enum Literal {
    Nil,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
}

/// Unary operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnaryOp {
    Neg,
    Not,
}

/// Binary operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinaryOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Pow,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

/// A pattern in a `match` expression.
#[derive(Debug, Clone, PartialEq)]
pub enum Pattern {
    /// `_` — matches anything, binds nothing.
    Wildcard,
    /// A literal constant.
    Literal(Literal),
    /// An identifier: matches anything and binds the value.
    Binding(String),
}

/// One arm of a `match` expression.
#[derive(Debug, Clone, PartialEq)]
pub struct MatchArm {
    pub pattern: Pattern,
    pub guard: Option<Expr>,
    pub body: Expr,
}

/// Short-circuiting boolean operators.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogicalOp {
    And,
    Or,
}

/// Expressions.
#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    Literal(Literal),
    Variable(String),
    Assign {
        name: String,
        value: Box<Expr>,
    },
    SetIndex {
        target: Box<Expr>,
        index: Box<Expr>,
        value: Box<Expr>,
    },
    SetProp {
        target: Box<Expr>,
        name: String,
        value: Box<Expr>,
    },
    Unary {
        op: UnaryOp,
        right: Box<Expr>,
    },
    Binary {
        op: BinaryOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
    Logical {
        op: LogicalOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
    /// `left |> right` — inserts `left` as the first argument of `right`.
    Pipe {
        left: Box<Expr>,
        right: Box<Expr>,
    },
    /// `left ?? right` — yields `right` when `left` is nil.
    NilCoalesce {
        left: Box<Expr>,
        right: Box<Expr>,
    },
    /// `expr?` — error propagation for `{ok, value, error}` results: yields
    /// `value` when `ok` is truthy/absent, otherwise returns the operand
    /// (or `nil`) from the enclosing function.
    Try {
        expr: Box<Expr>,
    },
    Call {
        callee: Box<Expr>,
        args: Vec<Expr>,
    },
    Index {
        target: Box<Expr>,
        index: Box<Expr>,
    },
    Get {
        target: Box<Expr>,
        name: String,
    },
    /// `target?.name` — yields nil instead of faulting when `target` is nil.
    SafeGet {
        target: Box<Expr>,
        name: String,
    },
    List(Vec<Expr>),
    Map(Vec<(Expr, Expr)>),
    If {
        cond: Box<Expr>,
        then_branch: Box<Block>,
        else_branch: Option<Box<Block>>,
    },
    Unless {
        cond: Box<Expr>,
        body: Box<Block>,
        else_branch: Option<Box<Block>>,
    },
    /// `may { body } [otherwise { fallback }]`.
    ///
    /// With no fallback, a fault yields `nil`.
    May {
        body: Box<Block>,
        fallback: Option<Box<Block>>,
    },
    /// A block used in expression position.
    Block(Block),
    /// `match (scrutinee) { pat => expr, ... }`
    Match {
        scrutinee: Box<Expr>,
        arms: Vec<MatchArm>,
    },
    Lambda {
        params: Vec<Param>,
        body: Box<Block>,
    },
    Range {
        start: Box<Expr>,
        end: Box<Expr>,
        inclusive: bool,
    },
}

impl Expr {
    pub fn int(v: i64) -> Expr {
        Expr::Literal(Literal::Int(v))
    }
    pub fn var(name: impl Into<String>) -> Expr {
        Expr::Variable(name.into())
    }
}
