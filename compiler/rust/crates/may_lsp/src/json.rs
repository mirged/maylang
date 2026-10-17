//! A tiny, dependency-free JSON model for JSON-RPC.
//!
//! The compiler workspace deliberately has no external crates, so the LSP
//! server carries its own JSON reader/writer. It covers the full JSON grammar
//! needed by the protocol (objects, arrays, strings with escapes, numbers,
//! booleans, null).

use std::fmt::Write as _;

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Json::Int(i) => Some(*i),
            _ => None,
        }
    }

    pub fn as_arr(&self) -> Option<&[Json]> {
        match self {
            Json::Arr(a) => Some(a),
            _ => None,
        }
    }

    pub fn to_string(&self) -> String {
        let mut out = String::new();
        write_json(&mut out, self);
        out
    }
}

fn write_json(out: &mut String, value: &Json) {
    match value {
        Json::Null => out.push_str("null"),
        Json::Bool(true) => out.push_str("true"),
        Json::Bool(false) => out.push_str("false"),
        Json::Int(i) => {
            let _ = write!(out, "{i}");
        }
        Json::Float(f) => {
            if f.is_finite() {
                let _ = write!(out, "{f}");
            } else {
                out.push_str("null");
            }
        }
        Json::Str(s) => write_string(out, s),
        Json::Arr(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json(out, item);
            }
            out.push(']');
        }
        Json::Obj(entries) => {
            out.push('{');
            for (i, (key, item)) in entries.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_string(out, key);
                out.push(':');
                write_json(out, item);
            }
            out.push('}');
        }
    }
}

fn write_string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Parse a JSON document, returning a human-readable error on failure.
pub fn parse(input: &str) -> Result<Json, String> {
    let chars: Vec<char> = input.chars().collect();
    let mut parser = Parser { chars, pos: 0 };
    parser.skip_ws();
    let value = parser.value()?;
    parser.skip_ws();
    if parser.pos != parser.chars.len() {
        return Err(format!("trailing characters at {}", parser.pos));
    }
    Ok(value)
}

struct Parser {
    chars: Vec<char>,
    pos: usize,
}

impl Parser {
    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn bump(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.pos += 1;
        Some(c)
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(' ' | '\t' | '\n' | '\r')) {
            self.pos += 1;
        }
    }

    fn expect(&mut self, expected: char) -> Result<(), String> {
        if self.bump() == Some(expected) {
            Ok(())
        } else {
            Err(format!("expected `{expected}` at {}", self.pos))
        }
    }

    fn value(&mut self) -> Result<Json, String> {
        match self.peek() {
            Some('{') => self.object(),
            Some('[') => self.array(),
            Some('"') => Ok(Json::Str(self.string()?)),
            Some('t') | Some('f') => self.boolean(),
            Some('n') => self.null(),
            Some(c) if c == '-' || c.is_ascii_digit() => self.number(),
            other => Err(format!("unexpected {other:?} at {}", self.pos)),
        }
    }

    fn object(&mut self) -> Result<Json, String> {
        self.expect('{')?;
        let mut entries = Vec::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.pos += 1;
            return Ok(Json::Obj(entries));
        }
        loop {
            self.skip_ws();
            let key = self.string()?;
            self.skip_ws();
            self.expect(':')?;
            self.skip_ws();
            let value = self.value()?;
            entries.push((key, value));
            self.skip_ws();
            match self.bump() {
                Some(',') => continue,
                Some('}') => break,
                other => return Err(format!("expected `,` or `}}`, found {other:?}")),
            }
        }
        Ok(Json::Obj(entries))
    }

    fn array(&mut self) -> Result<Json, String> {
        self.expect('[')?;
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.pos += 1;
            return Ok(Json::Arr(items));
        }
        loop {
            self.skip_ws();
            items.push(self.value()?);
            self.skip_ws();
            match self.bump() {
                Some(',') => continue,
                Some(']') => break,
                other => return Err(format!("expected `,` or `]`, found {other:?}")),
            }
        }
        Ok(Json::Arr(items))
    }

    fn string(&mut self) -> Result<String, String> {
        self.expect('"')?;
        let mut out = String::new();
        loop {
            match self.bump() {
                None => return Err("unterminated string".to_string()),
                Some('"') => return Ok(out),
                Some('\\') => match self.bump() {
                    Some('"') => out.push('"'),
                    Some('\\') => out.push('\\'),
                    Some('/') => out.push('/'),
                    Some('b') => out.push('\u{08}'),
                    Some('f') => out.push('\u{0c}'),
                    Some('n') => out.push('\n'),
                    Some('r') => out.push('\r'),
                    Some('t') => out.push('\t'),
                    Some('u') => out.push(self.unicode_escape()?),
                    other => return Err(format!("bad escape {other:?}")),
                },
                Some(c) => out.push(c),
            }
        }
    }

    fn unicode_escape(&mut self) -> Result<char, String> {
        let high = self.hex4()?;
        if (0xD800..0xDC00).contains(&high) {
            // Surrogate pair.
            if self.bump() != Some('\\') || self.bump() != Some('u') {
                return Err("expected low surrogate".to_string());
            }
            let low = self.hex4()?;
            let combined = 0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00);
            char::from_u32(combined).ok_or_else(|| "invalid surrogate pair".to_string())
        } else {
            char::from_u32(high).ok_or_else(|| "invalid \\u escape".to_string())
        }
    }

    fn hex4(&mut self) -> Result<u32, String> {
        let mut value = 0u32;
        for _ in 0..4 {
            let c = self.bump().ok_or_else(|| "short \\u escape".to_string())?;
            let digit = c.to_digit(16).ok_or_else(|| "bad hex digit".to_string())?;
            value = value * 16 + digit;
        }
        Ok(value)
    }

    fn number(&mut self) -> Result<Json, String> {
        let start = self.pos;
        let mut is_float = false;
        if self.peek() == Some('-') {
            self.pos += 1;
        }
        while let Some(c) = self.peek() {
            match c {
                '0'..='9' => self.pos += 1,
                '.' | 'e' | 'E' | '+' | '-' => {
                    is_float = true;
                    self.pos += 1;
                }
                _ => break,
            }
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        if is_float {
            text.parse::<f64>()
                .map(Json::Float)
                .map_err(|_| format!("invalid number `{text}`"))
        } else {
            text.parse::<i64>()
                .map(Json::Int)
                .map_err(|_| format!("invalid number `{text}`"))
        }
    }

    fn boolean(&mut self) -> Result<Json, String> {
        if self.consume_word("true") {
            Ok(Json::Bool(true))
        } else if self.consume_word("false") {
            Ok(Json::Bool(false))
        } else {
            Err(format!("invalid literal at {}", self.pos))
        }
    }

    fn null(&mut self) -> Result<Json, String> {
        if self.consume_word("null") {
            Ok(Json::Null)
        } else {
            Err(format!("invalid literal at {}", self.pos))
        }
    }

    fn consume_word(&mut self, word: &str) -> bool {
        let end = self.pos + word.len();
        if end <= self.chars.len() && self.chars[self.pos..end].iter().collect::<String>() == word {
            self.pos = end;
            true
        } else {
            false
        }
    }
}
