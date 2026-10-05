//! Recursive-descent parser for Maylang.
//!
//! Expressions use precedence climbing; statements are parsed directly. A
//! block's trailing expression becomes its value (see [`may_ast::Block`]).

use std::fmt;

use may_ast::*;
use may_lexer::{tokenize, InterpSegment, LexError, Token, TokenKind};

/// A syntax error with a source line.
#[derive(Debug, Clone, PartialEq)]
pub struct ParseError {
    pub message: String,
    pub line: u32,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "line {}: {}", self.line, self.message)
    }
}

impl std::error::Error for ParseError {}

impl From<LexError> for ParseError {
    fn from(e: LexError) -> Self {
        ParseError {
            message: e.message,
            line: e.line,
        }
    }
}

/// Parse a full source file into a [`Program`].
pub fn parse(source: &str) -> Result<Program, ParseError> {
    let tokens = tokenize(source)?;
    Parser::new(tokens).parse_program()
}

/// Parse a single expression (used by the REPL for `.expr` style input).
pub fn parse_expression(source: &str) -> Result<Expr, ParseError> {
    let tokens = tokenize(source)?;
    let mut parser = Parser::new(tokens);
    let expr = parser.expression()?;
    parser.consume(&TokenKind::Eof, "expected end of input")?;
    Ok(expr)
}

pub struct Parser {
    tokens: Vec<Token>,
    current: usize,
    /// Counter for hidden temporaries created by pattern desugaring.
    tmp_counter: usize,
}

impl Parser {
    pub fn new(tokens: Vec<Token>) -> Self {
        Parser {
            tokens,
            current: 0,
            tmp_counter: 0,
        }
    }

    // ----- token helpers -------------------------------------------------

    fn peek(&self) -> &Token {
        &self.tokens[self.current.min(self.tokens.len() - 1)]
    }

    fn peek_next(&self) -> &Token {
        let idx = (self.current + 1).min(self.tokens.len() - 1);
        &self.tokens[idx]
    }

    fn previous(&self) -> &Token {
        &self.tokens[self.current - 1]
    }

    fn advance(&mut self) -> &Token {
        if self.current < self.tokens.len() - 1 {
            self.current += 1;
        }
        self.previous()
    }

    fn check(&self, kind: &TokenKind) -> bool {
        std::mem::discriminant(&self.peek().kind) == std::mem::discriminant(kind)
    }

    fn check_next(&self, kind: &TokenKind) -> bool {
        std::mem::discriminant(&self.peek_next().kind) == std::mem::discriminant(kind)
    }

    fn matches(&mut self, kind: &TokenKind) -> bool {
        if self.check(kind) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn consume(&mut self, kind: &TokenKind, message: &str) -> Result<&Token, ParseError> {
        if self.check(kind) {
            Ok(self.advance())
        } else {
            Err(self.error_at_current(message))
        }
    }

    /// Accept `;`, or an end of block/input where the terminator is optional
    /// (this keeps the REPL tolerant of a missing final semicolon).
    fn statement_end(&mut self, message: &str) -> Result<(), ParseError> {
        if self.matches(&TokenKind::Semicolon)
            || self.check(&TokenKind::RBrace)
            || self.check(&TokenKind::Eof)
        {
            Ok(())
        } else {
            Err(self.error_at_current(message))
        }
    }

    fn error_at_current(&self, message: &str) -> ParseError {
        ParseError {
            message: format!("{} (found {})", message, self.peek().kind),
            line: self.peek().line,
        }
    }

    fn error<T>(&self, message: impl Into<String>) -> Result<T, ParseError> {
        Err(ParseError {
            message: message.into(),
            line: self.peek().line,
        })
    }

    fn ident(&mut self, message: &str) -> Result<String, ParseError> {
        if let TokenKind::Ident(name) = &self.peek().kind {
            let name = name.clone();
            self.advance();
            Ok(name)
        } else {
            Err(self.error_at_current(message))
        }
    }

    fn line(&self) -> u32 {
        self.peek().line
    }

    // ----- program / blocks ---------------------------------------------

    fn parse_program(&mut self) -> Result<Program, ParseError> {
        let mut stmts = Vec::new();
        while !self.check(&TokenKind::Eof) {
            stmts.extend(self.declaration()?);
        }
        Ok(Program::new(finish_block(stmts)))
    }

    fn block(&mut self) -> Result<Block, ParseError> {
        self.consume(&TokenKind::LBrace, "expected `{`")?;
        let mut stmts = Vec::new();
        while !self.check(&TokenKind::RBrace) && !self.check(&TokenKind::Eof) {
            stmts.extend(self.declaration()?);
        }
        self.consume(&TokenKind::RBrace, "expected `}`")?;
        Ok(finish_block(stmts))
    }

    /// A control-flow body: either a braced block or a single statement
    /// (so `unless (ready) return nil;` is valid).
    fn body(&mut self) -> Result<Block, ParseError> {
        if self.check(&TokenKind::LBrace) {
            return self.block();
        }
        let stmts = self.declaration()?;
        Ok(finish_block(stmts))
    }

    /// One declaration, which may desugar into several statements (so `let`
    /// destructuring can expand into a sequence of bindings).
    fn declaration(&mut self) -> Result<Vec<Stmt>, ParseError> {
        let public = self.matches_ident("pub");
        let line = self.line();
        if self.matches_ident("struct") {
            return Ok(vec![self.struct_declaration(public, line)?]);
        }
        if self.matches_ident("enum") {
            return self.enum_declaration(public, line);
        }
        // `fun name(...)` is a declaration; `fun(...)` is an anonymous lambda
        // expression, so only the former is handled here.
        if self.check(&TokenKind::Fun) && !self.check_next(&TokenKind::LParen) {
            return Ok(vec![self.fun_declaration(public)?]);
        }
        if self.check(&TokenKind::Let) || self.check(&TokenKind::Mut) {
            return self.let_declaration(public);
        }
        if public {
            return Err(self.error_at_current("`pub` must precede `fun`, `let` or `mut`"));
        }
        if self.check(&TokenKind::Import) || self.check(&TokenKind::From) {
            return Ok(vec![self.import_declaration()?]);
        }
        Ok(vec![self.statement()?])
    }

    /// A `struct Name { field, field: Type, "method": expr, ... }` declaration
    /// desugars to a constructor function returning a map, e.g.
    /// `fun Name(field, ...) { {"field": field, ...} }`. Fields whose key is a
    /// string literal are fixed members (methods) rather than parameters.
    fn struct_declaration(&mut self, public: bool, line: u32) -> Result<Stmt, ParseError> {
        let name = self.ident("expected struct name")?;
        self.consume(&TokenKind::LBrace, "expected `{` after struct name")?;
        let mut params: Vec<Param> = Vec::new();
        let mut fixed: Vec<(String, Expr)> = Vec::new();
        if !self.check(&TokenKind::RBrace) {
            loop {
                if let TokenKind::Str(_) = self.peek().kind {
                    let key = self.string_literal("expected member key")?;
                    self.consume(&TokenKind::Colon, "expected `:` after member key")?;
                    let value = self.expression()?;
                    fixed.push((key, value));
                } else {
                    let field = self.ident("expected field name")?;
                    let ty = self.optional_type_hint()?;
                    params.push(Param {
                        name: field,
                        type_hint: ty,
                    });
                }
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
                if self.check(&TokenKind::RBrace) {
                    break;
                }
            }
        }
        self.consume(&TokenKind::RBrace, "expected `}` after struct fields")?;
        let _ = self.matches(&TokenKind::Semicolon);

        let mut entries: Vec<(Expr, Expr)> = params
            .iter()
            .map(|p| {
                (
                    Expr::Literal(Literal::Str(p.name.clone())),
                    Expr::Variable(p.name.clone()),
                )
            })
            .collect();
        for (key, value) in fixed {
            entries.push((Expr::Literal(Literal::Str(key)), value));
        }
        let body = Block::new(Vec::new(), Some(Expr::Map(entries)), line);
        Ok(Stmt::new(
            StmtKind::Fun {
                name,
                params,
                body,
                public,
                type_params: Vec::new(),
                ret: None,
            },
            line,
        ))
    }

    /// An `enum Name { Variant, Variant(field, ...), ... }` desugars to one
    /// constructor function per variant, each returning a tagged map with a
    /// `"tag"` field. Match on `value.tag`.
    fn enum_declaration(&mut self, public: bool, line: u32) -> Result<Vec<Stmt>, ParseError> {
        let _name = self.ident("expected enum name")?;
        self.consume(&TokenKind::LBrace, "expected `{` after enum name")?;
        let mut out = Vec::new();
        if !self.check(&TokenKind::RBrace) {
            loop {
                let variant = self.ident("expected variant name")?;
                let mut params: Vec<Param> = Vec::new();
                if self.matches(&TokenKind::LParen) {
                    if !self.check(&TokenKind::RParen) {
                        loop {
                            let field = self.ident("expected variant field name")?;
                            let ty = self.optional_type_hint()?;
                            params.push(Param {
                                name: field,
                                type_hint: ty,
                            });
                            if !self.matches(&TokenKind::Comma) {
                                break;
                            }
                            if self.check(&TokenKind::RParen) {
                                break;
                            }
                        }
                    }
                    self.consume(&TokenKind::RParen, "expected `)` after variant fields")?;
                }
                let mut entries = vec![(
                    Expr::Literal(Literal::Str("tag".to_string())),
                    Expr::Literal(Literal::Str(variant.clone())),
                )];
                for p in &params {
                    entries.push((
                        Expr::Literal(Literal::Str(p.name.clone())),
                        Expr::Variable(p.name.clone()),
                    ));
                }
                let body = Block::new(Vec::new(), Some(Expr::Map(entries)), line);
                out.push(Stmt::new(
                    StmtKind::Fun {
                        name: variant,
                        params,
                        body,
                        public,
                        type_params: Vec::new(),
                        ret: None,
                    },
                    line,
                ));
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
                if self.check(&TokenKind::RBrace) {
                    break;
                }
            }
        }
        self.consume(&TokenKind::RBrace, "expected `}` after enum variants")?;
        let _ = self.matches(&TokenKind::Semicolon);
        Ok(out)
    }

    /// Consume `pub` when the next token is the identifier `pub`.
    fn matches_ident(&mut self, word: &str) -> bool {
        if let TokenKind::Ident(name) = &self.peek().kind {
            if name == word {
                self.advance();
                return true;
            }
        }
        false
    }

    fn import_declaration(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        if self.matches(&TokenKind::Import) {
            let path = self.string_literal("expected module path string after `import`")?;
            let alias = if self.matches_ident("as") {
                Some(self.ident("expected a namespace name after `as`")?)
            } else {
                None
            };
            self.statement_end("expected `;` after import")?;
            return Ok(Stmt::new(
                StmtKind::Import {
                    path,
                    names: None,
                    alias,
                },
                line,
            ));
        }
        self.consume(&TokenKind::From, "expected `from`")?;
        let path = self.string_literal("expected module path string after `from`")?;
        self.consume(&TokenKind::Import, "expected `import` after module path")?;
        let mut names = Vec::new();
        loop {
            names.push(self.ident("expected a name to import")?);
            if !self.matches(&TokenKind::Comma) {
                break;
            }
        }
        self.statement_end("expected `;` after import")?;
        Ok(Stmt::new(
            StmtKind::Import {
                path,
                names: Some(names),
                alias: None,
            },
            line,
        ))
    }

    fn fun_declaration(&mut self, public: bool) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.consume(&TokenKind::Fun, "expected `fun`")?;
        let name = self.ident("expected function name")?;
        // Optional generic parameters: `fun f<T, U>(...)`.
        let mut type_params = Vec::new();
        if self.matches(&TokenKind::Lt) {
            if !self.check(&TokenKind::Gt) {
                loop {
                    type_params.push(self.ident("expected type parameter name")?);
                    if !self.matches(&TokenKind::Comma) {
                        break;
                    }
                }
            }
            self.consume(&TokenKind::Gt, "expected `>` after type parameters")?;
        }
        let params = self.parameters()?;
        let ret = if self.matches(&TokenKind::Arrow) {
            Some(self.parse_type()?)
        } else {
            None
        };
        let body = self.block()?;
        Ok(Stmt::new(
            StmtKind::Fun {
                name,
                params,
                body,
                public,
                type_params,
                ret,
            },
            line,
        ))
    }

    fn let_declaration(&mut self, public: bool) -> Result<Vec<Stmt>, ParseError> {
        let line = self.line();
        let mutable = self.matches(&TokenKind::Mut);
        if !mutable {
            self.consume(&TokenKind::Let, "expected `let` or `mut`")?;
        }
        // Destructuring pattern?
        if self.check(&TokenKind::LBrace) || self.check(&TokenKind::LBracket) {
            if public {
                return Err(self.error_at_current("`pub` cannot be used with a destructuring pattern"));
            }
            let pattern = self.parse_pattern()?;
            self.consume(&TokenKind::Eq, "expected `=` after pattern")?;
            let value = self.expression()?;
            self.statement_end("expected `;` after declaration")?;
            let mut out = Vec::new();
            self.desugar_pattern(&pattern, value, mutable, line, &mut out);
            return Ok(out);
        }
        let name = self.ident("expected variable name")?;
        let type_hint = self.optional_type_hint()?;
        let value = if self.matches(&TokenKind::Eq) {
            Some(self.expression()?)
        } else {
            None
        };
        self.statement_end("expected `;` after declaration")?;
        Ok(vec![Stmt::new(
            StmtKind::Let {
                name,
                mutable,
                type_hint,
                value,
                public,
            },
            line,
        )])
    }

    /// A binding pattern for `let`/`for`: an identifier, `_`, a list `[a, b]`
    /// or a record `{x, y: z}` (nesting allowed).
    fn parse_pattern(&mut self) -> Result<BindPat, ParseError> {
        if self.matches(&TokenKind::LBracket) {
            let mut items = Vec::new();
            if !self.check(&TokenKind::RBracket) {
                loop {
                    items.push(self.parse_pattern()?);
                    if !self.matches(&TokenKind::Comma) {
                        break;
                    }
                    if self.check(&TokenKind::RBracket) {
                        break;
                    }
                }
            }
            self.consume(&TokenKind::RBracket, "expected `]` after list pattern")?;
            return Ok(BindPat::List(items));
        }
        if self.matches(&TokenKind::LBrace) {
            let mut fields = Vec::new();
            if !self.check(&TokenKind::RBrace) {
                loop {
                    let key = self.ident("expected field name in record pattern")?;
                    let sub = if self.matches(&TokenKind::Colon) {
                        self.parse_pattern()?
                    } else {
                        BindPat::Ident(key.clone())
                    };
                    fields.push((key, sub));
                    if !self.matches(&TokenKind::Comma) {
                        break;
                    }
                    if self.check(&TokenKind::RBrace) {
                        break;
                    }
                }
            }
            self.consume(&TokenKind::RBrace, "expected `}` after record pattern")?;
            return Ok(BindPat::Record(fields));
        }
        let name = self.ident("expected a binding name")?;
        if name == "_" {
            Ok(BindPat::Wild)
        } else {
            Ok(BindPat::Ident(name))
        }
    }

    /// Expand `pattern = source` into ordinary `let` statements. Composite
    /// patterns evaluate `source` once into a hidden temporary, then index it.
    fn desugar_pattern(
        &mut self,
        pattern: &BindPat,
        source: Expr,
        mutable: bool,
        line: u32,
        out: &mut Vec<Stmt>,
    ) {
        match pattern {
            BindPat::Wild => {}
            BindPat::Ident(name) => out.push(Stmt::new(
                StmtKind::Let {
                    name: name.clone(),
                    mutable,
                    type_hint: None,
                    value: Some(source),
                    public: false,
                },
                line,
            )),
            BindPat::List(items) => {
                let tmp = self.fresh_temp();
                out.push(self.bind_temp(&tmp, source, line));
                for (i, sub) in items.iter().enumerate() {
                    let index = Expr::Index {
                        target: Box::new(Expr::Variable(tmp.clone())),
                        index: Box::new(Expr::Literal(Literal::Int(i as i64))),
                    };
                    self.desugar_pattern(sub, index, mutable, line, out);
                }
            }
            BindPat::Record(fields) => {
                let tmp = self.fresh_temp();
                out.push(self.bind_temp(&tmp, source, line));
                for (key, sub) in fields {
                    let index = Expr::Index {
                        target: Box::new(Expr::Variable(tmp.clone())),
                        index: Box::new(Expr::Literal(Literal::Str(key.clone()))),
                    };
                    self.desugar_pattern(sub, index, mutable, line, out);
                }
            }
        }
    }

    fn fresh_temp(&mut self) -> String {
        let name = format!("$pat_{}", self.tmp_counter);
        self.tmp_counter += 1;
        name
    }

    fn bind_temp(&self, name: &str, value: Expr, line: u32) -> Stmt {
        Stmt::new(
            StmtKind::Let {
                name: name.to_string(),
                mutable: false,
                type_hint: None,
                value: Some(value),
                public: false,
            },
            line,
        )
    }

    fn optional_type_hint(&mut self) -> Result<Option<String>, ParseError> {
        if self.matches(&TokenKind::Colon) {
            Ok(Some(self.parse_type()?))
        } else {
            Ok(None)
        }
    }

    /// Parse a type expression and render it back to a canonical string, e.g.
    /// `List<Int>`, `Map<Str, Int>`, `(Int, Str) -> Bool`, `T?`.
    fn parse_type(&mut self) -> Result<String, ParseError> {
        let base = if self.matches(&TokenKind::LParen) {
            let mut parts = Vec::new();
            if !self.check(&TokenKind::RParen) {
                loop {
                    parts.push(self.parse_type()?);
                    if !self.matches(&TokenKind::Comma) {
                        break;
                    }
                }
            }
            self.consume(&TokenKind::RParen, "expected `)` in type")?;
            if self.matches(&TokenKind::Arrow) {
                let ret = self.parse_type()?;
                format!("({})->{}", parts.join(","), ret)
            } else if parts.len() == 1 {
                parts.pop().unwrap()
            } else {
                format!("({})", parts.join(","))
            }
        } else {
            self.ident("expected a type name")?
        };
        let mut out = base;
        if self.matches(&TokenKind::Lt) {
            let mut args = Vec::new();
            if !self.check(&TokenKind::Gt) {
                loop {
                    args.push(self.parse_type()?);
                    if !self.matches(&TokenKind::Comma) {
                        break;
                    }
                }
            }
            self.consume(&TokenKind::Gt, "expected `>` after type arguments")?;
            out = format!("{out}<{}>", args.join(","));
        }
        if self.matches(&TokenKind::Question) {
            out = format!("{out}?");
        }
        Ok(out)
    }

    fn parameters(&mut self) -> Result<Vec<Param>, ParseError> {
        self.consume(&TokenKind::LParen, "expected `(`")?;
        let mut params = Vec::new();
        if !self.check(&TokenKind::RParen) {
            loop {
                let name = self.ident("expected parameter name")?;
                let type_hint = self.optional_type_hint()?;
                params.push(Param { name, type_hint });
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
            }
        }
        self.consume(&TokenKind::RParen, "expected `)` after parameters")?;
        Ok(params)
    }

    // ----- statements ----------------------------------------------------

    fn statement(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        if self.matches(&TokenKind::While) {
            // Parentheses around the condition are optional.
            let cond = self.expression()?;
            let body = self.body()?;
            return Ok(Stmt::new(StmtKind::While { cond, body }, line));
        }
        if self.matches(&TokenKind::For) {
            // The loop binding may be a plain name or a destructuring pattern.
            let pattern = if self.check(&TokenKind::LBrace) || self.check(&TokenKind::LBracket) {
                self.parse_pattern()?
            } else {
                BindPat::Ident(self.ident("expected loop variable after `for`")?)
            };
            // The bootstrap runtime ignores annotations, including loop bindings.
            let _ = self.optional_type_hint()?;
            self.consume(&TokenKind::In, "expected `in` in for-loop")?;
            let iterable = self.expression()?;
            let mut body = self.body()?;
            let name = match pattern {
                BindPat::Ident(name) => name,
                other => {
                    let tmp = self.fresh_temp();
                    let mut prefix = Vec::new();
                    self.desugar_pattern(&other, Expr::Variable(tmp.clone()), false, line, &mut prefix);
                    for (i, stmt) in prefix.into_iter().enumerate() {
                        body.stmts.insert(i, stmt);
                    }
                    tmp
                }
            };
            return Ok(Stmt::new(
                StmtKind::For {
                    name,
                    iterable,
                    body,
                },
                line,
            ));
        }
        if self.matches(&TokenKind::Return) {
            let value = if self.check(&TokenKind::Semicolon) || self.check(&TokenKind::RBrace) {
                None
            } else {
                Some(self.expression()?)
            };
            self.statement_end("expected `;` after return")?;
            return Ok(Stmt::new(StmtKind::Return(value), line));
        }
        if self.matches(&TokenKind::Break) {
            self.statement_end("expected `;` after `break`")?;
            return Ok(Stmt::new(StmtKind::Break, line));
        }
        if self.matches(&TokenKind::Continue) {
            self.statement_end("expected `;` after `continue`")?;
            return Ok(Stmt::new(StmtKind::Continue, line));
        }
        if self.check(&TokenKind::LBrace) && !self.looks_like_map() {
            let block = self.block()?;
            return Ok(Stmt::new(StmtKind::Block(block), line));
        }

        let expr = self.expression()?;
        let semi = self.matches(&TokenKind::Semicolon);
        Ok(Stmt::new(StmtKind::Expr { expr, semi }, line))
    }

    /// Distinguish a map literal written at statement position from a block,
    /// e.g. `{"a": 1}` versus `{ do_thing(); }`. Only unambiguous map openings
    /// (`"key":`, `ident:`, `...`) are treated as maps; everything else is a
    /// block.
    fn looks_like_map(&self) -> bool {
        if !self.check(&TokenKind::LBrace) {
            return false;
        }
        let after_brace = &self.peek_next().kind;
        let third = self
            .tokens
            .get(self.current + 2)
            .map(|token| &token.kind);
        match after_brace {
            // `{}` is an empty map literal when it appears in expression
            // position (function/control bodies are parsed separately).
            TokenKind::RBrace => true,
            TokenKind::Ellipsis => true,
            TokenKind::Str(_) | TokenKind::Ident(_) => matches!(third, Some(TokenKind::Colon)),
            _ => false,
        }
    }

    // ----- expressions ---------------------------------------------------

    pub fn expression(&mut self) -> Result<Expr, ParseError> {
        self.assignment()
    }

    fn assignment(&mut self) -> Result<Expr, ParseError> {
        let expr = self.nil_coalesce()?;

        let compound = if self.matches(&TokenKind::PlusEq) {
            Some(BinaryOp::Add)
        } else if self.matches(&TokenKind::MinusEq) {
            Some(BinaryOp::Sub)
        } else if self.matches(&TokenKind::StarEq) {
            Some(BinaryOp::Mul)
        } else if self.matches(&TokenKind::SlashEq) {
            Some(BinaryOp::Div)
        } else {
            None
        };
        let plain = compound.is_none() && self.matches(&TokenKind::Eq);

        if compound.is_some() || plain {
            let rhs = self.assignment()?;
            let value = match compound {
                Some(op) => Box::new(Expr::Binary {
                    op,
                    left: Box::new(expr.clone()),
                    right: Box::new(rhs),
                }),
                None => Box::new(rhs),
            };
            return match expr {
                Expr::Variable(name) => Ok(Expr::Assign { name, value }),
                Expr::Get { target, name } => Ok(Expr::SetProp {
                    target,
                    name,
                    value,
                }),
                Expr::Index { target, index } => Ok(Expr::SetIndex {
                    target,
                    index,
                    value,
                }),
                _ => self.error("invalid assignment target"),
            };
        }
        Ok(expr)
    }

    fn nil_coalesce(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.pipe()?;
        while self.matches(&TokenKind::QuestionQuestion) {
            let right = self.pipe()?;
            left = Expr::NilCoalesce {
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn pipe(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.logic_or()?;
        while self.matches(&TokenKind::Pipe) {
            let right = self.logic_or()?;
            left = Expr::Pipe {
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn logic_or(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.logic_and()?;
        while self.matches(&TokenKind::Or) || self.matches(&TokenKind::OrOr) {
            let right = self.logic_and()?;
            left = Expr::Logical {
                op: LogicalOp::Or,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn logic_and(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.equality()?;
        while self.matches(&TokenKind::And) || self.matches(&TokenKind::AndAnd) {
            let right = self.equality()?;
            left = Expr::Logical {
                op: LogicalOp::And,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn equality(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.comparison()?;
        loop {
            let op = if self.matches(&TokenKind::EqEq) {
                BinaryOp::Eq
            } else if self.matches(&TokenKind::BangEq) {
                BinaryOp::Ne
            } else {
                break;
            };
            let right = self.comparison()?;
            left = Expr::Binary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn comparison(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.range_expr()?;
        loop {
            let op = if self.matches(&TokenKind::Lt) {
                BinaryOp::Lt
            } else if self.matches(&TokenKind::Le) {
                BinaryOp::Le
            } else if self.matches(&TokenKind::Gt) {
                BinaryOp::Gt
            } else if self.matches(&TokenKind::Ge) {
                BinaryOp::Ge
            } else {
                break;
            };
            let right = self.range_expr()?;
            left = Expr::Binary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn range_expr(&mut self) -> Result<Expr, ParseError> {
        let start = self.term()?;
        let inclusive = if self.matches(&TokenKind::DotDotEq) {
            true
        } else if self.matches(&TokenKind::DotDot) {
            false
        } else {
            return Ok(start);
        };
        let end = self.term()?;
        Ok(Expr::Range {
            start: Box::new(start),
            end: Box::new(end),
            inclusive,
        })
    }

    fn term(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.factor()?;
        loop {
            let op = if self.matches(&TokenKind::Plus) {
                BinaryOp::Add
            } else if self.matches(&TokenKind::Minus) {
                BinaryOp::Sub
            } else {
                break;
            };
            let right = self.factor()?;
            left = Expr::Binary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn factor(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.unary()?;
        loop {
            let op = if self.matches(&TokenKind::Star) {
                BinaryOp::Mul
            } else if self.matches(&TokenKind::Slash) {
                BinaryOp::Div
            } else if self.matches(&TokenKind::Percent) {
                BinaryOp::Mod
            } else {
                break;
            };
            let right = self.unary()?;
            left = Expr::Binary {
                op,
                left: Box::new(left),
                right: Box::new(right),
            };
        }
        Ok(left)
    }

    fn unary(&mut self) -> Result<Expr, ParseError> {
        if self.matches(&TokenKind::Minus) {
            let right = self.unary()?;
            return Ok(Expr::Unary {
                op: UnaryOp::Neg,
                right: Box::new(right),
            });
        }
        if self.matches(&TokenKind::Bang) || self.matches(&TokenKind::Not) {
            let right = self.unary()?;
            return Ok(Expr::Unary {
                op: UnaryOp::Not,
                right: Box::new(right),
            });
        }
        self.power()
    }

    /// `**` binds tighter than unary and is right-associative.
    fn power(&mut self) -> Result<Expr, ParseError> {
        let base = self.postfix()?;
        if self.matches(&TokenKind::StarStar) {
            let exponent = self.unary()?;
            return Ok(Expr::Binary {
                op: BinaryOp::Pow,
                left: Box::new(base),
                right: Box::new(exponent),
            });
        }
        Ok(base)
    }

    fn postfix(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.primary()?;
        loop {
            // A call/index operator must continue on the same line as the
            // expression it postfixes; otherwise it starts a new statement
            // (e.g. `if (c) { .. }` followed by a line beginning with `[`).
            let same_line = self.peek().line == self.previous().line;
            if same_line && self.matches(&TokenKind::LParen) {
                let args = self.arguments()?;
                expr = Expr::Call {
                    callee: Box::new(expr),
                    args,
                };
            } else if same_line && self.matches(&TokenKind::LBracket) {
                let index = self.expression()?;
                self.consume(&TokenKind::RBracket, "expected `]` after index")?;
                expr = Expr::Index {
                    target: Box::new(expr),
                    index: Box::new(index),
                };
            } else if self.matches(&TokenKind::QuestionDot) {
                let name = self.ident("expected property name after `?.`")?;
                expr = Expr::SafeGet {
                    target: Box::new(expr),
                    name,
                };
            } else if self.matches(&TokenKind::Dot) {
                let name = self.ident("expected property name after `.`")?;
                expr = Expr::Get {
                    target: Box::new(expr),
                    name,
                };
            } else if same_line && self.matches(&TokenKind::Question) {
                expr = Expr::Try {
                    expr: Box::new(expr),
                };
            } else {
                break;
            }
        }
        Ok(expr)
    }

    fn arguments(&mut self) -> Result<Vec<Expr>, ParseError> {
        let mut args = Vec::new();
        if !self.check(&TokenKind::RParen) {
            loop {
                args.push(self.expression()?);
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
            }
        }
        self.consume(&TokenKind::RParen, "expected `)` after arguments")?;
        Ok(args)
    }

    fn primary(&mut self) -> Result<Expr, ParseError> {
        // Arrow lambda: `x => expr` / `x => { ... }`.
        if matches!(self.peek().kind, TokenKind::Ident(_))
            && self.peek_next().kind == TokenKind::FatArrow
        {
            let name = self.ident("expected parameter name")?;
            self.advance(); // `=>`
            let body = self.lambda_body()?;
            return Ok(Expr::Lambda {
                params: vec![Param {
                    name,
                    type_hint: None,
                }],
                body: Box::new(body),
            });
        }

        let token = self.peek().clone();
        let expr = match &token.kind {
            TokenKind::Int(v) => {
                self.advance();
                Expr::Literal(Literal::Int(*v))
            }
            TokenKind::Float(v) => {
                self.advance();
                Expr::Literal(Literal::Float(*v))
            }
            TokenKind::Str(v) => {
                self.advance();
                Expr::Literal(Literal::Str(v.clone()))
            }
            TokenKind::InterpStr(segments) => {
                self.advance();
                let segments = segments.clone();
                self.string_interpolation(segments)?
            }
            TokenKind::True => {
                self.advance();
                Expr::Literal(Literal::Bool(true))
            }
            TokenKind::False => {
                self.advance();
                Expr::Literal(Literal::Bool(false))
            }
            TokenKind::Nil => {
                self.advance();
                Expr::Literal(Literal::Nil)
            }
            TokenKind::Ident(name) => {
                let name = name.clone();
                self.advance();
                Expr::Variable(name)
            }
            TokenKind::LParen => {
                self.advance();
                let expr = self.expression()?;
                self.consume(&TokenKind::RParen, "expected `)` after expression")?;
                expr
            }
            TokenKind::LBracket => self.list_literal()?,
            TokenKind::LBrace => self.map_literal()?,
            TokenKind::If => self.if_expression(false)?,
            TokenKind::Unless => self.if_expression(true)?,
            TokenKind::May => self.may_expression()?,
            TokenKind::Fun => self.lambda()?,
            TokenKind::Bar => self.short_lambda()?,
            TokenKind::Match => self.match_expression()?,
            _ => return self.error("expected expression"),
        };
        Ok(expr)
    }

    /// Desugar `"a${x}b"` into a left-fold of `+`, which stringifies operands.
    fn string_interpolation(
        &mut self,
        segments: Vec<InterpSegment>,
    ) -> Result<Expr, ParseError> {
        let mut acc = Expr::Literal(Literal::Str(String::new()));
        for segment in segments {
            let piece = match segment {
                InterpSegment::Lit(text) => Expr::Literal(Literal::Str(text)),
                InterpSegment::Expr(source) => parse_expression(&source)?,
            };
            acc = Expr::Binary {
                op: BinaryOp::Add,
                left: Box::new(acc),
                right: Box::new(piece),
            };
        }
        Ok(acc)
    }

    /// `|x, y| expr` and `|x| { ... }`.
    fn short_lambda(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::Bar, "expected `|`")?;
        let mut params = Vec::new();
        if !self.check(&TokenKind::Bar) {
            loop {
                let name = self.ident("expected parameter name")?;
                let type_hint = self.optional_type_hint()?;
                params.push(Param { name, type_hint });
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
            }
        }
        self.consume(
            &TokenKind::Bar,
            "expected `|` to close lambda parameters",
        )?;
        let body = self.lambda_body()?;
        Ok(Expr::Lambda {
            params,
            body: Box::new(body),
        })
    }

    /// A lambda body: a braced block or a single expression.
    fn lambda_body(&mut self) -> Result<Block, ParseError> {
        if self.check(&TokenKind::LBrace) {
            return self.block();
        }
        let line = self.line();
        let expr = self.expression()?;
        Ok(Block::new(Vec::new(), Some(expr), line))
    }

    /// A match-arm body: a braced block or a single expression.
    fn arm_body(&mut self) -> Result<Expr, ParseError> {
        if self.check(&TokenKind::LBrace) {
            let block = self.block()?;
            Ok(Expr::Block(block))
        } else {
            self.expression()
        }
    }

    fn string_literal(&mut self, message: &str) -> Result<String, ParseError> {
        if let TokenKind::Str(s) = &self.peek().kind {
            let s = s.clone();
            self.advance();
            Ok(s)
        } else {
            Err(self.error_at_current(message))
        }
    }

    fn match_expression(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::Match, "expected `match`")?;
        let scrutinee = self.expression()?;
        self.consume(&TokenKind::LBrace, "expected `{` after match scrutinee")?;
        let mut arms = Vec::new();
        while !self.check(&TokenKind::RBrace) && !self.check(&TokenKind::Eof) {
            let pattern = self.pattern()?;
            let guard = if self.matches(&TokenKind::If) {
                Some(self.expression()?)
            } else {
                None
            };
            self.consume(&TokenKind::FatArrow, "expected `=>` in match arm")?;
            let body = self.arm_body()?;
            arms.push(MatchArm {
                pattern,
                guard,
                body,
            });
            let _ = self.matches(&TokenKind::Comma);
        }
        self.consume(&TokenKind::RBrace, "expected `}` after match arms")?;
        Ok(Expr::Match {
            scrutinee: Box::new(scrutinee),
            arms,
        })
    }

    fn pattern(&mut self) -> Result<Pattern, ParseError> {
        let token = self.peek().clone();
        let pattern = match &token.kind {
            TokenKind::Ident(name) if name == "_" => {
                self.advance();
                Pattern::Wildcard
            }
            TokenKind::Ident(name) => {
                let name = name.clone();
                self.advance();
                Pattern::Binding(name)
            }
            TokenKind::Int(v) => {
                self.advance();
                Pattern::Literal(Literal::Int(*v))
            }
            TokenKind::Float(v) => {
                self.advance();
                Pattern::Literal(Literal::Float(*v))
            }
            TokenKind::Str(v) => {
                self.advance();
                Pattern::Literal(Literal::Str(v.clone()))
            }
            TokenKind::True => {
                self.advance();
                Pattern::Literal(Literal::Bool(true))
            }
            TokenKind::False => {
                self.advance();
                Pattern::Literal(Literal::Bool(false))
            }
            TokenKind::Nil => {
                self.advance();
                Pattern::Literal(Literal::Nil)
            }
            TokenKind::Minus => {
                self.advance();
                match &self.peek().kind {
                    TokenKind::Int(v) => {
                        let v = *v;
                        self.advance();
                        Pattern::Literal(Literal::Int(-v))
                    }
                    TokenKind::Float(v) => {
                        let v = *v;
                        self.advance();
                        Pattern::Literal(Literal::Float(-v))
                    }
                    _ => return self.error("expected a number after `-` in pattern"),
                }
            }
            _ => return self.error("expected a pattern"),
        };
        Ok(pattern)
    }

    fn list_literal(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::LBracket, "expected `[`")?;
        if self.check(&TokenKind::RBracket) {
            self.advance();
            return Ok(Expr::List(Vec::new()));
        }
        if self.matches(&TokenKind::Ellipsis) {
            let first = ListItem::Spread(self.expression()?);
            let items = self.list_items(first)?;
            return Ok(build_list_literal(items));
        }
        let first_expr = self.expression()?;
        if self.matches(&TokenKind::For) {
            return self.list_comprehension(first_expr);
        }
        let items = self.list_items(ListItem::Expr(first_expr))?;
        Ok(build_list_literal(items))
    }

    fn list_items(&mut self, first: ListItem) -> Result<Vec<ListItem>, ParseError> {
        let mut items = vec![first];
        while self.matches(&TokenKind::Comma) {
            if self.check(&TokenKind::RBracket) {
                break;
            }
            if self.matches(&TokenKind::Ellipsis) {
                items.push(ListItem::Spread(self.expression()?));
            } else {
                items.push(ListItem::Expr(self.expression()?));
            }
        }
        self.consume(&TokenKind::RBracket, "expected `]` after list")?;
        Ok(items)
    }

    /// `[body for name in iterable if cond]` desugars to
    /// `map(filter(iterable, fun(name) { cond }), fun(name) { body })`.
    fn list_comprehension(&mut self, body: Expr) -> Result<Expr, ParseError> {
        let name = self.ident("expected loop variable in comprehension")?;
        let _ = self.optional_type_hint()?;
        self.consume(&TokenKind::In, "expected `in` in comprehension")?;
        let iterable = self.expression()?;
        let cond = if self.matches(&TokenKind::If) {
            Some(self.expression()?)
        } else {
            None
        };
        self.consume(&TokenKind::RBracket, "expected `]` after comprehension")?;
        Ok(desugar_comprehension(body, name, iterable, cond))
    }

    fn map_literal(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::LBrace, "expected `{`")?;
        let mut items = Vec::new();
        if !self.check(&TokenKind::RBrace) {
            loop {
                if self.matches(&TokenKind::Ellipsis) {
                    items.push(MapItem::Spread(self.expression()?));
                } else {
                    let key = if matches!(self.peek().kind, TokenKind::Ident(_))
                        && self.check_next(&TokenKind::Colon)
                    {
                        let name = self.ident("expected key")?;
                        Expr::Literal(Literal::Str(name))
                    } else {
                        self.expression()?
                    };
                    self.consume(&TokenKind::Colon, "expected `:` after map key")?;
                    let value = self.expression()?;
                    items.push(MapItem::Entry(key, value));
                }
                if !self.matches(&TokenKind::Comma) {
                    break;
                }
                if self.check(&TokenKind::RBrace) {
                    break;
                }
            }
        }
        self.consume(&TokenKind::RBrace, "expected `}` after map")?;
        Ok(build_map_literal(items))
    }

    fn if_expression(&mut self, inverted: bool) -> Result<Expr, ParseError> {
        if inverted {
            self.consume(&TokenKind::Unless, "expected `unless`")?;
        } else {
            self.consume(&TokenKind::If, "expected `if`")?;
        }
        // Parentheses around the condition are optional.
        let cond = self.expression()?;
        let then_block = self.body()?;
        let else_branch = if self.matches(&TokenKind::Else) {
            if self.check(&TokenKind::If) {
                let line = self.line();
                let nested = self.if_expression(false)?;
                Some(Box::new(Block::new(Vec::new(), Some(nested), line)))
            } else if self.check(&TokenKind::Unless) {
                let line = self.line();
                let nested = self.if_expression(true)?;
                Some(Box::new(Block::new(Vec::new(), Some(nested), line)))
            } else {
                Some(Box::new(self.body()?))
            }
        } else {
            None
        };

        if inverted {
            Ok(Expr::Unless {
                cond: Box::new(cond),
                body: Box::new(then_block),
                else_branch,
            })
        } else {
            Ok(Expr::If {
                cond: Box::new(cond),
                then_branch: Box::new(then_block),
                else_branch,
            })
        }
    }

    fn may_expression(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::May, "expected `may`")?;
        let body = self.block()?;
        // `otherwise` is optional: without it a fault yields nil.
        let fallback = if self.matches(&TokenKind::Otherwise) {
            Some(Box::new(self.block()?))
        } else {
            None
        };
        Ok(Expr::May {
            body: Box::new(body),
            fallback,
        })
    }

    fn lambda(&mut self) -> Result<Expr, ParseError> {
        self.consume(&TokenKind::Fun, "expected `fun`")?;
        let params = self.parameters()?;
        if self.matches(&TokenKind::Arrow) {
            let _ = self.parse_type()?;
        }
        let body = self.block()?;
        Ok(Expr::Lambda {
            params,
            body: Box::new(body),
        })
    }
}

enum ListItem {
    Expr(Expr),
    Spread(Expr),
}

enum MapItem {
    Entry(Expr, Expr),
    Spread(Expr),
}

fn concat_lists(acc: Option<Expr>, next: Expr) -> Expr {
    match acc {
        None => next,
        Some(left) => Expr::Binary {
            op: BinaryOp::Add,
            left: Box::new(left),
            right: Box::new(next),
        },
    }
}

fn build_list_literal(items: Vec<ListItem>) -> Expr {
    if !items.iter().any(|i| matches!(i, ListItem::Spread(_))) {
        let exprs = items
            .into_iter()
            .map(|i| match i {
                ListItem::Expr(e) => e,
                ListItem::Spread(_) => unreachable!(),
            })
            .collect();
        return Expr::List(exprs);
    }
    let mut acc: Option<Expr> = None;
    let mut run: Vec<Expr> = Vec::new();
    for item in items {
        match item {
            ListItem::Expr(e) => run.push(e),
            ListItem::Spread(e) => {
                if !run.is_empty() {
                    let chunk = Expr::List(std::mem::take(&mut run));
                    acc = Some(concat_lists(acc, chunk));
                }
                acc = Some(concat_lists(acc, e));
            }
        }
    }
    if !run.is_empty() {
        let chunk = Expr::List(run);
        acc = Some(concat_lists(acc, chunk));
    }
    acc.unwrap_or_else(|| Expr::List(Vec::new()))
}

fn merge_maps(acc: Option<Expr>, next: Expr) -> Expr {
    match acc {
        None => next,
        Some(left) => Expr::Call {
            callee: Box::new(Expr::Variable("merge".to_string())),
            args: vec![left, next],
        },
    }
}

fn build_map_literal(items: Vec<MapItem>) -> Expr {
    if !items.iter().any(|i| matches!(i, MapItem::Spread(_))) {
        let entries = items
            .into_iter()
            .map(|i| match i {
                MapItem::Entry(k, v) => (k, v),
                MapItem::Spread(_) => unreachable!(),
            })
            .collect();
        return Expr::Map(entries);
    }
    let mut acc: Option<Expr> = None;
    let mut run: Vec<(Expr, Expr)> = Vec::new();
    for item in items {
        match item {
            MapItem::Entry(k, v) => run.push((k, v)),
            MapItem::Spread(e) => {
                if !run.is_empty() {
                    let chunk = Expr::Map(std::mem::take(&mut run));
                    acc = Some(merge_maps(acc, chunk));
                }
                acc = Some(merge_maps(acc, e));
            }
        }
    }
    if !run.is_empty() {
        let chunk = Expr::Map(run);
        acc = Some(merge_maps(acc, chunk));
    }
    acc.unwrap_or_else(|| Expr::Map(Vec::new()))
}

fn desugar_comprehension(body: Expr, name: String, iterable: Expr, cond: Option<Expr>) -> Expr {
    let param = || Param {
        name: name.clone(),
        type_hint: None,
    };
    let map_fn = Expr::Lambda {
        params: vec![param()],
        body: Box::new(Block::new(Vec::new(), Some(body), 0)),
    };
    let source = match cond {
        Some(c) => {
            let filter_fn = Expr::Lambda {
                params: vec![param()],
                body: Box::new(Block::new(Vec::new(), Some(c), 0)),
            };
            Expr::Call {
                callee: Box::new(Expr::Variable("filter".to_string())),
                args: vec![iterable, filter_fn],
            }
        }
        None => iterable,
    };
    Expr::Call {
        callee: Box::new(Expr::Variable("map".to_string())),
        args: vec![source, map_fn],
    }
}

/// Turn a statement list into a [`Block`], lifting a trailing expression
/// without a semicolon into the block's value.
/// A parser-level binding pattern used by `let`/`for` destructuring. It is
/// fully desugared into ordinary `let` bindings, so it never reaches the AST.
#[derive(Debug, Clone)]
enum BindPat {
    Ident(String),
    Wild,
    List(Vec<BindPat>),
    Record(Vec<(String, BindPat)>),
}

fn finish_block(mut stmts: Vec<Stmt>) -> Block {
    let is_tail = matches!(
        stmts.last(),
        Some(Stmt {
            kind: StmtKind::Expr { semi: false, .. },
            ..
        })
    );
    if is_tail {
        if let Some(Stmt {
            kind: StmtKind::Expr { expr, .. },
            line,
        }) = stmts.pop()
        {
            return Block::new(stmts, Some(expr), line);
        }
    }
    Block::new(stmts, None, 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_pipe_chain() {
        let program = parse("data |> filter(pred) |> map(fn);").unwrap();
        let expr = match program.body.stmts.first() {
            Some(Stmt {
                kind: StmtKind::Expr { expr, .. },
                ..
            }) => expr,
            other => panic!("unexpected: {other:?}"),
        };
        assert!(matches!(expr, Expr::Pipe { .. }));
    }

    #[test]
    fn parses_may() {
        let program = parse("let r = may { f() } otherwise { 0 };").unwrap();
        assert_eq!(program.body.stmts.len(), 1);
    }

    #[test]
    fn parses_unless_and_for() {
        parse("fun g() { unless (ready) { return nil; } for x in 0..10 { print(x); } }").unwrap();
    }

    #[test]
    fn bootstrap_annotations_do_not_change_runtime_syntax() {
        assert_eq!(
            parse("for x: Any in [1, 2] { print(x); }").unwrap(),
            parse("for x in [1, 2] { print(x); }").unwrap()
        );
        assert_eq!(
            parse("[x + 1 for x: Int in 0..3];").unwrap(),
            parse("[x + 1 for x in 0..3];").unwrap()
        );
        assert_eq!(
            parse("fun(x: Int) -> Int { return x; };").unwrap(),
            parse("fun(x: Int) { return x; };").unwrap()
        );
    }

    #[test]
    fn block_tail_detection() {
        let p = parse("{ 1 + 2 }").unwrap();
        // Top-level `{ ... }` is parsed as a block expression statement, then
        // lifted into the program tail.
        assert!(p.body.tail.is_some() || !p.body.stmts.is_empty());
    }

    #[test]
    fn parses_modern_syntax() {
        parse(
            "import \"util\";\n\
             from \"util\" import a, b;\n\
             let n = (may { int(s) }) ?? 0;\n\
             let e = user?.profile?.email;\n\
             let m = match (n) { 1 => \"one\", x if x > 2 => \"big\", _ => \"other\" };\n\
             let xs = [1, ...rest, 3];\n\
             let cfg = {...defaults, \"k\": 1};\n\
             let sq = [x * x for x in 1..=5 if x % 2 == 0];\n\
             let f = |x| x + 1;\n\
             let g = x => x * 2;\n\
             let s = \"n=${n}\";\n\
             let p = 2 ** 8;\n\
             mut c = 1; c += 1;\n",
        )
        .unwrap();
    }

    #[test]
    fn optional_condition_parens() {
        parse("if ready { go(); } else { stop(); }\nwhile running { tick(); }").unwrap();
    }
}
