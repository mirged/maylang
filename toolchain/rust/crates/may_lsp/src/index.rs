//! A lightweight project index: definitions, identifier occurrences, imports
//! and import resolution across files.
//!
//! The index is built from the lexer's tokens (which now carry line and
//! column), so identifier spans are exact enough to drive rename edits. It is
//! intentionally scope-insensitive: navigation prefers exact definitions but
//! reference/rename may include shadowed names with the same spelling.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use may_lexer::{tokenize, TokenKind};

/// A 0-based source span (line, character) with a length in characters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub line: usize,
    pub col: usize,
    pub len: usize,
}

impl Span {
    pub fn end_col(&self) -> usize {
        self.col + self.len
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DefKind {
    Function,
    Variable,
    Type,
}

#[derive(Debug, Clone)]
pub struct Def {
    pub name: String,
    pub kind: DefKind,
    pub span: Span,
    /// The declaration's signature, e.g. `pub fun greet(name) -> Str`.
    pub sig: String,
    /// The contiguous comment block directly above the declaration.
    pub doc: String,
    /// Parameter names parsed from the signature (empty for non-functions).
    pub params: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct ImportSpec {
    pub path: String,
    pub alias: Option<String>,
    pub names: Option<Vec<String>>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct Tok {
    /// `Some(name)` for identifier and keyword tokens.
    pub name: Option<String>,
    pub dot: bool,
    /// True for language keywords (never renamed or highlighted as references).
    pub keyword: bool,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct FileIndex {
    pub defs: Vec<Def>,
    pub toks: Vec<Tok>,
    pub imports: Vec<ImportSpec>,
}

impl FileIndex {
    pub fn build(text: &str) -> FileIndex {
        let tokens = tokenize(text).unwrap_or_default();
        let lines: Vec<&str> = text.split('\n').collect();
        let mut toks = Vec::with_capacity(tokens.len());
        let mut defs = Vec::new();
        let mut imports = Vec::new();

        for (i, token) in tokens.iter().enumerate() {
            let span = Span {
                line: token.line.saturating_sub(1) as usize,
                col: token.col.saturating_sub(1) as usize,
                len: 0,
            };
            match &token.kind {
                TokenKind::Ident(name) => toks.push(Tok {
                    name: Some(name.clone()),
                    dot: false,
                    keyword: false,
                    span: Span {
                        len: name.chars().count().max(1),
                        ..span
                    },
                }),
                TokenKind::Dot => toks.push(Tok {
                    name: None,
                    dot: true,
                    keyword: false,
                    span: Span { len: 1, ..span },
                }),
                _ => match keyword_str(&token.kind) {
                    Some(word) => toks.push(Tok {
                        name: Some(word.to_string()),
                        dot: false,
                        keyword: true,
                        span: Span {
                            len: word.chars().count(),
                            ..span
                        },
                    }),
                    None => toks.push(Tok {
                        name: None,
                        dot: false,
                        keyword: false,
                        span,
                    }),
                },
            }

            // Declarations: `fun name`, `let name`, `mut name`, `struct name`,
            // `enum name` (the last two are identifiers in the lexer).
            let decl_kind = match &token.kind {
                TokenKind::Fun => Some(DefKind::Function),
                TokenKind::Let | TokenKind::Mut => Some(DefKind::Variable),
                TokenKind::Ident(word) if word == "struct" || word == "enum" => {
                    Some(DefKind::Type)
                }
                _ => None,
            };
            if let (Some(kind), Some(next)) = (decl_kind, tokens.get(i + 1)) {
                if let TokenKind::Ident(name) = &next.kind {
                    let line = next.line.saturating_sub(1) as usize;
                    let sig = signature_of(&lines, line);
                    defs.push(Def {
                        name: name.clone(),
                        kind,
                        span: Span {
                            line,
                            col: next.col.saturating_sub(1) as usize,
                            len: name.chars().count().max(1),
                        },
                        params: crate::docs::signature_params(&sig),
                        sig,
                        doc: doc_before(&lines, line),
                    });
                }
            }

            // Imports.
            match &token.kind {
                TokenKind::Import => {
                    if let Some(TokenKind::Str(path)) = tokens.get(i + 1).map(|t| &t.kind) {
                        let mut alias = None;
                        if let (Some(a), Some(ns)) =
                            (tokens.get(i + 2), tokens.get(i + 3))
                        {
                            if matches!(&a.kind, TokenKind::Ident(w) if w == "as") {
                                if let TokenKind::Ident(ns_name) = &ns.kind {
                                    alias = Some(ns_name.clone());
                                }
                            }
                        }
                        imports.push(ImportSpec {
                            path: path.clone(),
                            alias,
                            names: None,
                            span,
                        });
                    }
                }
                TokenKind::From => {
                    if let Some(TokenKind::Str(path)) = tokens.get(i + 1).map(|t| &t.kind) {
                        let mut names = Vec::new();
                        let mut k = i + 2;
                        if matches!(tokens.get(k).map(|t| &t.kind), Some(TokenKind::Import)) {
                            k += 1;
                        }
                        while let Some(tok) = tokens.get(k) {
                            match &tok.kind {
                                TokenKind::Ident(name) => {
                                    names.push(name.clone());
                                    k += 1;
                                }
                                TokenKind::Comma => k += 1,
                                _ => break,
                            }
                        }
                        imports.push(ImportSpec {
                            path: path.clone(),
                            alias: None,
                            names: Some(names),
                            span,
                        });
                    }
                }
                _ => {}
            }
        }

        FileIndex {
            defs,
            toks,
            imports,
        }
    }

    pub fn definition(&self, name: &str) -> Option<&Def> {
        self.defs.iter().find(|d| d.name == name)
    }

    /// The identifier *or keyword* token containing (line, character).
    pub fn token_at(&self, line: usize, col: usize) -> Option<(&Tok, usize)> {
        self.toks
            .iter()
            .enumerate()
            .find(|(_, tok)| {
                tok.name.is_some()
                    && tok.span.line == line
                    && col >= tok.span.col
                    && col < tok.span.col + tok.span.len
            })
            .map(|(i, tok)| (tok, i))
    }

    /// The namespace qualifier before the identifier at `idx` (`ns.name`).
    pub fn qualifier_before(&self, idx: usize) -> Option<&str> {
        let dot = self.toks.get(idx.checked_sub(1)?)?;
        if !dot.dot {
            return None;
        }
        let ns = self.toks.get(idx.checked_sub(2)?)?;
        ns.name.as_deref()
    }

    pub fn is_qualified(&self, idx: usize) -> bool {
        self.toks
            .get(idx.wrapping_sub(1))
            .map(|t| t.dot)
            .unwrap_or(false)
    }

}

/// Shared, incrementally-updated index over a project root.
pub struct Workspace {
    pub root: Option<PathBuf>,
    pub stdlib: Vec<PathBuf>,
    pub files: HashMap<PathBuf, FileIndex>,
    scanned: bool,
}

impl Workspace {
    pub fn new(root: Option<PathBuf>) -> Workspace {
        let mut stdlib = Vec::new();
        if let Ok(env) = std::env::var("MAYLANG_STDLIB") {
            for part in env.split(':').filter(|p| !p.is_empty()) {
                stdlib.push(PathBuf::from(part));
            }
        }
        if let Some(root) = &root {
            stdlib.push(root.join("stdlib"));
            stdlib.push(root.join("..").join("stdlib"));
        }
        Workspace {
            root,
            stdlib,
            files: HashMap::new(),
            scanned: false,
        }
    }

    pub fn upsert(&mut self, path: &Path, text: &str) {
        let path = normalize(path);
        self.files.insert(path, FileIndex::build(text));
    }

    pub fn remove(&mut self, path: &Path) {
        self.files.remove(&normalize(path));
    }

    /// Force the next `ensure_scanned` to re-read the tree.
    pub fn invalidate_scan(&mut self) {
        self.scanned = false;
    }

    pub fn get(&self, path: &Path) -> Option<&FileIndex> {
        self.files.get(&normalize(path))
    }

    /// Scan the project root (and the stdlib) for `.may` files, once.
    pub fn ensure_scanned(&mut self) {
        if self.scanned {
            return;
        }
        self.scanned = true;
        let mut roots: Vec<PathBuf> = Vec::new();
        if let Some(root) = &self.root {
            roots.push(root.clone());
        }
        for dir in &self.stdlib {
            roots.push(dir.clone());
        }
        let mut found = Vec::new();
        for root in roots {
            if root.exists() {
                walk(&root, 0, &mut found);
            }
        }
        for path in found {
            let path = normalize(&path);
            if self.files.contains_key(&path) {
                continue;
            }
            if let Ok(text) = std::fs::read_to_string(&path) {
                self.files.insert(path, FileIndex::build(&text));
            }
        }
    }

    /// Load a file and everything it imports, so cross-file navigation reaches
    /// targets outside the scanned root (e.g. a sibling project or the stdlib).
    pub fn ensure_closure(&mut self, start: &Path) {
        let start = normalize(start);
        let mut seen: HashSet<PathBuf> = HashSet::new();
        let mut queue = vec![start];
        while let Some(file) = queue.pop() {
            if !seen.insert(file.clone()) {
                continue;
            }
            if !self.files.contains_key(&file) {
                if let Ok(text) = std::fs::read_to_string(&file) {
                    self.files.insert(file.clone(), FileIndex::build(&text));
                } else {
                    continue;
                }
            }
            let imports: Vec<String> = match self.files.get(&file) {
                Some(index) => index.imports.iter().map(|i| i.path.clone()).collect(),
                None => continue,
            };
            for spec in imports {
                if let Some(target) = self.resolve_import(&file, &spec) {
                    if !seen.contains(&target) {
                        queue.push(target);
                    }
                }
            }
        }
    }

    pub fn resolve_import(&self, from: &Path, spec: &str) -> Option<PathBuf> {
        let mut name = spec.to_string();
        if !name.ends_with(".may") {
            name.push_str(".may");
        }
        let candidate = from
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(&name);
        if candidate.exists() {
            return Some(normalize(&candidate));
        }
        for dir in &self.stdlib {
            let candidate = dir.join(&name);
            if candidate.exists() {
                return Some(normalize(&candidate));
            }
        }
        None
    }

    /// `start` plus everything it transitively imports.
    pub fn import_closure(&self, start: &Path) -> Vec<PathBuf> {
        let start = normalize(start);
        let mut seen: HashSet<PathBuf> = HashSet::new();
        let mut queue = vec![start];
        let mut out = Vec::new();
        while let Some(file) = queue.pop() {
            if !seen.insert(file.clone()) {
                continue;
            }
            out.push(file.clone());
            if let Some(index) = self.files.get(&file) {
                for imp in &index.imports {
                    if let Some(target) = self.resolve_import(&file, &imp.path) {
                        if !seen.contains(&target) {
                            queue.push(target);
                        }
                    }
                }
            }
        }
        out
    }

    /// Files that can see `owner`: its import closure plus every file that
    /// (transitively) imports it.
    pub fn related_files(&self, owner: &Path) -> Vec<PathBuf> {
        let owner = normalize(owner);
        let mut related: HashSet<PathBuf> = self.import_closure(&owner).into_iter().collect();
        let all: Vec<PathBuf> = self.files.keys().cloned().collect();
        for file in all {
            if self.import_closure(&file).contains(&owner) {
                related.insert(file);
            }
        }
        let mut out: Vec<PathBuf> = related.into_iter().collect();
        out.sort();
        out
    }

    /// Resolve `name` to a definition. Handles `ns.name` qualifiers and
    /// unqualified imports before falling back to the closure and the whole
    /// workspace.
    pub fn find_definition(
        &self,
        file: &Path,
        name: &str,
        qualifier: Option<&str>,
    ) -> Option<(PathBuf, Def)> {
        let file = normalize(file);
        let index = self.files.get(&file)?;

        if let Some(ns) = qualifier {
            for imp in &index.imports {
                let matches = imp.alias.as_deref() == Some(ns)
                    || (imp.alias.is_none()
                        && Path::new(&imp.path)
                            .file_stem()
                            .and_then(|s| s.to_str())
                            == Some(ns));
                if matches {
                    if let Some(target) = self.resolve_import(&file, &imp.path) {
                        if let Some(def) = self.definition_in(&target, name) {
                            return Some((target, def));
                        }
                    }
                }
            }
        }

        if let Some(def) = index.definition(name).cloned() {
            return Some((file.clone(), def));
        }

        // Unqualified imports first, then the closure, then anything.
        for imp in &index.imports {
            let exposes = match &imp.names {
                None => imp.alias.is_none(),
                Some(names) => names.iter().any(|n| n == name),
            };
            if exposes {
                if let Some(target) = self.resolve_import(&file, &imp.path) {
                    if let Some(def) = self.definition_in(&target, name) {
                        return Some((target, def));
                    }
                }
            }
        }
        for other in self.import_closure(&file) {
            if other == file {
                continue;
            }
            if let Some(def) = self.definition_in(&other, name) {
                return Some((other, def));
            }
        }
        let mut keys: Vec<PathBuf> = self.files.keys().cloned().collect();
        keys.sort();
        for other in keys {
            if let Some(def) = self.definition_in(&other, name) {
                return Some((other, def));
            }
        }
        None
    }

    pub fn definition_in(&self, file: &Path, name: &str) -> Option<Def> {
        self.files
            .get(&normalize(file))
            .and_then(|index| index.definition(name))
            .cloned()
    }
}

fn keyword_str(kind: &TokenKind) -> Option<&'static str> {
    Some(match kind {
        TokenKind::Fun => "fun",
        TokenKind::Let => "let",
        TokenKind::Mut => "mut",
        TokenKind::If => "if",
        TokenKind::Else => "else",
        TokenKind::While => "while",
        TokenKind::For => "for",
        TokenKind::In => "in",
        TokenKind::Return => "return",
        TokenKind::True => "true",
        TokenKind::False => "false",
        TokenKind::Nil => "nil",
        TokenKind::May => "may",
        TokenKind::Otherwise => "otherwise",
        TokenKind::Unless => "unless",
        TokenKind::And => "and",
        TokenKind::Or => "or",
        TokenKind::Not => "not",
        TokenKind::Break => "break",
        TokenKind::Continue => "continue",
        TokenKind::Match => "match",
        TokenKind::Import => "import",
        TokenKind::From => "from",
        _ => return None,
    })
}

fn normalize(path: &Path) -> PathBuf {
    std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
}

/// The declaration line up to the body's opening brace.
fn signature_of(lines: &[&str], line: usize) -> String {
    let raw = lines.get(line).copied().unwrap_or("").trim();
    let cut = match raw.find('{') {
        Some(i) => &raw[..i],
        None => raw,
    };
    cut.trim().to_string()
}

/// The contiguous `//` / `///` comment block directly above a declaration.
fn doc_before(lines: &[&str], line: usize) -> String {
    let mut collected: Vec<String> = Vec::new();
    let mut i = line;
    while i > 0 {
        i -= 1;
        let t = lines[i].trim();
        if t.starts_with("///") || t.starts_with("//") {
            collected.push(t.trim_start_matches('/').trim().to_string());
        } else {
            break;
        }
    }
    collected.reverse();
    collected.join("\n")
}

fn walk(dir: &Path, depth: usize, out: &mut Vec<PathBuf>) {
    if depth > 64 || out.len() > 5000 {
        return;
    }
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with('.') || name == "target" || name == "node_modules" {
            continue;
        }
        if path.is_dir() {
            walk(&path, depth + 1, out);
        } else if path.extension().and_then(|e| e.to_str()) == Some("may") {
            out.push(path);
        }
    }
}
