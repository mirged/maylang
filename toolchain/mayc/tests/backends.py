#!/usr/bin/env python3
"""Target/format selection, isolated output contexts, and real ISA emulation.

Unicorn is optional for structural checks; --require-emulation makes its absence
an error. Install it in a temporary venv and run this test inside that venv.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def compile_source(compiler, source, binary, *options):
    result = subprocess.run([str(compiler), *options, str(source), '-o', str(binary)],
                            cwd=ROOT, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode()
    return binary.read_bytes()


def elf_segments(image):
    offset = struct.unpack_from('<Q', image, 32)[0]
    size, count = struct.unpack_from('<HH', image, 54)
    for index in range(count):
        kind, flags, file, virtual, _, disk, memory, alignment = struct.unpack_from('<IIQQQQQQ', image, offset + index * size)
        if kind == 1:
            assert flags & 3 != 3, 'writable executable segment'
            assert file % alignment == virtual % alignment
            yield virtual, memory, file, disk


def macho_segments(image):
    offset = 32
    for _ in range(struct.unpack_from('<I', image, 16)[0]):
        kind, size = struct.unpack_from('<II', image, offset)
        if kind == 25:
            name = image[offset + 8:offset + 24].rstrip(b'\0')
            address, memory, file, disk = struct.unpack_from('<QQQQ', image, offset + 24)
            if name != b'__PAGEZERO':
                yield address, memory, file, disk
        offset += size


def emulate(image, arch, macos=False, windows=False):
    import unicorn as u
    from unicorn import arm64_const as arm, riscv_const as rv, x86_const as x86
    if arch == 'arm64':
        cpu = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM)
        sp, pc = arm.UC_ARM64_REG_SP, arm.UC_ARM64_REG_PC
        number = arm.UC_ARM64_REG_X16 if macos else arm.UC_ARM64_REG_X8
        arguments = [getattr(arm, f'UC_ARM64_REG_X{i}') for i in range(6)]
    elif arch == 'riscv64':
        cpu = u.Uc(u.UC_ARCH_RISCV, u.UC_MODE_RISCV64)
        sp, pc, number = rv.UC_RISCV_REG_SP, rv.UC_RISCV_REG_PC, rv.UC_RISCV_REG_A7
        arguments = [getattr(rv, f'UC_RISCV_REG_A{i}') for i in range(6)]
    else:
        cpu = u.Uc(u.UC_ARCH_X86, u.UC_MODE_64)
        sp, pc = x86.UC_X86_REG_RSP, x86.UC_X86_REG_RIP
    if windows:
        base = struct.unpack_from('<Q', image, 128 + 24 + 24)[0]
        size = struct.unpack_from('<I', image, 128 + 24 + 56)[0]
        cpu.mem_map(base, size)
        cpu.mem_write(base, image)
        entry = base + struct.unpack_from('<I', image, 128 + 24 + 16)[0]
    else:
        segments = list(macho_segments(image) if macos else elf_segments(image))
        for address, memory, file, disk in segments:
            if memory:
                cpu.mem_map(address, (memory + 4095) // 4096 * 4096)
                cpu.mem_write(address, image[file:file + disk])
        entry = 4194304 + 16384 if macos else struct.unpack_from('<Q', image, 24)[0]
    cpu.mem_map(0x10000000, 0x100000)
    cpu.reg_write(sp, 0x10100000 - (8 if windows else 0))
    output, status = bytearray(), []
    if windows:
        sentinel = 0x10000000
        cpu.mem_write(0x10100000 - 8, struct.pack('<Q', sentinel))
        cpu.reg_write(x86.UC_X86_REG_RDI, 0x12345678)
        cpu.reg_write(x86.UC_X86_REG_RSI, 0x87654321)
        allocated = [getattr(x86, f'UC_X86_REG_R{i}') for i in range(12, 16)]
        for index, register in enumerate(allocated):
            cpu.reg_write(register, 0xabc000 + index)
        cpu.emu_start(entry, sentinel, count=1000000)
        assert cpu.reg_read(pc) == sentinel
        assert cpu.reg_read(x86.UC_X86_REG_RAX) == 0
        assert cpu.reg_read(x86.UC_X86_REG_RDI) == 0x12345678
        assert cpu.reg_read(x86.UC_X86_REG_RSI) == 0x87654321
        for index, register in enumerate(allocated):
            assert cpu.reg_read(register) == 0xabc000 + index, 'allocator broke callee-save ABI'
        return

    def trap(uc, interrupt, unused):
        call = uc.reg_read(number)
        args = [uc.reg_read(register) for register in arguments]
        if call == (1 if macos else 93):
            status.append(args[0]); uc.emu_stop()
        elif call == (4 if macos else 64):
            assert args[0] == 1
            output.extend(uc.mem_read(args[1], args[2]))
            uc.reg_write(arguments[0], args[2])
        elif call == 222:
            assert args[:4] == [0, 4096, 3, 34]
            uc.mem_map(0x20000000, 4096)
            uc.reg_write(arguments[0], 0x20000000)
        else:
            raise AssertionError((interrupt, call, args))

    cpu.hook_add(u.UC_HOOK_INTR, trap)
    cpu.emu_start(entry, 0, count=1000000)
    assert bytes(output) == b'target-ok\n' and status == [42], (bytes(output), status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--require-emulation', action='store_true')
    options = parser.parse_args()
    compiler = options.compiler.resolve()
    try:
        import unicorn
        have_emulation = True
    except ImportError:
        have_emulation = False
    assert have_emulation or not options.require_emulation, 'Unicorn is required'
    with tempfile.TemporaryDirectory(prefix='mayc-backends-') as directory:
        work = Path(directory)
        context = work / 'context'
        compile_source(compiler, HERE / 'backend/context.may', context)
        result = subprocess.run([str(context)], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == (b'true true true true\n' * 3 + b'true true\n' * 2), result
        print('PASS interleaved emission contexts, labels, data, image and release', flush=True)
        # Independent Python oracle for signed constant division/remainder.
        # Weight terms so positive/negative mistakes cannot cancel each other.
        divisors = [1 << power for power in range(11)]
        expected = 0
        for n in range(-4097, 4098):
            for divisor in divisors:
                quotient = -(abs(n) // divisor) if n < 0 else n // divisor
                remainder = n - quotient * divisor
                expected += quotient * (n + 5000) + remainder * (n + 6000)
        source = work / 'raw-oracle.may'
        expressions = ''.join(f'checksum = checksum + (n / {d}) * (n + 5000) + (n % {d}) * (n + 6000);\n' for d in divisors)
        source.write_text('mut checksum: Any = 0; mut n: Any = -4097;\nwhile n <= 4097 {\n' + expressions +
                          'n = n + 1; }\n' + f'if checksum != {expected} {{ exit(1); }}\n' +
                          'let minimum: Any = -1152921504606846976;\n' +
                          'if minimum / 8 != -144115188075855872 or minimum % 8 != 0 { exit(2); }\nexit(0);\n')
        binary = work / 'raw-oracle'
        compile_source(compiler, source, binary, '--raw')
        assert subprocess.run([str(binary)], timeout=10).returncode == 0
        print('PASS signed power-of-two quotient/remainder against Python oracle', flush=True)

        raw = (HERE / 'backend/raw.may').read_text()
        # Linux AArch64 and RV64 use the generic syscall table, not x86 numbers.
        for target, machine, arch in [('arm64-linux', 183, 'arm64'), ('riscv64-linux', 243, 'riscv64')]:
            image = compile_source(compiler, HERE / 'backend/raw.may', work / target, '--raw', '--target', target)
            assert image[:4] == b'\x7fELF' and struct.unpack_from('<H', image, 18)[0] == machine
            assert len(list(elf_segments(image))) == 4
            readelf = subprocess.run(['readelf', '-hSWl', str(work / target)], capture_output=True)
            assert readelf.returncode == 0 and not readelf.stderr, readelf.stderr
            if have_emulation:
                emulate(image, arch)
            print(f'PASS {target} ELF and integer/pointer/call/branch execution' if have_emulation else f'PASS {target} ELF (execution skipped: install Unicorn)', flush=True)
        # Mach-O exercises Darwin syscall conventions without Linux mmap flags.
        source = work / 'darwin.may'
        source.write_text(raw[:raw.index('let memory:')] + 'syscall(4, 1, addr("target-ok\\n"), 10);\nexit(42);\n')
        image = compile_source(compiler, source, work / 'darwin', '--raw', '--target', 'arm64-macos')
        assert struct.unpack_from('<IIII', image) == (0xfeedfacf, 0x100000c, 0, 2)
        assert len(list(macho_segments(image))) == 3
        thread = 32 + 72 * 4
        assert struct.unpack_from('<IIII', image, thread) == (5, 288, 6, 68)
        assert struct.unpack_from('<Q', image, thread + 16 + 256)[0] == 4194304 + 16384
        if have_emulation:
            emulate(image, 'arm64', macos=True)
        print('PASS ARM64 Mach-O layout and Darwin syscall ABI (native signing not tested)', flush=True)
        source = work / 'windows.may'
        source.write_text('fun add(a: Any, b: Any) -> Any { return a + b; }\nmut n: Any = 0; while n < 10 { n = add(n, 1); }\n')
        image = compile_source(compiler, source, work / 'windows.exe', '--raw', '--target', 'x86_64-windows')
        assert image[:2] == b'MZ' and image[128:132] == b'PE\0\0'
        assert struct.unpack_from('<HH', image, 132) == (0x8664, 3)
        objdump = subprocess.run(['objdump', '-p', str(work / 'windows.exe')], capture_output=True)
        assert objdump.returncode == 0 and b'pei-x86-64' in objdump.stdout, objdump.stderr
        if have_emulation:
            emulate(image, 'x86_64', windows=True)
        print('PASS x86-64 PE32+ headers, entry return and preserved Windows registers', flush=True)
        for args, message in [(['--target', 'bogus'], b'unknown target'),
                              (['--target'], b'requires a target name'),
                              (['--target', 'arm64-linux', '--runtime', 'full'], b'--runtime full requires')]:
            output = work / 'invalid'
            command = [str(compiler), *args]
            if args != ['--target']:
                command += [str(HERE / 'backend/bench.may'), '-o', str(output)]
            result = subprocess.run(command, capture_output=True)
            assert result.returncode != 0 and message in result.stderr and not output.exists(), result
        print('PASS target diagnostics reject unsupported output before writing', flush=True)


if __name__ == '__main__':
    main()
