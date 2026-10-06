//! `maylang-lsp` — a Language Server Protocol server for Maylang.
//!
//! Speaks JSON-RPC 2.0 over stdio and reuses the real lexer, parser and gradual
//! checker. Features: diagnostics, hover, go-to-definition, completion,
//! document symbols, formatting, references and rename — the last four with
//! cross-file navigation through a project-wide index. No external crates.

mod docs;
mod format;
mod index;
mod json;
mod uri;

use std::collections::HashMap;
use std::io::{self, BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use index::{DefKind, Span, Workspace};
use json::Json;
use uri::{path_to_uri, uri_to_path};

const VERSION: &str = env!("CARGO_PKG_VERSION");

// ---------------------------------------------------------------- json sugar

fn obj(pairs: Vec<(&str, Json)>) -> Json {
    Json::Obj(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
}

fn arr(items: Vec<Json>) -> Json {
    Json::Arr(items)
}

fn strj(s: impl Into<String>) -> Json {
    Json::Str(s.into())
}

fn int(i: i64) -> Json {
    Json::Int(i)
}

fn markdown(value: &str) -> Json {
    obj(vec![(
        "contents",
        obj(vec![("kind", strj("markdown")), ("value", strj(value))]),
    )])
}

fn span_range(span: Span) -> Json {
    obj(vec![
        (
            "start",
            obj(vec![
                ("line", int(span.line as i64)),
                ("character", int(span.col as i64)),
            ]),
        ),
        (
            "end",
            obj(vec![
                ("line", int(span.line as i64)),
                ("character", int(span.end_col() as i64)),
            ]),
        ),
    ])
}

fn line_range(line: usize, end: usize) -> Json {
    obj(vec![
        (
            "start",
            obj(vec![("line", int(line as i64)), ("character", int(0))]),
        ),
        (
            "end",
            obj(vec![("line", int(line as i64)), ("character", int(end as i64))]),
        ),
    ])
}

fn location(path: &Path, span: Span) -> Json {
    obj(vec![
        ("uri", strj(path_to_uri(path))),
        ("range", span_range(span)),
    ])
}

// ---------------------------------------------------------------- text util

fn line_count(text: &str) -> usize {
    text.split('\n').count()
}

fn line_text(text: &str, line: usize) -> String {
    text.split('\n')
        .nth(line)
        .unwrap_or("")
        .trim_end_matches('\r')
        .to_string()
}

fn line_len(text: &str, line: usize) -> usize {
    line_text(text, line).chars().count()
}

fn full_document_range(text: &str) -> Json {
    let last = line_count(text).saturating_sub(1);
    obj(vec![
        (
            "start",
            obj(vec![("line", int(0)), ("character", int(0))]),
        ),
        (
            "end",
            obj(vec![
                ("line", int(last as i64)),
                ("character", int(line_len(text, last) as i64)),
            ]),
        ),
    ])
}

fn is_ident_char(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

fn is_valid_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(c) if c == '_' || c.is_alphabetic() => {}
        _ => return false,
    }
    chars.all(is_ident_char)
}

// --------------------------------------------------------------- diagnostics

fn split_line(err: &str) -> (usize, String) {
    if let Some(rest) = err.strip_prefix("line ") {
        if let Some((num, msg)) = rest.split_once(':') {
            if let Ok(n) = num.trim().parse::<usize>() {
                return (n.saturating_sub(1), msg.trim().to_string());
            }
        }
    }
    (0, err.to_string())
}

fn diagnostic(text: &str, line: usize, message: &str, severity: i64) -> Json {
    obj(vec![
        ("range", line_range(line, line_len(text, line))),
        ("severity", int(severity)),
        ("source", strj("maylang")),
        ("message", strj(message)),
    ])
}

fn diagnose(text: &str) -> Vec<Json> {
    let mut out = Vec::new();
    match may_parser::parse(text) {
        Err(e) => out.push(diagnostic(
            text,
            (e.line as usize).saturating_sub(1),
            &e.message,
            1,
        )),
        Ok(program) => {
            for err in may_check::check(&program).errors {
                let (line, message) = split_line(&err);
                out.push(diagnostic(text, line, &message, 1));
            }
        }
    }
    out
}

// -------------------------------------------------------------- completion

fn completion_items(index: &index::FileIndex) -> Json {
    let mut seen: Vec<String> = Vec::new();
    let mut items = Vec::new();
    let mut add = |label: String, kind: i64, detail: &str| {
        if seen.contains(&label) {
            return;
        }
        seen.push(label.clone());
        items.push(obj(vec![
            ("label", strj(label)),
            ("kind", int(kind)),
            ("detail", strj(detail)),
        ]));
    };

    for def in &index.defs {
        let (kind, detail) = match def.kind {
            DefKind::Function => (3, "function"),
            DefKind::Variable => (6, "variable"),
            DefKind::Type => (23, "type"),
        };
        add(def.name.clone(), kind, detail);
    }
    for tok in &index.toks {
        if let Some(name) = &tok.name {
            if !tok.keyword {
                add(name.clone(), 6, "identifier");
            }
        }
    }
    for kw in docs::keyword_names() {
        add(kw.to_string(), 14, "keyword");
    }
    for b in docs::builtin_names() {
        add(b.to_string(), 3, "builtin");
    }
    items.sort_by(|a, b| {
        let ka = a.get("label").and_then(Json::as_str).unwrap_or("");
        let kb = b.get("label").and_then(Json::as_str).unwrap_or("");
        ka.cmp(kb)
    });
    arr(items)
}

// ------------------------------------------------------------------- hover

fn def_markdown(def: &index::Def, file: &Path) -> String {
    let signature = if def.sig.is_empty() {
        def.name.clone()
    } else {
        def.sig.clone()
    };
    let mut text = format!("```maylang\n{signature}\n```");
    if !def.doc.is_empty() {
        text.push_str("\n\n");
        text.push_str(&def.doc);
    }
    text.push_str(&format!(
        "\n\n---\n\nDefined in `{}` on line {}.",
        file.file_name().and_then(|n| n.to_str()).unwrap_or("?"),
        def.span.line + 1
    ));
    text
}

// -------------------------------------------------------------- signature help

/// Find the innermost call enclosing the cursor on its line: returns the callee
/// name and the zero-based index of the argument under the cursor.
fn call_context(text: &str, line: usize, character: usize) -> Option<(String, usize)> {
    let chars: Vec<char> = line_text(text, line).chars().collect();
    let mut i = character.min(chars.len());
    let mut depth = 0i32;
    let mut commas = 0usize;
    while i > 0 {
        i -= 1;
        match chars[i] {
            ')' => depth += 1,
            '(' => {
                if depth == 0 {
                    let mut j = i;
                    while j > 0 && chars[j - 1] == ' ' {
                        j -= 1;
                    }
                    let mut k = j;
                    while k > 0 && is_ident_char(chars[k - 1]) {
                        k -= 1;
                    }
                    if k == j {
                        return None;
                    }
                    let name: String = chars[k..j].iter().collect();
                    return Some((name, commas));
                }
                depth -= 1;
            }
            ',' if depth == 0 => commas += 1,
            _ => {}
        }
    }
    None
}

// ------------------------------------------------------------------ server

struct Document {
    text: String,
    version: i64,
}

struct Server {
    workspace: Workspace,
    docs: HashMap<PathBuf, Document>,
    shutdown: bool,
}

fn write_message(value: &Json) -> io::Result<()> {
    let body = value.to_string();
    let mut stdout = io::stdout().lock();
    write!(stdout, "Content-Length: {}\r\n\r\n", body.len())?;
    stdout.write_all(body.as_bytes())?;
    stdout.flush()
}

fn respond(id: &Json, result: Json) {
    let _ = write_message(&obj(vec![
        ("jsonrpc", strj("2.0")),
        ("id", id.clone()),
        ("result", result),
    ]));
}

fn respond_error(id: &Json, code: i64, message: &str) {
    let _ = write_message(&obj(vec![
        ("jsonrpc", strj("2.0")),
        ("id", id.clone()),
        ("error", obj(vec![("code", int(code)), ("message", strj(message))])),
    ]));
}

fn notify(method: &str, params: Json) {
    let _ = write_message(&obj(vec![
        ("jsonrpc", strj("2.0")),
        ("method", strj(method)),
        ("params", params),
    ]));
}

impl Server {
    fn document_text(&self, path: &Path) -> String {
        if let Some(doc) = self.docs.get(path) {
            return doc.text.clone();
        }
        std::fs::read_to_string(path).unwrap_or_default()
    }

    fn ensure_file(&mut self, path: &Path) {
        if self.workspace.get(path).is_some() {
            return;
        }
        let text = self.document_text(path);
        self.workspace.upsert(path, &text);
    }

    fn publish(&self, uri: &str) {
        let path = match uri_to_path(uri) {
            Some(path) => path,
            None => return,
        };
        let text = self.document_text(&path);
        let version = self.docs.get(&path).map(|d| d.version).unwrap_or(0);
        notify(
            "textDocument/publishDiagnostics",
            obj(vec![
                ("uri", strj(uri)),
                ("version", int(version)),
                ("diagnostics", arr(diagnose(&text))),
            ]),
        );
    }

    fn position(params: &Json) -> (usize, usize) {
        let pos = params.get("position");
        let line = pos
            .and_then(|p| p.get("line"))
            .and_then(Json::as_i64)
            .unwrap_or(0)
            .max(0) as usize;
        let character = pos
            .and_then(|p| p.get("character"))
            .and_then(Json::as_i64)
            .unwrap_or(0)
            .max(0) as usize;
        (line, character)
    }

    fn path_from(params: &Json) -> Option<PathBuf> {
        let uri = params.get("textDocument")?.get("uri")?.as_str()?;
        uri_to_path(uri)
    }

    /// Resolve the token at a request position to (path, name, span, qualifier,
    /// is_keyword). Keywords are returned too so hover can document them.
    fn target_at(
        &mut self,
        params: &Json,
    ) -> Option<(PathBuf, String, Span, Option<String>, bool)> {
        let path = Self::path_from(params)?;
        let (line, ch) = Self::position(params);
        self.workspace.ensure_scanned();
        self.ensure_file(&path);
        self.workspace.ensure_closure(&path);
        let index = self.workspace.get(&path)?;
        let (tok, idx) = index.token_at(line, ch)?;
        let name = tok.name.clone()?;
        let span = tok.span;
        let is_keyword = tok.keyword;
        let qualifier = if is_keyword {
            None
        } else {
            index.qualifier_before(idx).map(str::to_string)
        };
        Some((path, name, span, qualifier, is_keyword))
    }

    fn occurrences(
        workspace: &Workspace,
        file: &Path,
        name: &str,
        skip_qualified: bool,
    ) -> Vec<Span> {
        match workspace.get(file) {
            Some(index) => index
                .toks
                .iter()
                .enumerate()
                .filter(|(i, tok)| {
                    tok.name.as_deref() == Some(name)
                        && !tok.keyword
                        && !(skip_qualified && index.is_qualified(*i))
                })
                .map(|(_, tok)| tok.span)
                .collect(),
            None => Vec::new(),
        }
    }

    fn handle_request(&mut self, method: &str, id: &Json, params: &Json) {
        match method {
            "initialize" => {
                let root = initialize_root(params);
                self.workspace = Workspace::new(root);
                let capabilities = obj(vec![
                    ("textDocumentSync", int(1)),
                    ("hoverProvider", Json::Bool(true)),
                    ("definitionProvider", Json::Bool(true)),
                    ("referencesProvider", Json::Bool(true)),
                    (
                        "renameProvider",
                        obj(vec![("prepareProvider", Json::Bool(true))]),
                    ),
                    ("documentFormattingProvider", Json::Bool(true)),
                    (
                        "signatureHelpProvider",
                        obj(vec![("triggerCharacters", arr(vec![strj("("), strj(",")]))]),
                    ),
                    (
                        "completionProvider",
                        obj(vec![("triggerCharacters", arr(vec![strj("."), strj("?")]))]),
                    ),
                    ("documentSymbolProvider", Json::Bool(true)),
                ]);
                respond(
                    id,
                    obj(vec![
                        ("capabilities", capabilities),
                        (
                            "serverInfo",
                            obj(vec![("name", strj("maylang-lsp")), ("version", strj(VERSION))]),
                        ),
                    ]),
                );
            }
            "shutdown" => {
                self.shutdown = true;
                respond(id, Json::Null);
            }
            "textDocument/hover" => respond(id, self.hover(params)),
            "textDocument/definition" => respond(id, self.definition(params)),
            "textDocument/references" => respond(id, self.references(params)),
            "textDocument/prepareRename" => respond(id, self.prepare_rename(params)),
            "textDocument/rename" => respond(id, self.rename(params)),
            "textDocument/formatting" => respond(id, self.formatting(params)),
            "textDocument/signatureHelp" => respond(id, self.signature_help(params)),
            "textDocument/completion" => {
                let result = match Self::path_from(params) {
                    Some(path) => {
                        self.ensure_file(&path);
                        self.workspace
                            .get(&path)
                            .map(completion_items)
                            .unwrap_or_else(|| arr(Vec::new()))
                    }
                    None => arr(Vec::new()),
                };
                respond(id, result);
            }
            "textDocument/documentSymbol" => {
                let result = match Self::path_from(params) {
                    Some(path) => {
                        self.ensure_file(&path);
                        self.document_symbols(&path)
                    }
                    None => arr(Vec::new()),
                };
                respond(id, result);
            }
            other => respond_error(id, -32601, &format!("method `{other}` not found")),
        }
    }

    fn hover(&mut self, params: &Json) -> Json {
        let (path, name, _, qualifier, _) = match self.target_at(params) {
            Some(target) => target,
            None => return Json::Null,
        };
        // Keywords are reserved, so they can't be shadowed.
        if let Some(doc) = docs::keyword_markdown(&name) {
            return markdown(&doc);
        }
        // A real definition (project or stdlib source) wins over a built-in.
        if let Some((owner, def)) = self
            .workspace
            .find_definition(&path, &name, qualifier.as_deref())
        {
            return markdown(&def_markdown(&def, &owner));
        }
        if let Some(doc) = docs::builtin_markdown(&name) {
            return markdown(&doc);
        }
        Json::Null
    }

    fn definition(&mut self, params: &Json) -> Json {
        let (path, name, _, qualifier, is_keyword) = match self.target_at(params) {
            Some(target) => target,
            None => return Json::Null,
        };
        if is_keyword {
            return Json::Null;
        }
        match self
            .workspace
            .find_definition(&path, &name, qualifier.as_deref())
        {
            Some((owner, def)) => arr(vec![location(&owner, def.span)]),
            None => Json::Null,
        }
    }

    fn references(&mut self, params: &Json) -> Json {
        let (path, name, _, qualifier, is_keyword) = match self.target_at(params) {
            Some(target) => target,
            None => return Json::Null,
        };
        if is_keyword {
            return Json::Null;
        }
        let found = self
            .workspace
            .find_definition(&path, &name, qualifier.as_deref());
        let (owner, kind) = match found {
            Some((owner, def)) => (owner, def.kind),
            None => (path.clone(), DefKind::Variable),
        };
        let files = if kind == DefKind::Variable {
            vec![owner.clone()]
        } else {
            self.workspace.related_files(&owner)
        };
        let skip_qualified = kind == DefKind::Variable;
        let mut out = Vec::new();
        for file in files {
            for span in Self::occurrences(&self.workspace, &file, &name, skip_qualified) {
                out.push(location(&file, span));
            }
        }
        arr(out)
    }

    fn prepare_rename(&mut self, params: &Json) -> Json {
        match self.target_at(params) {
            Some((_, name, span, _, false)) if is_valid_identifier(&name) => obj(vec![
                ("range", span_range(span)),
                ("placeholder", strj(name)),
            ]),
            _ => Json::Null,
        }
    }

    fn rename(&mut self, params: &Json) -> Json {
        let new_name = match params.get("newName").and_then(Json::as_str) {
            Some(name) => name.to_string(),
            None => return Json::Null,
        };
        if !is_valid_identifier(&new_name) || docs::is_keyword(&new_name) {
            return Json::Null;
        }
        let (path, name, _, qualifier, is_keyword) = match self.target_at(params) {
            Some(target) => target,
            None => return Json::Null,
        };
        if is_keyword {
            return Json::Null;
        }
        let found = self
            .workspace
            .find_definition(&path, &name, qualifier.as_deref());
        let (owner, kind) = match found {
            Some((owner, def)) => (owner, def.kind),
            None => (path.clone(), DefKind::Variable),
        };
        let files = if kind == DefKind::Variable {
            vec![owner.clone()]
        } else {
            self.workspace.related_files(&owner)
        };
        let skip_qualified = kind == DefKind::Variable;

        let mut changes: Vec<(String, Json)> = Vec::new();
        for file in files {
            let spans = Self::occurrences(&self.workspace, &file, &name, skip_qualified);
            if spans.is_empty() {
                continue;
            }
            let edits: Vec<Json> = spans
                .into_iter()
                .map(|span| {
                    obj(vec![
                        ("range", span_range(span)),
                        ("newText", strj(new_name.clone())),
                    ])
                })
                .collect();
            changes.push((path_to_uri(&file), arr(edits)));
        }
        obj(vec![("changes", Json::Obj(changes))])
    }

    fn formatting(&mut self, params: &Json) -> Json {
        let path = match Self::path_from(params) {
            Some(path) => path,
            None => return arr(Vec::new()),
        };
        let text = self.document_text(&path);
        let options = params.get("options");
        let tab_size = options
            .and_then(|o| o.get("tabSize"))
            .and_then(Json::as_i64)
            .unwrap_or(4)
            .clamp(1, 16) as usize;
        let insert_spaces = options
            .and_then(|o| o.get("insertSpaces"))
            .map(|v| v == &Json::Bool(true))
            .unwrap_or(true);

        let formatted = format::format(&text, insert_spaces, tab_size);
        if formatted == text {
            return arr(Vec::new());
        }
        arr(vec![obj(vec![
            ("range", full_document_range(&text)),
            ("newText", strj(formatted)),
        ])])
    }

    fn signature_help(&mut self, params: &Json) -> Json {
        let path = match Self::path_from(params) {
            Some(path) => path,
            None => return Json::Null,
        };
        let (line, ch) = Self::position(params);
        let text = self.document_text(&path);
        let (name, active) = match call_context(&text, line, ch) {
            Some(context) => context,
            None => return Json::Null,
        };
        self.workspace.ensure_scanned();
        self.ensure_file(&path);
        self.workspace.ensure_closure(&path);

        let (signature, parameters) =
            if let Some((_, def)) = self.workspace.find_definition(&path, &name, None) {
                (def.sig.clone(), def.params.clone())
            } else if let Some(sig) = docs::builtin_signature(&name) {
                (sig.to_string(), docs::signature_params(sig))
            } else {
                return Json::Null;
            };
        if parameters.is_empty() {
            return Json::Null;
        }
        let active = active.min(parameters.len() - 1);
        let params_json: Vec<Json> = parameters
            .iter()
            .map(|p| obj(vec![("label", strj(p.clone()))]))
            .collect();
        obj(vec![
            (
                "signatures",
                arr(vec![obj(vec![
                    ("label", strj(signature)),
                    ("parameters", arr(params_json)),
                ])]),
            ),
            ("activeSignature", int(0)),
            ("activeParameter", int(active as i64)),
        ])
    }

    fn document_symbols(&self, path: &Path) -> Json {
        let index = match self.workspace.get(path) {
            Some(index) => index,
            None => return arr(Vec::new()),
        };
        let mut out = Vec::new();
        for def in &index.defs {
            let kind = match def.kind {
                DefKind::Function => 12,
                DefKind::Variable => 13,
                DefKind::Type => 23,
            };
            out.push(symbol_json(&def.name, kind, def.span));
        }
        for imp in &index.imports {
            let name = imp.alias.clone().unwrap_or_else(|| {
                Path::new(&imp.path)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or(&imp.path)
                    .to_string()
            });
            out.push(symbol_json(&name, 2, imp.span));
        }
        arr(out)
    }

    fn handle_notification(&mut self, method: &str, params: &Json) {
        match method {
            "initialized" => {}
            "textDocument/didOpen" => {
                if let Some(td) = params.get("textDocument") {
                    if let (Some(uri), Some(text)) = (td.get("uri").and_then(Json::as_str), td.get("text").and_then(Json::as_str)) {
                        if let Some(path) = uri_to_path(uri) {
                            let version = td.get("version").and_then(Json::as_i64).unwrap_or(0);
                            self.docs.insert(
                                path.clone(),
                                Document { text: text.to_string(), version },
                            );
                            self.workspace.upsert(&path, text);
                            self.publish(uri);
                        }
                    }
                }
            }
            "textDocument/didChange" => {
                let uri = params
                    .get("textDocument")
                    .and_then(|td| td.get("uri"))
                    .and_then(Json::as_str)
                    .map(str::to_string);
                let version = params
                    .get("textDocument")
                    .and_then(|td| td.get("version"))
                    .and_then(Json::as_i64)
                    .unwrap_or(0);
                let text = params
                    .get("contentChanges")
                    .and_then(Json::as_arr)
                    .and_then(|c| c.last())
                    .and_then(|change| change.get("text"))
                    .and_then(Json::as_str)
                    .map(str::to_string);
                if let (Some(uri), Some(text)) = (uri, text) {
                    if let Some(path) = uri_to_path(&uri) {
                        self.docs.insert(
                            path.clone(),
                            Document { text: text.clone(), version },
                        );
                        self.workspace.upsert(&path, &text);
                        self.publish(&uri);
                    }
                }
            }
            "textDocument/didSave" => {
                if let Some(uri) = params
                    .get("textDocument")
                    .and_then(|td| td.get("uri"))
                    .and_then(Json::as_str)
                {
                    self.publish(uri);
                }
            }
            "textDocument/didClose" => {
                if let Some(uri) = params
                    .get("textDocument")
                    .and_then(|td| td.get("uri"))
                    .and_then(Json::as_str)
                {
                    if let Some(path) = uri_to_path(uri) {
                        self.docs.remove(&path);
                        self.workspace.remove(&path);
                        // Republish empty diagnostics for the closed file.
                        notify(
                            "textDocument/publishDiagnostics",
                            obj(vec![("uri", strj(uri)), ("diagnostics", arr(Vec::new()))]),
                        );
                    }
                }
            }
            "workspace/didChangeWatchedFiles" => {
                if let Some(changes) = params.get("changes").and_then(Json::as_arr) {
                    for change in changes {
                        if let Some(uri) = change.get("uri").and_then(Json::as_str) {
                            if let Some(path) = uri_to_path(uri) {
                                if !self.docs.contains_key(&path) {
                                    self.workspace.remove(&path);
                                }
                            }
                        }
                    }
                }
                self.workspace.invalidate_scan();
            }
            _ => {}
        }
    }
}

fn symbol_json(name: &str, kind: i64, span: Span) -> Json {
    let range = span_range(span);
    obj(vec![
        ("name", strj(name)),
        ("kind", int(kind)),
        ("range", range.clone()),
        ("selectionRange", range),
        ("children", arr(Vec::new())),
    ])
}

fn initialize_root(params: &Json) -> Option<PathBuf> {
    if let Some(uri) = params.get("rootUri").and_then(Json::as_str) {
        if let Some(path) = uri_to_path(uri) {
            return Some(path);
        }
    }
    if let Some(path) = params.get("rootPath").and_then(Json::as_str) {
        return Some(PathBuf::from(path));
    }
    if let Some(folders) = params.get("workspaceFolders").and_then(Json::as_arr) {
        if let Some(uri) = folders.first().and_then(|f| f.get("uri")).and_then(Json::as_str) {
            return uri_to_path(uri);
        }
    }
    None
}

// -------------------------------------------------------------------- main

fn read_message(reader: &mut impl BufRead) -> io::Result<Option<String>> {
    let mut content_length: Option<usize> = None;
    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line)?;
        if n == 0 {
            return Ok(None);
        }
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        if let Some(rest) = trimmed.strip_prefix("Content-Length:") {
            content_length = rest.trim().parse::<usize>().ok();
        }
    }
    let length = match content_length {
        Some(l) => l,
        None => return Ok(None),
    };
    let mut buffer = vec![0u8; length];
    reader.read_exact(&mut buffer)?;
    Ok(Some(String::from_utf8_lossy(&buffer).into_owned()))
}

const FEATURES: &str =
    "diagnostics, hover-docs, definition, references, rename, formatting, signatureHelp, symbols";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--version" || a == "-V") {
        println!("maylang-lsp {VERSION} ({FEATURES})");
        return;
    }
    if args.iter().any(|a| a == "--help" || a == "-h") {
        println!("maylang-lsp {VERSION} — Maylang language server");
        println!("Speaks LSP over stdio. Features: {FEATURES}");
        println!();
        println!("  maylang-lsp             run the server (stdio)");
        println!("  maylang-lsp --version   print the version and features");
        println!("  maylang-lsp --help      show this help");
        return;
    }

    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    let mut server = Server {
        workspace: Workspace::new(None),
        docs: HashMap::new(),
        shutdown: false,
    };

    loop {
        let raw = match read_message(&mut reader) {
            Ok(Some(raw)) => raw,
            Ok(None) => break,
            Err(_) => break,
        };
        let message = match json::parse(&raw) {
            Ok(message) => message,
            Err(_) => continue,
        };
        let method = message
            .get("method")
            .and_then(Json::as_str)
            .map(str::to_string);
        let id = message.get("id").cloned();
        let params = message.get("params").cloned().unwrap_or(Json::Null);

        if method.as_deref() == Some("exit") {
            break;
        }
        match (method, id) {
            (Some(method), Some(id)) => server.handle_request(&method, &id, &params),
            (Some(method), None) => server.handle_notification(&method, &params),
            (None, _) => {}
        }
    }

    std::process::exit(if server.shutdown { 0 } else { 1 });
}
