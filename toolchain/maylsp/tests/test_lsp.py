#!/usr/bin/env python3
"""Black-box LSP tests: build with mayc and exchange actual framed messages."""
import argparse
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class Client:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.messages = queue.Queue()
        self.notifications = []
        self.next_id = 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            while True:
                headers = {}
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        raise EOFError("server closed stdout")
                    if line == b"\r\n":
                        break
                    key, value = line.decode().strip().split(":", 1)
                    headers[key.lower()] = value.strip()
                body = self.process.stdout.read(int(headers["content-length"]))
                self.messages.put(json.loads(body))
        except Exception as error:
            self.messages.put(error)

    def raw(self, body, fragmented=False):
        packet = b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        if fragmented:
            for i in range(0, len(packet), 3):
                self.process.stdin.write(packet[i:i + 3])
                self.process.stdin.flush()
        else:
            self.process.stdin.write(packet)
            self.process.stdin.flush()

    def send(self, method, params=None, request=False, identifier=None, ascii=True):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if request:
            self.next_id += 1
            message["id"] = self.next_id if identifier is None else identifier
        self.raw(json.dumps(message, ensure_ascii=ascii).encode())
        return message.get("id")

    def receive(self):
        message = self.messages.get(timeout=30)
        if isinstance(message, Exception):
            raise message
        return message

    def request(self, method, params=None, identifier=None):
        if method == "initialize" and params is not None:
            params = {**params, "initializationOptions": {"strict": False, **params.get("initializationOptions", {})}}
        ident = self.send(method, params, True, identifier)
        while True:
            message = self.receive()
            if "id" not in message:
                self.notifications.append(message)
            else:
                assert message["id"] == ident, message
                return message

    def result(self, method, params=None):
        message = self.request(method, params)
        assert "error" not in message, message
        return message["result"]

    def diagnostics(self, uri):
        # A barrier request drains all preceding notifications.
        self.result("textDocument/diagnostic", {"textDocument": {"uri": uri}})
        matches = [m["params"] for m in self.notifications
                   if m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == uri]
        assert matches, (uri, self.notifications)
        return matches[-1]

    def stop(self):
        assert self.result("shutdown") is None
        self.send("exit")
        self.process.wait(timeout=10)
        assert self.process.returncode == 0
        errors = self.process.stderr.read().decode()
        assert not errors, errors


def run(binary, work):
    lib = work / "lib.may"
    lib.write_text('/// Add two integers.\npub fun add(a: Int, b: Int) -> Int { a + b }\nfun hidden() { 0 }\n')
    main = work / "main.may"
    text = 'import "lib" as math;\nlet amount = math.add(1, 2);\nfun local(amount) {\n    let nested = amount;\n    nested\n}\nprint(amount);\n'
    main.write_text(text)
    uri = main.as_uri()
    doc = {"textDocument": {"uri": uri}}
    def pos(line, character, **extra):
        return {**doc, "position": {"line": line, "character": character}, **extra}
    c = Client(binary)
    try:
        assert c.request("textDocument/hover", pos(0, 0))["error"]["code"] == -32002
        initialized = c.request("initialize", {"rootUri": work.as_uri(), "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}}, identifier=0)
        caps = initialized["result"]["capabilities"]
        assert caps["positionEncoding"] == "utf-16" and caps["textDocumentSync"]["change"] == 2
        c.send("initialized", {})
        assert c.request("initialize", {})["error"]["code"] == -32600
        c.raw(b'{"jsonrpc":"2.0", "id":99, "method":"broken",}', fragmented=True)
        assert c.receive()["error"]["code"] == -32700
        assert c.request("does/not/exist", {})["error"]["code"] == -32601
        c.send("textDocument/didOpen", {"textDocument": {"uri": uri, "text": text, "version": 1, "languageId": "maylang"}})
        assert c.diagnostics(uri)["diagnostics"] == [], c.diagnostics(uri)
        pull = c.result("textDocument/diagnostic", doc)
        assert pull["kind"] == "full" and pull["items"] == []
        print("PASS lifecycle, strict JSON and compiler diagnostics", flush=True)

        hover = c.result("textDocument/hover", pos(1, 19))
        assert "Add two integers." in hover["contents"]["value"]
        definition = c.result("textDocument/definition", pos(1, 19))
        assert definition["uri"] == lib.as_uri() and definition["range"]["start"] == {"line": 1, "character": 8}, definition
        declaration = c.result("textDocument/declaration", pos(1, 19))
        assert declaration == definition
        links = c.result("textDocument/documentLink", doc)
        assert links[0]["target"] == lib.as_uri()
        symbols = c.result("textDocument/documentSymbol", doc)
        assert {s["name"] for s in symbols} == {"amount", "local"}
        assert symbols[1]["children"][0]["name"] == "nested"
        workspace = c.result("workspace/symbol", {"query": "add"})
        assert any(s["location"]["uri"] == lib.as_uri() for s in workspace)
        print("PASS hover, navigation, document links and symbols", flush=True)

        references = c.result("textDocument/references", pos(1, 5, context={"includeDeclaration": True}))
        assert [r["range"]["start"]["line"] for r in references] == [1, 6], references
        local_refs = c.result("textDocument/references", pos(2, 12, context={"includeDeclaration": True}))
        assert [r["range"]["start"]["line"] for r in local_refs] == [2, 3], local_refs
        highlights = c.result("textDocument/documentHighlight", pos(1, 5))
        assert len(highlights) == 2
        prepared = c.result("textDocument/prepareRename", pos(1, 19))
        assert prepared["placeholder"] == "add"
        renamed = c.result("textDocument/rename", pos(1, 19, newName="plus"))
        assert set(renamed["changes"]) == {uri, lib.as_uri()}, renamed
        assert c.request("textDocument/rename", pos(1, 19, newName="fun"))["error"]["code"] == -32602
        assert c.request("textDocument/rename", pos(2, 12, newName="nested"))["error"]["code"] == -32602
        print("PASS lexical shadowing, references, highlights and cross-file rename", flush=True)

        completions = c.result("textDocument/completion", pos(1, 18))["items"]
        labels = {x["label"] for x in completions}
        assert "add" in labels and "hidden" not in labels and "print" not in labels, labels
        signature = c.result("textDocument/signatureHelp", pos(1, 26))
        assert signature["activeParameter"] == 1 and len(signature["signatures"][0]["parameters"]) == 2, signature
        folding = c.result("textDocument/foldingRange", doc)
        assert any(f["startLine"] == 2 and f["endLine"] == 5 for f in folding)
        selection = c.result("textDocument/selectionRange", {**doc, "positions": [{"line": 3, "character": 18}]})
        assert "parent" in selection[0]
        semantic = c.result("textDocument/semanticTokens/full", doc)["data"]
        assert semantic and len(semantic) % 5 == 0
        assert all(semantic[i] >= 0 for i in range(len(semantic)))
        ranged = c.result("textDocument/semanticTokens/range", {**doc, "range": {"start": {"line": 1, "character": 0}, "end": {"line": 2, "character": 0}}})
        assert ranged["data"]
        print("PASS completion, signature help, folding, selection and semantic tokens", flush=True)

        # Full sync, then an incremental edit after a non-BMP character.
        unicode_text = 'let face = "🦊"; let number = 3;\nprint(number);\n'
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": unicode_text}]}, ascii=False)
        assert c.diagnostics(uri)["diagnostics"] == []
        hints = c.result("textDocument/inlayHint", {**doc, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 0}}})
        assert any(h["label"] == ": Int" for h in hints), hints
        start = len(unicode_text.splitlines()[0].split("number")[0].encode("utf-16-le")) // 2
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 3}, "contentChanges": [
            {"range": {"start": {"line": 0, "character": start}, "end": {"line": 0, "character": start + 6}}, "text": "renamed"},
            {"range": {"start": {"line": 1, "character": 6}, "end": {"line": 1, "character": 12}}, "text": "renamed"}]})
        assert c.diagnostics(uri)["diagnostics"] == []
        definition = c.result("textDocument/definition", pos(1, 8))
        assert definition["range"]["start"] == {"line": 0, "character": start}, definition
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": "broken"}]})
        assert c.result("textDocument/hover", pos(1, 8)) is not None
        print("PASS UTF-8 framing, UTF-16 edits, sequential changes and stale versions", flush=True)

        invalid = 'let count: Int = "wrong";\n'
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 4}, "contentChanges": [{"text": invalid}]})
        diagnostics = c.diagnostics(uri)
        assert diagnostics["version"] == 4 and "expected Int" in diagnostics["diagnostics"][0]["message"], diagnostics
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 5}, "contentChanges": [{"text": 'fun broken( {\n'}]})
        assert c.diagnostics(uri)["diagnostics"]
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 6}, "contentChanges": [{"text": 'import "missing";\n'}]})
        assert "Cannot resolve import" in c.diagnostics(uri)["diagnostics"][0]["message"]
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 7}, "contentChanges": [{"text": text}]})
        assert c.diagnostics(uri)["diagnostics"] == []
        print("PASS syntax, type, missing import diagnostics and recovery", flush=True)

        ugly = 'fun test() {\nprint("{ untouched }");   \n// } comment\n}\n\n\n'
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 8}, "contentChanges": [{"text": ugly}]})
        edits = c.result("textDocument/formatting", {**doc, "options": {"tabSize": 2, "insertSpaces": True}})
        formatted = edits[0]["newText"]
        assert formatted == 'fun test() {\n  print("{ untouched }");\n  // } comment\n}\n', formatted
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 9}, "contentChanges": [{"text": formatted}]})
        assert c.result("textDocument/formatting", {**doc, "options": {"tabSize": 2, "insertSpaces": True}}) == []
        sorted_imports = 'import "z.may";\nimport "a.may";\nprint(1);\n'
        c.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 10}, "contentChanges": [{"text": sorted_imports}]})
        actions = c.result("textDocument/codeAction", {**doc, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 0}}, "context": {"diagnostics": [], "only": ["source.organizeImports"]}})
        assert actions[0]["edit"]["changes"][uri][0]["newText"].startswith('import "a.may";'), actions
        c.send("textDocument/didClose", doc)
        assert c.diagnostics(uri)["diagnostics"] == [], c.diagnostics(uri)
        assert c.result("textDocument/hover", pos(1, 19)) is not None  # disk restored
        print("PASS formatting, idempotence, organize imports and close", flush=True)
        run_language_features(c, work, lib)
        run_workspace_changes(c, work)
        run_protocol_edges(c, uri)
        c.stop()
        assert c.process.returncode == 0
    finally:
        if c.process.poll() is None:
            c.process.kill()
            c.process.wait()

    # Exit before shutdown is an unsuccessful exit, including before initialize.
    c = Client(binary)
    c.send("exit")
    c.process.wait(timeout=10)
    assert c.process.returncode == 1
    print("PASS exit status", flush=True)


def position(text, needle, occurrence=0, delta=0):
    offset = -1
    for _ in range(occurrence + 1):
        offset = text.index(needle, offset + 1)
    before = text[:offset + delta]
    return {"line": before.count("\n"), "character": len(before.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2}


def run_language_features(c, work, lib):
    path = work / "space 🦊.may"
    text = '''struct Point { x: Int, y: Int }
let point = Point(1, 2);
let [first, second] = [1, 2];
let {value: renamed, plain} = {value: 3, plain: 4};
let mapped = map([1, 2], |item| item + first);
let short = v => v + second;
let anonymous = fun(value) { value + renamed };
let message = "hello ${first} ${short(2)}";
for [left, right] in [[1, 2]] { print(left, right); }
fun props(p: Point) { p.x }
print(point.x, plain, mapped);
enum Choice { Yes(v), No }
let chosen = Yes(1);
let comp = [entry * 2 for entry in [1, 2] if entry > 0];
let matched = match(1) { n if n > 0 => n, _ => 0 };
fun generic<T>(values: Map<Str, Int>, more: List<T>) { values }
'''
    path.write_text(text)
    uri = path.as_uri()
    doc = {"textDocument": {"uri": uri}}
    def at(needle, occurrence=0, delta=0, **extra):
        return {**doc, "position": position(text, needle, occurrence, delta), **extra}
    c.send("textDocument/didOpen", {"textDocument": {"uri": uri, "text": text, "version": 1, "languageId": "maylang"}}, ascii=False)
    assert c.diagnostics(uri)["diagnostics"] == [], c.diagnostics(uri)
    refs = c.result("textDocument/references", at("first", context={"includeDeclaration": True}))
    assert len(refs) == 3, refs
    for name in ("item", "v =>", "value) {", "left", "renamed", "plain"):
        result = c.result("textDocument/references", at(name, context={"includeDeclaration": True}))
        assert len(result) == 2, (name, result)
    assert c.result("textDocument/definition", at("${first}", delta=3))["range"]["start"]["line"] == 2
    field = c.result("textDocument/definition", at("point.x", delta=6))
    assert field["range"]["start"] == {"line": 0, "character": 15}, field
    assert c.result("textDocument/definition", at("p.x", delta=2)) == field
    completions = c.result("textDocument/completion", at("point.x", delta=6))["items"]
    assert {i["label"] for i in completions} == {"x", "y"}, completions
    constructor = c.result("textDocument/definition", at("Yes(1)"))
    assert constructor["range"]["start"]["line"] == 11, constructor
    renamed = c.result("textDocument/rename", at("first", newName="initial"))
    assert len(renamed["changes"][uri]) == 3
    # Map keys retain their spelling when their binding is renamed.
    renamed = c.result("textDocument/rename", at("plain", newName="ordinary"))
    assert len(renamed["changes"][uri]) == 2, renamed
    for name in ("entry", "n if"):
        result = c.result("textDocument/references", at(name, context={"includeDeclaration": True}))
        assert len(result) == 3, (name, result)
    generic = c.result("textDocument/hover", at("generic"))
    assert "Map<Str, Int>" in generic["contents"]["value"]
    multiline = 'fun multiline() {\nlet text = "first  \n  second\nlast";\nprint(text);\n}\n'
    multiline_path = work / "multiline.may"
    multiline_path.write_text(multiline)
    multiline_doc = {"textDocument": {"uri": multiline_path.as_uri()}}
    formatted = c.result("textDocument/formatting", {**multiline_doc, "options": {"tabSize": 2, "insertSpaces": True}})[0]["newText"]
    assert '"first  \n  second\nlast"' in formatted, formatted
    print("PASS destructuring, lambdas, interpolations, struct fields, enums and encoded URIs", flush=True)

    other = work / "selective.may"
    selective = 'from "lib" import add;\nlet result = add(1, 2);\nfun shadow(math) { math.add(1, 2) }\nfun caller() { add(1, 2) + add(3, 4) }\n'
    other.write_text(selective)
    other_doc = {"textDocument": {"uri": other.as_uri()}}
    c.send("textDocument/didOpen", {"textDocument": {"uri": other.as_uri(), "text": selective, "version": 1, "languageId": "maylang"}})
    assert c.diagnostics(other.as_uri())["diagnostics"] == [], c.diagnostics(other.as_uri())
    renamed = c.result("textDocument/rename", {**other_doc, "position": {"line": 1, "character": 14}, "newName": "combine"})
    assert len(renamed["changes"][other.as_uri()]) == 4, renamed
    hierarchy = c.result("textDocument/prepareCallHierarchy", {**other_doc, "position": {"line": 1, "character": 14}})
    assert hierarchy[0]["name"] == "add"
    incoming = c.result("callHierarchy/incomingCalls", {"item": hierarchy[0]})
    assert len(incoming) == 1 and incoming[0]["from"]["name"] == "caller" and len(incoming[0]["fromRanges"]) == 2, incoming
    outgoing = c.result("callHierarchy/outgoingCalls", {"item": incoming[0]["from"]})
    assert len(outgoing) == 1 and outgoing[0]["to"]["name"] == "add" and len(outgoing[0]["fromRanges"]) == 2, outgoing
    assert c.result("textDocument/definition", {**other_doc, "position": {"line": 2, "character": 24}}) is None
    print("PASS pull diagnostics, call hierarchy and alias shadowing", flush=True)
    lib_text = lib.read_text().replace("Add two integers.", "Fresh documentation.")
    lib.write_text(lib_text)
    c.send("workspace/didChangeWatchedFiles", {"changes": [{"uri": lib.as_uri(), "type": 2}]})
    hover = c.result("textDocument/hover", {**other_doc, "position": {"line": 1, "character": 14}})
    assert "Fresh documentation." in hover["contents"]["value"], hover
    c.send("textDocument/didOpen", {"textDocument": {"uri": lib.as_uri(), "text": lib_text.replace("a + b", '"bad"'), "version": 1, "languageId": "maylang"}})
    assert "expected Int" in c.diagnostics(lib.as_uri())["diagnostics"][0]["message"]
    c.send("textDocument/didClose", {"textDocument": {"uri": lib.as_uri()}})
    assert c.diagnostics(other.as_uri())["diagnostics"] == [], c.diagnostics(other.as_uri())
    c.send("textDocument/didClose", other_doc)
    c.send("textDocument/didClose", doc)
    print("PASS selective imports, file watching and unsaved dependencies", flush=True)


def run_protocol_edges(c, uri):
    for body in (b'[]', b'{"jsonrpc":"1.0","id":1,"method":"test"}'):
        c.raw(body)
        while True:
            reply = c.receive()
            if "id" in reply:
                break
            c.notifications.append(reply)
        assert reply["error"]["code"] == -32600, reply
    for body in (b'{"x":01}', b'{"x":"\\uD800"}', b'{"x":"\\q"}',
                 b'{"x":"\xff"}', b'{"x":1.}', b'{"x":[1,]}', b'{"x":true} trailing'):
        c.raw(body)
        assert c.receive()["error"]["code"] == -32700, body
    assert c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": {"line": -1, "character": 0}})["error"]["code"] == -32602
    c.send("$/cancelRequest", {"id": 999})
    assert c.request("workspace/symbol", {"query": "__empty__"}, identifier="string-id")["result"] == []
    # This request crosses the 64 KiB transport read buffer.
    large = json.dumps({"jsonrpc": "2.0", "id": "large", "method": "workspace/symbol", "params": {"query": "x" * 70000}}).encode()
    c.raw(large)
    reply = c.receive()
    assert reply["id"] == "large" and reply["result"] == [], reply
    print("PASS malformed requests, Unicode errors, cancellation and buffered transport", flush=True)


def run_workspace_changes(c, work):
    extra = work / "other.root"
    extra.mkdir()
    source = extra / "workspace.may"
    source.write_text('fun workspace_added() { 1 }\n')
    c.send("workspace/didChangeWorkspaceFolders", {"event": {"added": [{"uri": extra.as_uri(), "name": "extra"}], "removed": [{"uri": work.as_uri(), "name": "main"}]}})
    assert len(c.result("workspace/symbol", {"query": "workspace_added"})) == 1
    assert c.result("workspace/symbol", {"query": "caller"}) == []
    c.send("workspace/didChangeWorkspaceFolders", {"event": {"added": [{"uri": work.as_uri(), "name": "main"}], "removed": [{"uri": extra.as_uri(), "name": "extra"}]}})
    assert len(c.result("workspace/symbol", {"query": "caller"})) == 1
    source.unlink()
    c.send("workspace/didChangeWatchedFiles", {"changes": [{"uri": source.as_uri(), "type": 3}]})
    assert c.result("workspace/symbol", {"query": "workspace_added"}) == []
    created = extra / "created.may"
    created.write_text('fun watched_create() { 1 }\n')
    c.send("workspace/didChangeWatchedFiles", {"changes": [{"uri": created.as_uri(), "type": 1}]})
    assert len(c.result("workspace/symbol", {"query": "watched_create"})) == 1
    print("PASS workspace folders, dotted directories and file creation/deletion", flush=True)


def run_responsiveness(binary, work):
    editor_root = work / "editor-session"
    editor_root.mkdir()
    # Document highlighting must never walk unrelated workspace files. A FIFO
    # makes an accidental workspace scan block deterministically.
    os.mkfifo(editor_root / "unrelated.may")
    source = ROOT / "toolchain/maylsp/main.may"
    text = source.read_text()
    doc = {"textDocument": {"uri": source.as_uri()}}
    at = {**doc, "position": position(text, "ls_cwd")}
    client = Client(binary)
    try:
        client.result("initialize", {"rootUri": editor_root.as_uri(), "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}})
        opened = time.monotonic()
        client.send("textDocument/didOpen", {"textDocument": {"uri": source.as_uri(), "languageId": "maylang", "version": 1, "text": text}})
        # Queue the requests VS Code issues when opening a document, followed
        # by hover. The old semantic-token implementation exceeded 30 seconds.
        methods = [("textDocument/documentSymbol", doc),
                   ("textDocument/diagnostic", doc),
                   ("textDocument/semanticTokens/full", doc),
                   ("textDocument/documentHighlight", at),
                   ("textDocument/hover", at)]
        pending = {client.send(method, params, request=True): method for method, params in methods}
        hover_elapsed = None
        answers = {}
        while pending:
            message = client.receive()
            if "id" not in message:
                client.notifications.append(message)
                continue
            method = pending.pop(message["id"])
            assert "error" not in message, message
            answers[method] = message["result"]
            if method == "textDocument/hover":
                hover_elapsed = time.monotonic() - opened
                assert "textDocument/diagnostic" in pending.values(), "Hover waited for compiler diagnostics"
        assert hover_elapsed < 3, f"Editor requests starved hover for {hover_elapsed:.2f}s"
        assert "ls_cwd" in answers["textDocument/hover"]["contents"]["value"]
        assert answers["textDocument/documentHighlight"]
        assert answers["textDocument/diagnostic"]["items"] == []
        # Duplicate pull requests reuse the check performed for didOpen.
        start = time.monotonic()
        for _ in range(3):
            assert client.result("textDocument/diagnostic", doc)["items"] == []
        assert time.monotonic() - start < 2, "Unchanged diagnostics reran the compiler"
        client.stop()
        print(f"PASS VS Code request queue, local highlighting and cached diagnostics ({hover_elapsed:.3f}s)", flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait()


def run_documentation(binary, work):
    subprocess.run(["python3", str(ROOT / "toolchain/maylsp/docs/generate.py"), "--check"], check=True)
    catalog = json.loads((ROOT / "toolchain/maylsp/docs/reference.json").read_text())
    entries = {name: entry for group in catalog.values() for name, entry in group.items()}
    import re
    for filename, constant in [("src/text.may", "LS_KEYWORDS"), ("src/index.may", "LS_BUILTINS")]:
        source = (ROOT / "toolchain/maylsp" / filename).read_text()
        names = json.loads(re.search(rf"let {constant}(?:\s*:\s*Any)? = (\[.*?\]);", source).group(1))
        assert set(names) <= entries.keys(), set(names) - entries.keys()
    path = work / "documentation.may"
    text = ('let items = [1, 2];\nprint(len(items));\n'
            'let transformed = map(items, x => x + 1);\n'
            'let part = slice(items, 0, 1);\nlet size: Int = 2;\n'
            'let fallback = nil ?? 7;\n')
    path.write_text(text)
    doc = {"textDocument": {"uri": path.as_uri()}}
    client = Client(binary)
    try:
        client.result("initialize", {"rootUri": work.as_uri(), "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}})
        client.send("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(), "text": text, "version": 1, "languageId": "maylang"}})
        for name, phrase in [("print", "standard output"), ("len", "Unicode characters"),
                             ("map", "input list is preserved"), ("slice", "stop index is exclusive"),
                             ("let", "immutable binding"), ("Int", "61-bit"), ("??", "false")]:
            hover = client.result("textDocument/hover", {**doc, "position": position(text, name)})
            prose = hover["contents"]["value"]
            assert phrase in prose and "**Example**" in prose, (name, prose)
        signature = client.result("textDocument/signatureHelp", {**doc, "position": position(text, "map(items,", delta=len("map(items,"))})
        assert signature["activeParameter"] == 1
        params = signature["signatures"][0]["parameters"]
        assert params[1]["label"] == "f" and "function" in params[1]["documentation"]["value"]
        signature = client.result("textDocument/signatureHelp", {**doc, "position": position(text, "print(", delta=6)})
        assert "print(" in signature["signatures"][0]["label"]
        assert "standard output" in signature["signatures"][0]["documentation"]["value"]
        items = client.result("textDocument/completion", {**doc, "position": {"line": 6, "character": 0}})["items"]
        for name in ("len", "map", "slice", "let"):
            item = next(item for item in items if item["label"] == name)
            assert "**Example**" in item["documentation"]["value"], item
        text = '/// Local transformation, with its own contract.\nfun map(value) { value }\nmap(1);\n'
        client.send("textDocument/didChange", {**doc, "textDocument": {"uri": path.as_uri(), "version": 2}, "contentChanges": [{"text": text}]})
        prose = client.result("textDocument/hover", {**doc, "position": {"line": 2, "character": 1}})["contents"]["value"]
        assert "Local transformation" in prose and "input list is preserved" not in prose
        assert client.result("textDocument/diagnostic", doc)["items"] == []
        client.stop()
        print("PASS generated documentation, keyword/type/operator hover, builtin signatures and local overrides", flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait()


def run_inlay_types(binary, work):
    folder = work / "inlay-types"
    folder.mkdir()
    lib = folder / "model.may"
    lib_text = 'pub fun number() -> Int { 7 }\npub struct Record { value: Int }\n'
    lib.write_text(lib_text)
    path = folder / "main.may"
    text = '''import "model" as model;
fun title() -> Str { "hello" }
fun unknown() { true }
fun identity<T>(value: T) -> T { value }
fun boxed<T>(value: T) -> List<T> { [value] }
struct Point { x: Int, y: Int }
enum Choice { Yes(value), No }
let text = title();
let count = len([1, 2]);
let opaque = unknown();
let generic = identity(1);
let genericList = boxed(1);
let point = Point(1, 2);
let chosen = Yes(1);
let imported = model.number();
let remote = model.Record(3);
let copied = imported;
let forward = later();
let explicit: Int = 3;
let combined = model.number() + 1;
let cycleA = cycleB;
let cycleB = cycleA;
fun later() -> Int { 5 }
fun shadow() {
    fun len(value) { value }
    let shadowed = len([1]);
}
fun shadowConstructor() {
    fun Point(x, y) -> Str { "label" }
    let label = Point(1, 2);
}
point.x;
remote.value;
'''
    path.write_text(text)
    doc = {"textDocument": {"uri": path.as_uri()}}
    query = {**doc, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 100, "character": 0}}}
    client = Client(binary)
    def hints_by_name():
        hints = client.result("textDocument/inlayHint", query)
        result = {}
        for hint in hints:
            prefix = text.splitlines()[hint["position"]["line"]][:hint["position"]["character"]]
            result[prefix.split()[-1]] = hint["label"]
        return result
    try:
        client.result("initialize", {"rootUri": folder.as_uri(), "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}})
        client.send("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(), "text": text, "version": 1, "languageId": "maylang"}})
        expected = {"text": ": Str", "count": ": Int", "point": ": Point", "chosen": ": Choice",
                    "imported": ": Int", "remote": ": model.Record", "copied": ": Int",
                    "forward": ": Int", "label": ": Str"}
        assert hints_by_name() == expected, hints_by_name()
        # Cached inference must follow changes in a dirty imported buffer.
        client.send("textDocument/didOpen", {"textDocument": {"uri": lib.as_uri(), "version": 1, "languageId": "maylang",
                    "text": lib_text.replace('-> Int { 7 }', '-> Str { "seven" }')}})
        expected.update(imported=": Str", copied=": Str")
        assert hints_by_name() == expected, hints_by_name()
        # Constructor inference still supplies struct member navigation.
        target = client.result("textDocument/definition", {**doc, "position": position(text, "point.x", delta=6)})
        assert target["uri"] == path.as_uri() and target["range"]["start"] == position(text, "x: Int")
        target = client.result("textDocument/definition", {**doc, "position": position(text, "remote.value", delta=7)})
        assert target["uri"] == lib.as_uri() and target["range"]["start"] == position(lib_text, "value: Int")
        client.stop()
        print("PASS return-type hints, constructors, builtin results, generics, aliases, shadowing and dirty imports", flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait()


def run_background_checks(binary, work):
    path = work / "rapid-edits.may"
    text = "fun large() {\n" + "".join(f"let value{i} = {i};\n" for i in range(4000)) + "missing;\n}\n"
    path.write_text(text)
    doc = {"textDocument": {"uri": path.as_uri()}}
    client = Client(binary)
    try:
        client.result("initialize", {"rootUri": work.as_uri(), "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}})
        client.send("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(), "text": text, "version": 1, "languageId": "maylang"}})
        pending = client.send("textDocument/diagnostic", doc, request=True)
        # Ensure the worker is underway before cancelling its pull request.
        client.result("textDocument/hover", {**doc, "position": {"line": 0, "character": 5}})
        client.send("$/cancelRequest", {"id": pending})
        cancelled = client.receive()
        assert cancelled["id"] == pending and cancelled["error"]["code"] == -32800, cancelled
        for version in range(2, 15):
            client.send("textDocument/didChange", {"textDocument": {"uri": path.as_uri(), "version": version}, "contentChanges": [{"text": f"let current = {version};\n"}]})
        result = client.result("textDocument/diagnostic", doc)
        assert result["items"] == []
        published = [m["params"] for m in client.notifications if m.get("method") == "textDocument/publishDiagnostics"]
        assert published and all(p["version"] == 14 and p["diagnostics"] == [] for p in published), published
        # Push diagnostics must arrive even while the client sends no requests.
        client.send("textDocument/didChange", {"textDocument": {"uri": path.as_uri(), "version": 15}, "contentChanges": [{"text": "missing;\n"}]})
        pushed = client.receive()
        assert pushed["method"] == "textDocument/publishDiagnostics" and pushed["params"]["version"] == 15
        assert "unknown name" in pushed["params"]["diagnostics"][0]["message"]
        client.send("textDocument/didChange", {"textDocument": {"uri": path.as_uri(), "version": 16}, "contentChanges": [{"text": text}]})
        client.send("textDocument/diagnostic", doc, request=True)
        # Shutdown must reap active workers without waiting for their checks.
        client.send("shutdown", request=True)
        while True:
            reply = client.receive()
            if reply.get("id") == client.next_id:
                assert reply["result"] is None
                break
        client.send("exit")
        client.process.wait(timeout=5)
        assert client.process.returncode == 0 and not client.process.stderr.read()
        print("PASS background checking, cancellation, edit coalescing, stale result rejection and idle publication", flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait()


def run_strict_checks(binary, work):
    path = work / "strict-default.may"
    uri = path.as_uri()
    doc = {"textDocument": {"uri": uri}}
    client = Client(binary)
    try:
        # Bypass the legacy fixture helper to test the actual default.
        ident = client.send("initialize", {"rootUri": work.as_uri()}, request=True)
        assert client.receive()["id"] == ident
        text = "let value = 1;\n"
        client.send("textDocument/didOpen", {"textDocument": {"uri": uri, "text": text, "version": 1, "languageId": "maylang"}})
        result = client.result("textDocument/diagnostic", doc)
        assert result["items"] == [], result
        text = "fun add(a: Int, b: Int) -> Int { return a + b; }\nlet value: Int = add(2, 3);\n"
        client.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": text}]})
        assert client.result("textDocument/diagnostic", doc)["items"] == []
        hover = client.result("textDocument/hover", {**doc, "position": {"line": 0, "character": 5}})
        assert "-> Int" in hover["contents"]["value"], hover
        client.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 3}, "contentChanges": [{"text": 'let value: Int = "wrong";\n'}]})
        result = client.result("textDocument/diagnostic", doc)
        assert any("expected Int, found Str" in item["message"] for item in result["items"]), result
        client.send("workspace/didChangeConfiguration", {"settings": {"maylang": {"strict": False}}})
        client.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 4}, "contentChanges": [{"text": "let value = 1;\n"}]})
        assert client.result("textDocument/diagnostic", doc)["items"] == []
        client.send("workspace/didChangeConfiguration", {"settings": {"maylang": {"strict": True}}})
        result = client.result("textDocument/diagnostic", doc)
        assert result["items"] == [], result
        multi = 'fun a() -> Int { return "bad"; }\nfun b() -> Bool { return 7; }\n'
        client.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 5}, "contentChanges": [{"text": multi}]})
        errors = client.result("textDocument/diagnostic", doc)["items"]
        assert len(errors) == 2 and {item["range"]["start"]["line"] for item in errors} == {0, 1}, errors
        assert all(item["code"] == "E_TYPE" for item in errors), errors
        client.stop()
        print("PASS strict defaults, multiple diagnostics, hover and configuration updates", flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--compiler", type=Path, default=ROOT / "toolchain/mayc/mayc_new")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="maylsp-tests-") as directory:
        work = Path(directory)
        binary = args.binary.resolve() if args.binary else work / "maylsp"
        if args.binary is None:
            subprocess.run([str(args.compiler), str(ROOT / "toolchain/maylsp/main.may"), "-o", str(binary)], cwd=ROOT, check=True, timeout=120)
        run_strict_checks(binary, work)
        run(binary, work)
        run_documentation(binary, work)
        run_inlay_types(binary, work)
        run_background_checks(binary, work)
        run_responsiveness(binary, work)


if __name__ == "__main__":
    main()
