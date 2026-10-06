//! Maylang tokenizer: turns source text into a stream of [`Token`]s.

use std::fmt;

/// One piece of an interpolated string: a literal run or an embedded
/// expression's source text (parsed later by the parser).
#[derive(Debug, Clone, PartialEq)]
pub enum InterpSegment {
    Lit(String),
    Expr(String),
}

/// A lexical token kind. Literal payloads carry their parsed value.
#[derive(Debug, Clone, PartialEq)]
pub enum TokenKind {
    // Literals & identifiers.
    Int(i64),
    Float(f64),
    Str(String),
    /// A string containing `${ ... }` interpolations.
    InterpStr(Vec<InterpSegment>),
    Ident(String),

    // Delimiters.
    LParen,
    RParen,
    LBrace,
    RBrace,
    LBracket,
    RBracket,

    // Punctuation & operators.
    Comma,
    Dot,
    DotDot,
    DotDotEq,
    Ellipsis,
    Semicolon,
    Colon,
    Pipe,
    Bar,
    Plus,
    Minus,
    Star,
    StarStar,
    Slash,
    Percent,
    PlusEq,
    MinusEq,
    StarEq,
    SlashEq,
    Bang,
    BangEq,
    Eq,
    EqEq,
    Arrow,
    FatArrow,
    Gt,
    Ge,
    Lt,
    Le,
    AndAnd,
    OrOr,
    Question,
    QuestionQuestion,
    QuestionDot,

    // Keywords.
    Fun,
    Let,
    Mut,
    If,
    Else,
    While,
    For,
    In,
    Return,
    True,
    False,
    Nil,
    May,
    Otherwise,
    Unless,
    And,
    Or,
    Not,
    Break,
    Continue,
    Match,
    Import,
    From,

    Eof,
}

impl fmt::Display for TokenKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TokenKind::Int(v) => write!(f, "integer `{v}`"),
            TokenKind::Float(v) => write!(f, "float `{v}`"),
            TokenKind::Str(v) => write!(f, "string {v:?}"),
            TokenKind::InterpStr(_) => write!(f, "interpolated string"),
            TokenKind::Ident(v) => write!(f, "identifier `{v}`"),
            TokenKind::LParen => write!(f, "`(`"),
            TokenKind::RParen => write!(f, "`)`"),
            TokenKind::LBrace => write!(f, "`{{`"),
            TokenKind::RBrace => write!(f, "`}}`"),
            TokenKind::LBracket => write!(f, "`[`"),
            TokenKind::RBracket => write!(f, "`]`"),
            TokenKind::Comma => write!(f, "`,`"),
            TokenKind::Dot => write!(f, "`.`"),
            TokenKind::DotDot => write!(f, "`..`"),
            TokenKind::DotDotEq => write!(f, "`..=`"),
            TokenKind::Semicolon => write!(f, "`;`"),
            TokenKind::Colon => write!(f, "`:`"),
            TokenKind::Pipe => write!(f, "`|>`"),
            TokenKind::Plus => write!(f, "`+`"),
            TokenKind::Minus => write!(f, "`-`"),
            TokenKind::Star => write!(f, "`*`"),
            TokenKind::Slash => write!(f, "`/`"),
            TokenKind::Percent => write!(f, "`%`"),
            TokenKind::Bang => write!(f, "`!`"),
            TokenKind::BangEq => write!(f, "`!=`"),
            TokenKind::Eq => write!(f, "`=`"),
            TokenKind::EqEq => write!(f, "`==`"),
            TokenKind::Arrow => write!(f, "`->`"),
            TokenKind::Gt => write!(f, "`>`"),
            TokenKind::Ge => write!(f, "`>=`"),
            TokenKind::Lt => write!(f, "`<`"),
            TokenKind::Le => write!(f, "`<=`"),
            TokenKind::AndAnd => write!(f, "`&&`"),
            TokenKind::OrOr => write!(f, "`||`"),
            TokenKind::Question => write!(f, "`?`"),
            TokenKind::QuestionQuestion => write!(f, "`??`"),
            TokenKind::QuestionDot => write!(f, "`?.`"),
            TokenKind::StarStar => write!(f, "`**`"),
            TokenKind::PlusEq => write!(f, "`+=`"),
            TokenKind::MinusEq => write!(f, "`-=`"),
            TokenKind::StarEq => write!(f, "`*=`"),
            TokenKind::SlashEq => write!(f, "`/=`"),
            TokenKind::FatArrow => write!(f, "`=>`"),
            TokenKind::Ellipsis => write!(f, "`...`"),
            TokenKind::Bar => write!(f, "`|`"),
            TokenKind::Fun => write!(f, "`fun`"),
            TokenKind::Let => write!(f, "`let`"),
            TokenKind::Mut => write!(f, "`mut`"),
            TokenKind::If => write!(f, "`if`"),
            TokenKind::Else => write!(f, "`else`"),
            TokenKind::While => write!(f, "`while`"),
            TokenKind::For => write!(f, "`for`"),
            TokenKind::In => write!(f, "`in`"),
            TokenKind::Return => write!(f, "`return`"),
            TokenKind::True => write!(f, "`true`"),
            TokenKind::False => write!(f, "`false`"),
            TokenKind::Nil => write!(f, "`nil`"),
            TokenKind::May => write!(f, "`may`"),
            TokenKind::Otherwise => write!(f, "`otherwise`"),
            TokenKind::Unless => write!(f, "`unless`"),
            TokenKind::And => write!(f, "`and`"),
            TokenKind::Or => write!(f, "`or`"),
            TokenKind::Not => write!(f, "`not`"),
            TokenKind::Break => write!(f, "`break`"),
            TokenKind::Continue => write!(f, "`continue`"),
            TokenKind::Match => write!(f, "`match`"),
            TokenKind::Import => write!(f, "`import`"),
            TokenKind::From => write!(f, "`from`"),
            TokenKind::Eof => write!(f, "end of input"),
        }
    }
}

/// A token together with its 1-based source line and column.
///
/// `col` counts Unicode scalar values from the start of the line (1-based) and
/// is `0` when a token was built without position information.
#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub kind: TokenKind,
    pub line: u32,
    pub col: u32,
}

impl Token {
    pub fn new(kind: TokenKind, line: u32) -> Self {
        Token {
            kind,
            line,
            col: 0,
        }
    }

    pub fn at(kind: TokenKind, line: u32, col: u32) -> Self {
        Token { kind, line, col }
    }
}

/// A lexical error.
#[derive(Debug, Clone, PartialEq)]
pub struct LexError {
    pub message: String,
    pub line: u32,
}

impl fmt::Display for LexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "line {}: {}", self.line, self.message)
    }
}

impl std::error::Error for LexError {}

/// The Maylang lexer.
pub struct Lexer {
    chars: Vec<char>,
    pos: usize,
    line: u32,
    /// Character offset where the current line begins (for column tracking).
    line_start: usize,
}

impl Lexer {
    pub fn new(source: &str) -> Self {
        Lexer {
            chars: source.chars().collect(),
            pos: 0,
            line: 1,
            line_start: 0,
        }
    }

    /// Tokenize the entire input, including the trailing [`TokenKind::Eof`].
    pub fn tokenize(mut self) -> Result<Vec<Token>, LexError> {
        let mut tokens = Vec::new();
        loop {
            let token = self.next_token()?;
            let is_eof = token.kind == TokenKind::Eof;
            tokens.push(token);
            if is_eof {
                return Ok(tokens);
            }
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn peek2(&self) -> Option<char> {
        self.chars.get(self.pos + 1).copied()
    }

    fn advance(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.pos += 1;
        if c == '\n' {
            self.line_start = self.pos;
        }
        Some(c)
    }

    fn matches(&mut self, expected: char) -> bool {
        if self.peek() == Some(expected) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn err<T>(&self, message: impl Into<String>) -> Result<T, LexError> {
        Err(LexError {
            message: message.into(),
            line: self.line,
        })
    }

    fn skip_trivia(&mut self) -> Result<(), LexError> {
        loop {
            match self.peek() {
                Some(c) if c.is_whitespace() => {
                    self.pos += 1;
                    if c == '\n' {
                        self.line += 1;
                        self.line_start = self.pos;
                    }
                }
                Some('/') if self.peek2() == Some('/') => {
                    while let Some(c) = self.peek() {
                        if c == '\n' {
                            break;
                        }
                        self.pos += 1;
                    }
                }
                Some('/') if self.peek2() == Some('*') => {
                    let start_line = self.line;
                    self.pos += 2;
                    let mut depth = 1;
                    while depth > 0 {
                        match self.advance() {
                            Some('\n') => self.line += 1,
                            Some('/') if self.peek() == Some('*') => {
                                self.pos += 1;
                                depth += 1;
                            }
                            Some('*') if self.peek() == Some('/') => {
                                self.pos += 1;
                                depth -= 1;
                            }
                            Some(_) => {}
                            None => {
                                return Err(LexError {
                                    message: "unterminated block comment".to_string(),
                                    line: start_line,
                                });
                            }
                        }
                    }
                }
                _ => return Ok(()),
            }
        }
    }

    fn next_token(&mut self) -> Result<Token, LexError> {
        self.skip_trivia()?;
        let line = self.line;
        let col = (self.pos - self.line_start + 1) as u32;
        let c = match self.advance() {
            Some(c) => c,
            None => return Ok(Token::at(TokenKind::Eof, line, col)),
        };

        let kind = match c {
            '(' => TokenKind::LParen,
            ')' => TokenKind::RParen,
            '{' => TokenKind::LBrace,
            '}' => TokenKind::RBrace,
            '[' => TokenKind::LBracket,
            ']' => TokenKind::RBracket,
            ',' => TokenKind::Comma,
            ';' => TokenKind::Semicolon,
            ':' => TokenKind::Colon,
            '+' => {
                if self.matches('=') {
                    TokenKind::PlusEq
                } else {
                    TokenKind::Plus
                }
            }
            '-' => {
                if self.matches('=') {
                    TokenKind::MinusEq
                } else if self.matches('>') {
                    TokenKind::Arrow
                } else {
                    TokenKind::Minus
                }
            }
            '*' => {
                if self.matches('*') {
                    TokenKind::StarStar
                } else if self.matches('=') {
                    TokenKind::StarEq
                } else {
                    TokenKind::Star
                }
            }
            '%' => TokenKind::Percent,
            '?' => {
                if self.matches('?') {
                    TokenKind::QuestionQuestion
                } else if self.matches('.') {
                    TokenKind::QuestionDot
                } else {
                    TokenKind::Question
                }
            }
            '.' => {
                if self.matches('.') {
                    if self.matches('.') {
                        TokenKind::Ellipsis
                    } else if self.matches('=') {
                        TokenKind::DotDotEq
                    } else {
                        TokenKind::DotDot
                    }
                } else {
                    TokenKind::Dot
                }
            }
            '/' => {
                if self.matches('=') {
                    TokenKind::SlashEq
                } else {
                    TokenKind::Slash
                }
            }
            '!' => {
                if self.matches('=') {
                    TokenKind::BangEq
                } else {
                    TokenKind::Bang
                }
            }
            '=' => {
                if self.matches('>') {
                    TokenKind::FatArrow
                } else if self.matches('=') {
                    TokenKind::EqEq
                } else {
                    TokenKind::Eq
                }
            }
            '<' => {
                if self.matches('=') {
                    TokenKind::Le
                } else {
                    TokenKind::Lt
                }
            }
            '>' => {
                if self.matches('=') {
                    TokenKind::Ge
                } else {
                    TokenKind::Gt
                }
            }
            '&' => {
                if self.matches('&') {
                    TokenKind::AndAnd
                } else {
                    return self.err("unexpected character `&` (did you mean `&&`?)");
                }
            }
            '|' => {
                if self.matches('>') {
                    TokenKind::Pipe
                } else if self.matches('|') {
                    TokenKind::OrOr
                } else {
                    TokenKind::Bar
                }
            }
            '"' => self.string(line)?,
            c if c.is_ascii_digit() => self.number(c, line)?,
            c if is_ident_start(c) => self.identifier(c),
            other => return self.err(format!("unexpected character `{other}`")),
        };

        Ok(Token::at(kind, line, col))
    }

    fn string(&mut self, line: u32) -> Result<TokenKind, LexError> {
        let mut literal = String::new();
        let mut segments: Vec<InterpSegment> = Vec::new();
        let mut has_interp = false;
        loop {
            match self.advance() {
                None => {
                    return Err(LexError {
                        message: "unterminated string literal".to_string(),
                        line,
                    })
                }
                Some('"') => {
                    if has_interp {
                        if !literal.is_empty() {
                            segments.push(InterpSegment::Lit(literal));
                        }
                        return Ok(TokenKind::InterpStr(segments));
                    }
                    return Ok(TokenKind::Str(literal));
                }
                Some('$') if self.peek() == Some('{') => {
                    self.pos += 1; // consume `{`
                    if !literal.is_empty() {
                        segments.push(InterpSegment::Lit(std::mem::take(&mut literal)));
                    }
                    has_interp = true;
                    let source = self.interpolation_expr(line)?;
                    segments.push(InterpSegment::Expr(source));
                }
                Some('\\') => {
                    let escaped = match self.advance() {
                        Some('n') => '\n',
                        Some('t') => '\t',
                        Some('r') => '\r',
                        Some('0') => '\0',
                        Some('\\') => '\\',
                        Some('"') => '"',
                        Some('$') => '$',
                        Some(other) => {
                            return self.err(format!("invalid escape sequence `\\{other}`"))
                        }
                        None => {
                            return Err(LexError {
                                message: "unterminated string literal".to_string(),
                                line,
                            })
                        }
                    };
                    literal.push(escaped);
                }
                Some('\n') => {
                    self.line += 1;
                    literal.push('\n');
                }
                Some(c) => literal.push(c),
            }
        }
    }

    /// Read the source text of a `${ ... }` hole, assuming the opening `{` has
    /// been consumed. Tracks nested braces and skips over nested strings.
    fn interpolation_expr(&mut self, line: u32) -> Result<String, LexError> {
        let mut depth = 1usize;
        let mut out = String::new();
        loop {
            match self.advance() {
                None => {
                    return Err(LexError {
                        message: "unterminated string interpolation `${`".to_string(),
                        line,
                    })
                }
                Some('{') => {
                    depth += 1;
                    out.push('{');
                }
                Some('}') => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(out);
                    }
                    out.push('}');
                }
                Some('"') => {
                    out.push('"');
                    loop {
                        match self.advance() {
                            None => {
                                return Err(LexError {
                                    message: "unterminated string literal".to_string(),
                                    line,
                                })
                            }
                            Some('\\') => {
                                out.push('\\');
                                if let Some(c) = self.advance() {
                                    out.push(c);
                                }
                            }
                            Some('"') => {
                                out.push('"');
                                break;
                            }
                            Some('\n') => {
                                self.line += 1;
                                out.push('\n');
                            }
                            Some(c) => out.push(c),
                        }
                    }
                }
                Some('\n') => {
                    self.line += 1;
                    out.push('\n');
                }
                Some(c) => out.push(c),
            }
        }
    }

    fn number(&mut self, first: char, line: u32) -> Result<TokenKind, LexError> {
        let mut text = String::new();
        text.push(first);
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == '_' {
                text.push(c);
                self.pos += 1;
            } else {
                break;
            }
        }

        let mut is_float = false;
        // Fractional part: only if `.` is followed by a digit (so `1..2` is a
        // range, not a malformed float).
        if self.peek() == Some('.') && self.peek2().is_some_and(|c| c.is_ascii_digit()) {
            is_float = true;
            text.push('.');
            self.pos += 1;
            while let Some(c) = self.peek() {
                if c.is_ascii_digit() || c == '_' {
                    text.push(c);
                    self.pos += 1;
                } else {
                    break;
                }
            }
        }

        // Exponent.
        if matches!(self.peek(), Some('e') | Some('E')) {
            let save_pos = self.pos;
            let save_line = self.line;
            let mut exp = String::new();
            exp.push(self.advance().unwrap());
            if matches!(self.peek(), Some('+') | Some('-')) {
                exp.push(self.advance().unwrap());
            }
            if self.peek().is_some_and(|c| c.is_ascii_digit()) {
                while let Some(c) = self.peek() {
                    if c.is_ascii_digit() || c == '_' {
                        exp.push(c);
                        self.pos += 1;
                    } else {
                        break;
                    }
                }
                text.push_str(&exp);
                is_float = true;
            } else {
                // Not actually an exponent; roll back.
                self.pos = save_pos;
                self.line = save_line;
            }
        }

        let cleaned: String = text.chars().filter(|c| *c != '_').collect();
        if is_float {
            match cleaned.parse::<f64>() {
                Ok(v) => Ok(TokenKind::Float(v)),
                Err(_) => Err(LexError {
                    message: format!("invalid float literal `{cleaned}`"),
                    line,
                }),
            }
        } else {
            match cleaned.parse::<i64>() {
                Ok(v) => Ok(TokenKind::Int(v)),
                Err(_) => Err(LexError {
                    message: format!("invalid integer literal `{cleaned}`"),
                    line,
                }),
            }
        }
    }

    fn identifier(&mut self, first: char) -> TokenKind {
        let mut text = String::new();
        text.push(first);
        while let Some(c) = self.peek() {
            if is_ident_continue(c) {
                text.push(c);
                self.pos += 1;
            } else {
                break;
            }
        }
        match text.as_str() {
            "fun" => TokenKind::Fun,
            "let" => TokenKind::Let,
            "mut" => TokenKind::Mut,
            "if" => TokenKind::If,
            "else" => TokenKind::Else,
            "while" => TokenKind::While,
            "for" => TokenKind::For,
            "in" => TokenKind::In,
            "return" => TokenKind::Return,
            "true" => TokenKind::True,
            "false" => TokenKind::False,
            "nil" => TokenKind::Nil,
            "may" => TokenKind::May,
            "otherwise" => TokenKind::Otherwise,
            "unless" => TokenKind::Unless,
            "and" => TokenKind::And,
            "or" => TokenKind::Or,
            "not" => TokenKind::Not,
            "break" => TokenKind::Break,
            "continue" => TokenKind::Continue,
            "match" => TokenKind::Match,
            "import" => TokenKind::Import,
            "from" => TokenKind::From,
            _ => TokenKind::Ident(text),
        }
    }
}

fn is_ident_start(c: char) -> bool {
    c == '_' || c.is_alphabetic()
}

fn is_ident_continue(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

/// Convenience helper.
pub fn tokenize(source: &str) -> Result<Vec<Token>, LexError> {
    Lexer::new(source).tokenize()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(src: &str) -> Vec<TokenKind> {
        tokenize(src)
            .unwrap()
            .into_iter()
            .map(|t| t.kind)
            .collect()
    }

    #[test]
    fn basic_tokens() {
        let ts = kinds("let x = 1..10;");
        assert_eq!(
            ts,
            vec![
                TokenKind::Let,
                TokenKind::Ident("x".into()),
                TokenKind::Eq,
                TokenKind::Int(1),
                TokenKind::DotDot,
                TokenKind::Int(10),
                TokenKind::Semicolon,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn pipe_and_may() {
        let ts = kinds("x |> may { y } otherwise { 0 }");
        assert!(ts.contains(&TokenKind::Pipe));
        assert!(ts.contains(&TokenKind::May));
        assert!(ts.contains(&TokenKind::Otherwise));
    }

    #[test]
    fn floats_vs_range() {
        assert_eq!(kinds("1.5"), vec![TokenKind::Float(1.5), TokenKind::Eof]);
        assert_eq!(kinds("1e3"), vec![TokenKind::Float(1000.0), TokenKind::Eof]);
        assert_eq!(
            kinds("1..=5"),
            vec![
                TokenKind::Int(1),
                TokenKind::DotDotEq,
                TokenKind::Int(5),
                TokenKind::Eof
            ]
        );
    }

    #[test]
    fn strings() {
        assert_eq!(
            kinds(r#""a\nb""#),
            vec![TokenKind::Str("a\nb".into()), TokenKind::Eof]
        );
    }

    #[test]
    fn nested_block_comment() {
        assert_eq!(
            kinds("/* a /* b */ c */ 1"),
            vec![TokenKind::Int(1), TokenKind::Eof]
        );
    }

    #[test]
    fn new_operators() {
        let ts = kinds("a ?? b ?. c ** 2 ** 3 ... |x| x => y");
        assert!(ts.contains(&TokenKind::QuestionQuestion));
        assert!(ts.contains(&TokenKind::QuestionDot));
        assert_eq!(ts.iter().filter(|t| **t == TokenKind::StarStar).count(), 2);
        assert!(ts.contains(&TokenKind::Ellipsis));
        assert!(ts.contains(&TokenKind::Bar));
        assert!(ts.contains(&TokenKind::FatArrow));
    }

    #[test]
    fn compound_and_keywords() {
        let ts = kinds("x += 1; y -= 2; z *= 3; w /= 4; match import from");
        assert!(ts.contains(&TokenKind::PlusEq));
        assert!(ts.contains(&TokenKind::MinusEq));
        assert!(ts.contains(&TokenKind::StarEq));
        assert!(ts.contains(&TokenKind::SlashEq));
        assert!(ts.contains(&TokenKind::Match));
        assert!(ts.contains(&TokenKind::Import));
        assert!(ts.contains(&TokenKind::From));
    }

    #[test]
    fn string_interpolation_segments() {
        let ts = kinds(r#""a${x + 1}b""#);
        match &ts[0] {
            TokenKind::InterpStr(segments) => {
                assert_eq!(segments.len(), 3);
                assert_eq!(segments[0], InterpSegment::Lit("a".into()));
                assert_eq!(segments[1], InterpSegment::Expr("x + 1".into()));
                assert_eq!(segments[2], InterpSegment::Lit("b".into()));
            }
            other => panic!("unexpected {other:?}"),
        }
    }
}
