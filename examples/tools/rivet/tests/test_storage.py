#!/usr/bin/env python3
"""Independent binary-format oracle and process-level storage regressions."""
import concurrent.futures
import fcntl
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

BINARY = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path("rivet").resolve()
HEADER = b"RIVET01\n" + struct.pack("<II", 1, 0)


def frame(tx, kind, key=b"", value=b""):
    body = struct.pack("<4s5I", b"RVF1", 28 + len(key) + len(value), tx, kind, len(key), len(value)) + key + value
    return body + struct.pack("<I", zlib.adler32(body))


def decode(blob):
    """Check complete logs without using Rivet's decoder."""
    assert blob[:16] == HEADER
    offset, tx, committed, pending = 16, 0, {}, []
    frames = []
    while offset < len(blob):
        magic, size, tid, kind, klen, vlen = struct.unpack_from("<4s5I", blob, offset)
        assert magic == b"RVF1" and size == 28 + klen + vlen
        assert offset + size <= len(blob)
        body = blob[offset:offset + size - 4]
        assert zlib.adler32(body) == struct.unpack_from("<I", blob, offset + size - 4)[0]
        key = blob[offset + 24:offset + 24 + klen]
        value = blob[offset + 24 + klen:offset + size - 4]
        if kind == 1:
            assert not pending and tid == tx + 1
            pending = [(kind, key, value)]
        elif kind == 4:
            assert pending and tid == tx + 1
            for op, k, v in pending[1:]:
                if op == 2:
                    committed[k] = v
                else:
                    committed.pop(k, None)
            pending = []
            tx = tid
        else:
            assert pending and tid == tx + 1
            pending.append((kind, key, value))
        frames.append((offset, size, tid, kind, key, value))
        offset += size
    assert not pending
    return committed, frames


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rivet-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "data.rvt"
        self.run_command("init")

    def run_command(self, command, *args, ok=True, db=None):
        result = subprocess.run([str(BINARY), command, str(db or self.db), *map(str, args)],
                                capture_output=True, timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        else:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(b"rivet:", result.stderr)
        return result

    def batch(self, operations):
        path = self.root / "batch.json"
        path.write_text(json.dumps(operations, ensure_ascii=False))
        return path

    def test_format_oracle_overwrite_delete_and_unicode(self):
        self.run_command("put", "greeting", "hello")
        self.run_command("put", "greeting", "labas")
        self.run_command("put", "miestas/žemė", "Ąžuolas 🌳")
        self.run_command("put", "empty", "")
        self.assertEqual(self.run_command("get", "greeting").stdout, b"labas")
        self.assertEqual(self.run_command("get", "miestas/žemė").stdout, "Ąžuolas 🌳".encode())
        self.assertEqual(self.run_command("get", "empty").stdout, b"")
        self.run_command("delete", "greeting")
        self.run_command("get", "greeting", ok=False)
        values, frames = decode(self.db.read_bytes())
        self.assertEqual(values, {"miestas/žemė".encode(): "Ąžuolas 🌳".encode(), b"empty": b""})
        self.assertEqual(len(frames), 15)
        self.assertIn(b"COMMIT", self.run_command("inspect").stdout)
        self.assertIn(b"live payload", self.run_command("stats").stdout)

    def test_all_bytes_and_exact_maximum_value(self):
        raw = bytes(range(256)) * 256
        source = self.root / "binary.bin"
        source.write_bytes(raw)
        self.run_command("put-file", "binary", source)
        self.assertEqual(self.run_command("get", "binary").stdout, raw)
        destination = self.root / "restored.bin"
        self.run_command("get", "binary", "--out", destination)
        self.assertEqual(destination.read_bytes(), raw)
        before = self.db.read_bytes()
        self.run_command("get", "binary", "--out", self.db, ok=False)
        self.assertEqual(self.db.read_bytes(), before)
        self.run_command("get", "binary", "--out", destination, ok=False)
        self.assertEqual(destination.read_bytes(), raw)
        self.run_command("compact")
        self.assertEqual(self.run_command("get", "binary").stdout, raw)
        self.assertEqual(decode(self.db.read_bytes())[0], {b"binary": raw})

    def test_atomic_batch_and_rejected_batch_do_not_touch_disk(self):
        self.run_command("put", "first", "old")
        self.run_command("batch", self.batch([
            {"op": "put", "key": "first", "value": "new"},
            {"op": "put", "key": "second", "value": "2"},
            {"op": "delete", "key": "first"},
            {"op": "put", "key": "first", "value": "last"},
        ]))
        values, frames = decode(self.db.read_bytes())
        self.assertEqual(values, {b"first": b"last", b"second": b"2"})
        self.assertEqual([f[2] for f in frames[-6:]], [2] * 6)
        before = self.db.read_bytes()
        for operations in [[], [{"op": "put", "key": "x", "value": "okay"}, {"op": "oops", "key": "y"}],
                           [{"op": "put", "key": "x", "value": 42}], [{"op": "delete", "key": ""}],
                           [{"op": "put", "key": "x", "value": "a" * 65537}]]:
            self.run_command("batch", self.batch(operations), ok=False)
            self.assertEqual(self.db.read_bytes(), before)

    def test_every_byte_truncation_preserves_atomicity(self):
        self.run_command("put", "stable", "before")
        base = self.db.read_bytes()
        suffix = frame(2, 1) + frame(2, 2, b"stable", b"after") + frame(2, 2, b"other", b"value") + frame(2, 4)
        # Exhaust all cut points, including cuts inside lengths and checksums.
        for cut in range(len(suffix)):
            with self.subTest(cut=cut):
                self.db.write_bytes(base + suffix[:cut])
                self.assertEqual(self.run_command("get", "stable").stdout, b"before")
                self.run_command("get", "other", ok=False)
                if cut:
                    self.run_command("put", "later", "write", ok=False)
                self.run_command("recover")
                self.assertEqual(self.db.read_bytes(), base)
        self.db.write_bytes(base + suffix)
        self.assertEqual(self.run_command("get", "stable").stdout, b"after")
        self.assertEqual(self.run_command("get", "other").stdout, b"value")
        self.run_command("recover")
        self.assertEqual(self.db.read_bytes(), base + suffix)

    def test_complete_corruption_is_never_repaired_silently(self):
        self.run_command("put", "key", "value")
        clean = self.db.read_bytes()
        for position in [0, 16, 20, 28, 60, 72, len(clean) - 1]:
            damaged = bytearray(clean)
            damaged[position] ^= 1
            self.db.write_bytes(damaged)
            self.run_command("get", "key", ok=False)
            self.run_command("recover", ok=False)
            self.run_command("compact", ok=False)
            self.assertEqual(self.db.read_bytes(), damaged)
        # Correct checksums do not excuse impossible transaction structure.
        for suffix in [frame(2, 4), frame(3, 1), frame(2, 1) + frame(2, 1),
                       frame(2, 1) + frame(3, 2, b"bad", b"value")]:
            self.db.write_bytes(clean + suffix)
            self.run_command("recover", ok=False)
            self.assertEqual(self.db.read_bytes(), clean + suffix)

    def test_compaction_preserves_values_and_lock_identity(self):
        for i in range(20):
            self.run_command("put", "retained", "version-" + str(i))
        self.run_command("put", "discarded", "gone")
        self.run_command("delete", "discarded")
        before, _ = decode(self.db.read_bytes())
        old_size = self.db.stat().st_size
        lock = Path(str(self.db) + ".lock")
        inode = lock.stat().st_ino
        self.run_command("compact")
        self.assertLess(self.db.stat().st_size, old_size)
        self.assertEqual(decode(self.db.read_bytes())[0], before)
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(list(self.root.glob("*.compact.*")), [])
        self.run_command("put", "next", "after compaction")
        self.assertEqual(self.run_command("get", "next").stdout, b"after compaction")

    def test_concurrent_writers_and_external_lock(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(self.run_command, "put", "worker/" + str(i), str(i)) for i in range(24)]
            for job in jobs:
                job.result()
        values, frames = decode(self.db.read_bytes())
        self.assertEqual(values, {("worker/" + str(i)).encode(): str(i).encode() for i in range(24)})
        self.assertEqual(len(frames), 72)
        with Path(str(self.db) + ".lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            child = subprocess.Popen([str(BINARY), "put", str(self.db), "blocked", "until release"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.communicate(timeout=0.15)
                fcntl.flock(lock, fcntl.LOCK_UN)
                out, err = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, err)
            finally:
                if child.poll() is None:
                    child.kill(); child.communicate()

    def test_randomized_workload_matches_reference(self):
        rng = random.Random(42)
        expected = {}
        for batch in range(12):
            operations = []
            for _ in range(20):
                key = "key/" + str(rng.randrange(30))
                if rng.randrange(4) == 0:
                    operations.append({"op": "delete", "key": key})
                    expected.pop(key.encode(), None)
                else:
                    value = "value/" + str(rng.randrange(100000))
                    operations.append({"op": "put", "key": key, "value": value})
                    expected[key.encode()] = value.encode()
            self.run_command("batch", self.batch(operations))
            self.assertEqual(decode(self.db.read_bytes())[0], expected)
            if batch % 3 == 2:
                self.run_command("compact")
                self.assertEqual(decode(self.db.read_bytes())[0], expected)

    def test_compaction_and_writers_share_a_stable_lock(self):
        self.run_command("put", "base", "preserved")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            jobs = []
            for i in range(12):
                jobs.append(pool.submit(self.run_command, "put", "mixed/" + str(i), str(i)))
                if i % 3 == 0:
                    jobs.append(pool.submit(self.run_command, "compact"))
            for job in jobs:
                job.result()
        expected = {b"base": b"preserved", **{("mixed/" + str(i)).encode(): str(i).encode() for i in range(12)}}
        self.assertEqual(decode(self.db.read_bytes())[0], expected)

    def test_reports_escape_control_characters_and_filter_prefix(self):
        self.run_command("put", "service/z", "last")
        self.run_command("put", "service/a", "first")
        self.run_command("put", "other/\n\x1b", "control key")
        listing = self.run_command("list", "service/").stdout
        self.assertLess(listing.index(b"service/a"), listing.index(b"service/z"))
        self.assertNotIn(b"other/", listing)
        inspected = self.run_command("inspect").stdout
        self.assertIn(b"other/\\x0a\\x1b", inspected)
        self.assertNotIn(b"\x1b", inspected)

    def test_bounds_and_creation_protection(self):
        before = self.db.read_bytes()
        self.run_command("init", ok=False)
        self.run_command("put", "", "x", ok=False)
        self.run_command("put", "k" * 1025, "x", ok=False)
        large = self.root / "large.bin"
        large.write_bytes(b"a" * 65537)
        self.run_command("put-file", "large", large, ok=False)
        self.assertEqual(self.db.read_bytes(), before)
        alias = self.root / "alias.rvt"
        alias.symlink_to(self.db)
        self.run_command("put", "unsafe", "x", db=alias, ok=False)
        self.assertEqual(self.db.read_bytes(), before)
        self.run_command("compact")
        self.assertEqual(self.db.read_bytes(), HEADER)

    def test_compaction_splits_large_live_payload_into_transactions(self):
        source = self.root / "value.bin"
        raw = bytes(range(256)) * 256
        source.write_bytes(raw)
        for i in range(17):
            self.run_command("put-file", "large/" + str(i), source)
        self.run_command("compact")
        values, frames = decode(self.db.read_bytes())
        self.assertEqual(len(values), 17)
        self.assertTrue(all(v == raw for v in values.values()))
        self.assertEqual(sum(f[3] == 4 for f in frames), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
