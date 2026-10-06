//! A conservative, comment-preserving formatter.
//!
//! It re-indents by brace depth (using the lexer, so braces inside strings and
//! comments are ignored), trims trailing whitespace, collapses runs of blank
//! lines and ends the file with a single newline. It never reflows or reorders
//! tokens, so comments and layout of individual statements are preserved.

use std::collections::HashMap;

use may_lexer::{tokenize, TokenKind};

pub fn format(text: &str, insert_spaces: bool, tab_size: usize) -> String {
    let tokens = match tokenize(text) {
        Ok(tokens) => tokens,
        Err(_) => return text.to_string(), // don't touch code that won't lex
    };

    let mut opens: HashMap<usize, i64> = HashMap::new();
    let mut closes: HashMap<usize, i64> = HashMap::new();
    let mut first_is_close: HashMap<usize, bool> = HashMap::new();
    for token in &tokens {
        if token.line == 0 {
            continue;
        }
        let line = token.line as usize - 1;
        first_is_close
            .entry(line)
            .or_insert(matches!(token.kind, TokenKind::RBrace));
        match token.kind {
            TokenKind::LBrace => *opens.entry(line).or_insert(0) += 1,
            TokenKind::RBrace => *closes.entry(line).or_insert(0) += 1,
            _ => {}
        }
    }

    let trailing_newline = text.ends_with('\n');
    let raw_lines: Vec<&str> = text.split('\n').collect();
    let unit = if insert_spaces {
        " ".repeat(tab_size.max(1))
    } else {
        "\t".to_string()
    };

    let mut depth: i64 = 0;
    let mut out_lines: Vec<String> = Vec::new();
    let mut last_blank = false;

    for (i, raw) in raw_lines.iter().enumerate() {
        if i + 1 == raw_lines.len() && raw.is_empty() && trailing_newline {
            break;
        }
        let content = raw.trim();
        if content.is_empty() {
            if !last_blank {
                out_lines.push(String::new());
                last_blank = true;
            }
            continue;
        }
        let mut indent = depth;
        if first_is_close.get(&i).copied().unwrap_or(false) && indent > 0 {
            indent -= 1;
        }
        let prefix = unit.repeat(indent.max(0) as usize);
        out_lines.push(format!("{prefix}{content}"));
        last_blank = false;

        depth += opens.get(&i).copied().unwrap_or(0) - closes.get(&i).copied().unwrap_or(0);
        if depth < 0 {
            depth = 0;
        }
    }

    while out_lines.last().map(|l| l.is_empty()).unwrap_or(false) {
        out_lines.pop();
    }

    let mut result = out_lines.join("\n");
    if !result.is_empty() {
        result.push('\n');
    }
    result
}
