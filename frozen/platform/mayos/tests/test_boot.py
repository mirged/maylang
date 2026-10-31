#!/usr/bin/env python3
"""Boot the actual raw kernel in QEMU and exercise both serial and PS/2 input."""
import argparse
import json
import os
from pathlib import Path
import re
import select
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import zlib

parser = argparse.ArgumentParser()
parser.add_argument("--qemu", default="qemu-system-x86_64")
parser.add_argument("--iso", type=Path, required=True)
options, rest = parser.parse_known_args()
ISO = options.iso.resolve()


class Guest:
    def __init__(self, ram="64M", disk=None, attach=True, fail_write=False):
        self.temp = tempfile.TemporaryDirectory(prefix="mayos-qemu-")
        self.qmp_path = Path(self.temp.name) / "qmp.sock"
        self.disk = Path(disk) if disk else Path(self.temp.name) / "disk.img"
        if attach and not self.disk.exists():
            with self.disk.open("wb") as image:
                image.truncate(4 * 1024 * 1024)
        disk_path = str(self.disk)
        if fail_write:
            config = Path(self.temp.name) / "blkdebug.conf"
            config.write_text('[inject-error]\nevent = "write_aio"\nerrno = "5"\nonce = "on"\nimmediately = "on"\n')
            disk_path = "blkdebug:" + str(config) + ":" + disk_path
        drive = ["-drive", "file=" + disk_path + ",format=raw,if=ide,index=0,werror=report"] if attach else []
        self.process = subprocess.Popen([
            options.qemu, "-machine", "pc,accel=tcg", "-m", ram,
            "-cdrom", str(ISO), "-boot", "d", "-display", "none",
            "-serial", "stdio", "-monitor", "none", "-no-reboot",
            "-qmp", "unix:" + str(self.qmp_path) + ",server=on,wait=off",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
            *drive,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.buffer = b""
        self.transcript = b""
        self.qmp_socket = None
        self.qmp_reader = None

    def until(self, token, timeout=10):
        deadline = time.monotonic() + timeout
        while token not in self.buffer:
            if time.monotonic() >= deadline:
                raise AssertionError("QEMU timeout waiting for " + repr(token) + "\n" + self.transcript.decode(errors="replace"))
            ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
            if ready:
                part = os.read(self.process.stdout.fileno(), 65536)
                if not part:
                    error = self.process.stderr.read().decode(errors="replace")
                    raise AssertionError("QEMU exited before " + repr(token) + ": " + str(self.process.poll()) + "\n" + error + "\n" + self.transcript.decode(errors="replace"))
                self.buffer += part
                self.transcript += part
        stop = self.buffer.index(token) + len(token)
        response, self.buffer = self.buffer[:stop], self.buffer[stop:]
        return response.decode("ascii", errors="replace")

    def command(self, command):
        self.process.stdin.write(command.encode() + b"\n")
        self.process.stdin.flush()
        return self.until(b"mayos> ")

    def connect_qmp(self):
        if self.qmp_socket:
            return
        self.qmp_socket = socket.socket(socket.AF_UNIX)
        self.qmp_socket.settimeout(5)
        self.qmp_socket.connect(str(self.qmp_path))
        self.qmp_reader = self.qmp_socket.makefile("rb")
        json.loads(self.qmp_reader.readline())
        self.qmp("qmp_capabilities")

    def qmp(self, command, arguments=None):
        payload = {"execute": command}
        if arguments is not None:
            payload["arguments"] = arguments
        self.qmp_socket.sendall(json.dumps(payload).encode() + b"\n")
        while True:
            reply = json.loads(self.qmp_reader.readline())
            if "error" in reply:
                raise AssertionError(reply)
            if "return" in reply:
                return reply["return"]

    def key(self, name):
        names = name if isinstance(name, (list, tuple)) else [name]
        self.qmp("send-key", {"keys": [{"type": "qcode", "data": key} for key in names], "hold-time": 30})
        time.sleep(0.06)

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate(timeout=5)
        if self.qmp_reader:
            self.qmp_reader.close()
        if self.qmp_socket:
            self.qmp_socket.close()
        self.temp.cleanup()

    def shutdown(self):
        self.process.stdin.write(b"shutdown\n")
        self.process.stdin.flush()
        self.until(b"MayOS shutdown.")
        if self.process.wait(timeout=5) != 33:
            raise AssertionError("Guest shutdown failed")
        self.stop()


class BootTests(unittest.TestCase):
    def boot(self, ram="64M", **kwargs):
        guest = Guest(ram, **kwargs)
        self.addCleanup(guest.stop)
        banner = guest.until(b"mayos> ")
        self.assertIn("BOOT_OK", banner)
        self.assertNotIn("FAULT", banner)
        return guest

    def test_serial_monitor_allocator_and_timer(self):
        guest = self.boot()
        self.assertIn("strict mayc --raw", guest.command("info"))
        self.assertIn("0x36d76289", guest.command("info"))
        self.assertIn("SELFTEST PASS", guest.command("selftest"))
        self.assertIn("used: 0 bytes", guest.command("mem"))
        self.assertIn("ALLOC 0x800000", guest.command("alloc 32"))
        self.assertIn("FILLED 16 bytes", guest.command("fill 0x800000 16 65"))
        dumped = guest.command("dump 0x800000 16")
        self.assertIn("41 " * 16, dumped)
        checksum = zlib.adler32(b"A" * 16)
        self.assertIn("ADLER32 " + hex(checksum), guest.command("checksum 0x800000 16"))
        self.assertIn("ALLOC 0x800020", guest.command("alloc 1"))
        self.assertIn("00 ", guest.command("dump 0x800020 1"))
        self.assertIn("used: 48 bytes", guest.command("mem"))
        self.assertIn("SELFTEST PASS", guest.command("selftest"))
        self.assertIn("used: 48 bytes", guest.command("mem"))
        before = int(re.search(r"(\d+) ticks", guest.command("uptime"))[1])
        time.sleep(0.08)
        after = int(re.search(r"(\d+) ticks", guest.command("uptime"))[1])
        self.assertGreater(after, before)
        self.assertIn("Type 1 = usable RAM", guest.command("mmap"))
        guest.process.stdin.write(b"shutdown\n"); guest.process.stdin.flush()
        self.assertIn("MayOS shutdown.", guest.until(b"MayOS shutdown."))
        self.assertEqual(guest.process.wait(timeout=5), 33)
        (ISO.parent / "serial-test.log").write_bytes(guest.transcript)

    def test_input_bounds_and_command_errors(self):
        guest = self.boot()
        for command in ["unknown", "alloc", "alloc -1", "alloc 0", "alloc 2147483648", "alloc 0x",
                        "fill 0x400000 1 1", "fill 0x800000 1 1", "dump 0x800000 1",
                        "checksum 0x800000 1", "help a b c d"]:
            self.assertIn("ERR", guest.command(command), command)
        self.assertIn("ALLOC 0x800000", guest.command("alloc 32"))
        for command in ["fill 0x80001f 2 1", "fill 0x800000 1 256", "fill 0x800000 0 1",
                        "dump 0x800000 257", "checksum 0x800000 4097"]:
            self.assertIn("ERR", guest.command(command), command)
        self.assertIn("line too long", guest.command("x" * 140))
        self.assertIn("show this command list", guest.command("helpX\b"))
        guest.process.stdin.write(b"help\r\n"); guest.process.stdin.flush()
        self.assertIn("show this command list", guest.until(b"mayos> "))
        self.assertIn("allocation arena usage", guest.command("help"))

    def test_arena_exhaustion_is_bounded(self):
        guest = self.boot()
        self.assertIn("ALLOC 0x800000", guest.command("alloc 8388608"))
        self.assertIn("free: 0 bytes", guest.command("mem"))
        self.assertIn("ERR allocation refused", guest.command("alloc 1"))
        self.assertIn("FILLED 1 bytes", guest.command("fill 0xffffff 1 255"))
        self.assertIn("ERR", guest.command("fill 0xffffff 2 1"))
        self.assertIn("ff ", guest.command("dump 0xffffff 1"))

    def test_ps2_keyboard_and_vga_screen(self):
        guest = self.boot()
        guest.connect_qmp()
        for name in ["h", "e", "l", "p", "ret"]:
            guest.key(name)
        self.assertIn("show this command list", guest.until(b"mayos> "))
        self.assertIn("FORMATTED", guest.command("format yes"))
        for name in ["w", "r", "i", "t", "e", "spc", "g", "u", "i", "spc",
                     ("shift", "apostrophe"), "h", "i", "spc", ("shift", "1"),
                     ("shift", "apostrophe"), "ret"]:
            guest.key(name)
        self.assertIn("SAVED gui / 4 bytes", guest.until(b"mayos> "))
        self.assertIn("hi !\r\n", guest.command("cat gui"))
        screenshot = ISO.parent / "mayos-screen.ppm"
        guest.qmp("screendump", {"filename": str(screenshot)})
        content = screenshot.read_bytes()
        self.assertTrue(content.startswith(b"P6\n"))
        pixels = content.split(b"\n", 3)[3]
        self.assertGreater(len(set(pixels)), 1, "VGA framebuffer must contain visible text")

    def test_small_ram_is_rejected_before_allocating(self):
        guest = Guest("8M")
        self.addCleanup(guest.stop)
        guest.until(b"BOOT_ERROR: 8..16 MiB arena is not usable RAM.")
        self.assertEqual(guest.process.wait(timeout=5), 35)

    def test_files_persist_across_reboot_and_load_binary_memory(self):
        with tempfile.TemporaryDirectory(prefix="mayos-persist-") as temp:
            disk = Path(temp) / "disk.img"
            guest = self.boot(disk=disk)
            self.assertIn("no valid snapshot", guest.command("disk"))
            self.assertIn("ERR", guest.command("write note hello"))
            self.assertIn("ERR", guest.command("format"))
            self.assertIn("FORMATTED", guest.command("format yes"))
            self.assertIn("0 / 16 files", guest.command("ls"))
            self.assertIn("SAVED note", guest.command('write note "hello from MayOS"'))
            self.assertIn("hello from MayOS\r\n", guest.command("cat note"))
            self.assertIn("SAVED lines", guest.command('write lines "one\\ntwo\\tthree"'))
            self.assertIn("one\r\ntwo.three", guest.command("cat lines"))
            self.assertIn("SAVED empty / 0", guest.command('write empty ""'))
            self.assertIn("ALLOC 0x800000", guest.command("alloc 480"))
            self.assertIn("FILLED", guest.command("fill 0x800000 480 255"))
            self.assertIn("SAVED binary / 480", guest.command("save binary 0x800000 480"))
            self.assertIn("ERR", guest.command("save binary 0x800000 481"))
            self.assertIn("ERR", guest.command('write bad/name text'))
            self.assertIn("ERR", guest.command('write abcdefghijklmnopqrstuvwx text'))
            self.assertIn("ERR", guest.command('write note "unclosed'))
            self.assertIn("ERR", guest.command('write note "closed"suffix'))
            self.assertIn("ERR", guest.command('write note "bad\\q"'))
            self.assertIn("hello from MayOS\r\n", guest.command("cat note"))
            guest.shutdown()
            guest = self.boot(disk=disk)
            self.assertIn("4 / 16 files", guest.command("ls"))
            self.assertIn("hello from MayOS\r\n", guest.command("cat note"))
            self.assertIn("LOADED 0x800000 / 480 bytes", guest.command("load binary"))
            expected = hex(zlib.adler32(b"\xff" * 480))
            self.assertIn(expected, guest.command("checksum 0x800000 480"))
            self.assertIn("no allocation", guest.command("load empty"))
            self.assertIn("SAVED note", guest.command('write note replacement'))
            self.assertIn("REMOVED lines", guest.command("rm lines"))
            guest.shutdown()
            guest = self.boot(disk=disk)
            self.assertIn("replacement\r\n", guest.command("cat note"))
            self.assertIn("ERR file not found", guest.command("cat lines"))
            guest.shutdown()

    def test_directory_capacity_and_deleted_slot_reuse(self):
        guest = self.boot()
        self.assertIn("FORMATTED", guest.command("format yes"))
        for index in range(16):
            self.assertIn("SAVED", guest.command(f"write f{index} value{index}"))
        self.assertIn("16 / 16 files", guest.command("ls"))
        self.assertIn("directory full", guest.command("write extra text"))
        self.assertIn("SAVED", guest.command("write f0 replacement"))
        self.assertIn("REMOVED", guest.command("rm f8"))
        self.assertIn("SAVED extra", guest.command("write extra text"))
        self.assertIn("16 / 16 files", guest.command("ls"))
        self.assertIn("value9\r\n", guest.command("cat f9"))

    def test_corrupted_latest_snapshot_recovers_previous_generation(self):
        for corrupt_offset in [2 * 512 + 32, 1 * 512 + 8]:
            with self.subTest(offset=corrupt_offset), tempfile.TemporaryDirectory(prefix="mayos-recover-") as temp:
                disk = Path(temp) / "disk.img"
                guest = self.boot(disk=disk)
                guest.command("format yes") # generation 1, bank 0
                guest.command("write note old") # generation 2, bank 1
                guest.command("write note new") # generation 3, bank 0
                guest.shutdown()
                with disk.open("r+b") as image:
                    image.seek(corrupt_offset)
                    byte = image.read(1)
                    image.seek(corrupt_offset)
                    image.write(bytes([byte[0] ^ 1]))
                guest = self.boot(disk=disk)
                self.assertIn("generation 2 / bank 1", guest.command("disk"))
                self.assertIn("old\r\n", guest.command("cat note"))
                self.assertIn("SAVED note", guest.command("write note repaired"))
                guest.shutdown()
                guest = self.boot(disk=disk)
                self.assertIn("generation 3 / bank 0", guest.command("disk"))
                self.assertIn("repaired\r\n", guest.command("cat note"))
                guest.shutdown()

    def test_missing_small_and_invalid_disks_fail_without_writes(self):
        guest = self.boot(attach=False)
        self.assertIn("No supported", guest.command("disk"))
        self.assertIn("ERR", guest.command("format yes"))
        self.assertIn("ERR", guest.command("ls"))
        guest.shutdown()
        with tempfile.TemporaryDirectory(prefix="mayos-invalid-") as temp:
            for size in [512 * 16, 512 * 64]:
                with self.subTest(size=size):
                    disk = Path(temp) / "disk.img"
                    original = bytes([0xA5]) * size
                    disk.write_bytes(original)
                    guest = self.boot(disk=disk)
                    self.assertIn("ERR", guest.command("write note text"))
                    if size < 512 * 35:
                        self.assertIn("too small", guest.command("disk"))
                        self.assertIn("ERR", guest.command("format yes"))
                    else:
                        self.assertIn("no valid snapshot", guest.command("disk"))
                    guest.shutdown()
                    self.assertEqual(disk.read_bytes(), original)

    def test_disk_write_failure_remounts_and_allows_retry(self):
        with tempfile.TemporaryDirectory(prefix="mayos-io-error-") as temp:
            disk = Path(temp) / "disk.img"
            guest = self.boot(disk=disk)
            guest.command("format yes")
            guest.command("write note original")
            guest.shutdown()
            guest = self.boot(disk=disk, fail_write=True)
            self.assertIn("ERR disk commit failed", guest.command("write note lost"))
            self.assertIn("original\r\n", guest.command("cat note"))
            self.assertIn("generation 2", guest.command("disk"))
            self.assertIn("SAVED note", guest.command("write note retried"))
            guest.shutdown()
            guest = self.boot(disk=disk)
            self.assertIn("retried\r\n", guest.command("cat note"))
            guest.shutdown()

    def test_kernel_is_raw_elf_without_runtime_or_interpreter(self):
        blob = (ISO.parent / "kernel.elf").read_bytes()
        self.assertEqual(blob[:6], b"\x7fELF\x02\x01")
        self.assertEqual(struct.unpack_from("<Q", blob, 24)[0], 0x401000)
        offset = struct.unpack_from("<Q", blob, 32)[0]
        stride, count = struct.unpack_from("<HH", blob, 54)
        self.assertEqual(stride, 56)
        for i in range(count):
            kind, flags, file_offset, virtual, physical, file_size, memory_size, align = struct.unpack_from("<II6Q", blob, offset + i * stride)
            self.assertNotEqual(kind, 3, "PT_INTERP must not exist")
            if kind == 1:
                self.assertEqual(virtual, physical)
                self.assertGreaterEqual(physical, 0x400000)
                self.assertLessEqual(physical + memory_size, 0x800000)
                self.assertLessEqual(file_offset + file_size, len(blob))
        self.assertTrue(b"rt_gc\x00" not in blob, "raw kernel must not contain the hosted collector")
        self.assertTrue(b"rt_read_file\x00" not in blob, "raw kernel must not contain hosted file I/O")
        subprocess.run(["grub-file", "--is-x86-multiboot2", str(ISO.parent / "loader.elf")], check=True)


if __name__ == "__main__":
    unittest.main(argv=[__file__, *rest], verbosity=2)
