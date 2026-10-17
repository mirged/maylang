#!/usr/bin/env python3
"""Drive the native database through a repeatable crash/recovery demonstration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="rivet-demo-") as directory:
    root = Path(directory)
    database = root / "demo.rvt"
    def run(*args, expect=0):
        result = subprocess.run([str(binary), args[0], str(database), *map(str, args[1:])], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        if result.returncode != expect:
            raise SystemExit(result.returncode or 1)
    print("RIVET / configuration store and crash laboratory\n")
    run("init")
    batch = root / "batch.json"
    batch.write_text(json.dumps([
        {"op": "put", "key": "service/host", "value": "localhost"},
        {"op": "put", "key": "service/port", "value": "8080"},
        {"op": "put", "key": "feature/replay", "value": "enabled"},
    ]))
    run("batch", batch)
    run("put", "service/port", "9090")
    run("delete", "feature/replay")
    print("\nByte-level log before a simulated torn write:")
    run("inspect")
    committed = database.read_bytes()
    run("put", "service/port", "9999")
    # Remove seven bytes from the final COMMIT; the whole transaction vanishes.
    with database.open("r+b") as stream:
        stream.truncate(database.stat().st_size - 7)
    print("\nAfter a torn COMMIT, the previous port remains visible:")
    run("get", "service/port")
    print("\nWriting is blocked until recovery:")
    run("put", "service/port", "1111", expect=2)
    run("recover")
    assert database.read_bytes() == committed
    print("\nCompaction removes overwritten values and tombstones:")
    run("compact")
    run("inspect")
    print("\nDemo complete. The temporary database is removed automatically.")
