#!/usr/bin/env python3
"""Measure a cold VS Code request queue, then cached tokens and formatting."""
import argparse
import tempfile
import time
from pathlib import Path

from test_lsp import Client, ROOT, position


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "toolchain/maylsp/build/maylsp")
    parser.add_argument("--source", type=Path, default=ROOT / "toolchain/maylsp/main.may")
    args = parser.parse_args()
    source = args.source.resolve()
    text = source.read_text()
    doc = {"textDocument": {"uri": source.as_uri()}}
    first_name = next((line.split("fun ", 1)[1].split("(", 1)[0]
                       for line in text.splitlines() if line.startswith("fun ")), None)
    at = {**doc, "position": position(text, first_name) if first_name else {"line": 0, "character": 0}}
    with tempfile.TemporaryDirectory(prefix="maylsp-benchmark-") as directory:
        client = Client(args.binary.resolve())
        try:
            client.result("initialize", {"rootUri": Path(directory).as_uri(),
                                         "initializationOptions": {"stdlibPath": str(ROOT / "stdlib")}})
            start = time.monotonic()
            client.send("textDocument/didOpen", {"textDocument": {
                "uri": source.as_uri(), "languageId": "maylang", "version": 1, "text": text}})
            methods = [("textDocument/documentSymbol", doc), ("textDocument/diagnostic", doc),
                       ("textDocument/semanticTokens/full", doc), ("textDocument/documentHighlight", at),
                       ("textDocument/hover", at)]
            pending = {client.send(method, params, request=True): method for method, params in methods}
            while pending:
                reply = client.receive()
                if "id" not in reply:
                    continue
                assert "error" not in reply, reply
                print(f"{pending.pop(reply['id'])}: {time.monotonic() - start:.3f}s since open", flush=True)
            for method, params in [("textDocument/semanticTokens/full", doc),
                                   ("textDocument/formatting", {**doc, "options": {"tabSize": 4, "insertSpaces": True}})]:
                start = time.monotonic()
                client.result(method, params)
                print(f"warm {method}: {time.monotonic() - start:.3f}s", flush=True)
            client.stop()
        finally:
            if client.process.poll() is None:
                client.process.kill()
                client.process.wait()


if __name__ == "__main__":
    main()
