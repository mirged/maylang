#!/usr/bin/env python3
"""Run the portable core on every ISA/format, including a simulated PE loader."""
import argparse
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile

from backends import compile_source, compiler_binary, elf_segments, macho_segments

HERE = Path(__file__).resolve().parent
EXPECTED = (
    'core 42 -5 -2 true false nil\n'
    '[1, 7, 3] 4 15 4\n'
    'éλ🙂 5 λ 955\n'
    'hi ababab hé,λ,🙂\n'
    'true true true\n'
    '6 30 10 243 256\n'
    '564\n'
    '-1152921504606846976 -1152921504606846976\n'
    'heap 73 73\n'
    '[-2, -1, 0, 1] true [1, 2, 3] heλ HEλ\n'
).encode()


def emulate(image, target, expected=EXPECTED, status=42):
    import unicorn as u
    from unicorn import arm64_const as arm, riscv_const as rv, x86_const as x86
    windows, macos = target.endswith('windows'), target.endswith('macos')
    if target.startswith('arm64'):
        cpu = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM)
        sp, pc = arm.UC_ARM64_REG_SP, arm.UC_ARM64_REG_PC
        number = arm.UC_ARM64_REG_X16 if macos else arm.UC_ARM64_REG_X8
        args = [getattr(arm, f'UC_ARM64_REG_X{i}') for i in range(6)]
    elif target.startswith('riscv'):
        cpu = u.Uc(u.UC_ARCH_RISCV, u.UC_MODE_RISCV64)
        sp, pc, number = rv.UC_RISCV_REG_SP, rv.UC_RISCV_REG_PC, rv.UC_RISCV_REG_A7
        args = [getattr(rv, f'UC_RISCV_REG_A{i}') for i in range(6)]
    else:
        cpu = u.Uc(u.UC_ARCH_X86, u.UC_MODE_64)
        sp, pc, number = x86.UC_X86_REG_RSP, x86.UC_X86_REG_RIP, x86.UC_X86_REG_RAX
        args = [x86.UC_X86_REG_RDI, x86.UC_X86_REG_RSI, x86.UC_X86_REG_RDX,
                x86.UC_X86_REG_R10, x86.UC_X86_REG_R8, x86.UC_X86_REG_R9]
    cpu.mem_map(0x10000000, 0x100000)
    cpu.reg_write(sp, 0x10100000 - (8 if windows else 0))
    output, exits = bytearray(), []
    next_mapping = 0x20000000

    def allocate(size):
        nonlocal next_mapping
        size = (size + 4095) // 4096 * 4096
        address = next_mapping
        cpu.mem_map(address, size)
        next_mapping += size + 4096
        return address

    def write(pointer, count):
        count = min(count, 7)  # Exercise runtime handling of partial writes.
        output.extend(cpu.mem_read(pointer, count))
        return count

    if windows:
        optional = 128 + 24
        base = struct.unpack_from('<Q', image, optional + 24)[0]
        size = struct.unpack_from('<I', image, optional + 56)[0]
        cpu.mem_map(base, size); cpu.mem_write(base, image)
        entry = base + struct.unpack_from('<I', image, optional + 16)[0]
        imports = struct.unpack_from('<I', image, optional + 120)[0]
        assert imports, 'core PE has no OS imports'
        lookup, _, _, dll, iat = struct.unpack_from('<IIIII', image, imports)
        assert image[dll:dll + 13] == b'kernel32.dll\0'
        names = ['GetStdHandle', 'WriteFile', 'VirtualAlloc', 'ExitProcess']
        cpu.mem_map(0x30000000, 4096)
        for index, name in enumerate(names):
            hint = struct.unpack_from('<Q', image, lookup + 8 * index)[0]
            assert image[hint + 2:hint + 3 + len(name)] == name.encode() + b'\0'
            stub = 0x30000000 + index * 256
            cpu.mem_write(stub, b'\xc3')
            cpu.mem_write(base + iat + index * 8, struct.pack('<Q', stub))
        windows_args = [x86.UC_X86_REG_RCX, x86.UC_X86_REG_RDX, x86.UC_X86_REG_R8, x86.UC_X86_REG_R9]

        def imported(uc, address, size, unused):
            index = (address - 0x30000000) // 256
            values = [uc.reg_read(reg) for reg in windows_args]
            assert uc.reg_read(sp) % 16 == 8, 'Windows call is not aligned'
            if index == 0:
                assert values[0] & 0xffffffff == 0xfffffff5
                result = 0xfeed
            elif index == 1:
                assert values[0] == 0xfeed
                assert struct.unpack('<Q', uc.mem_read(uc.reg_read(sp) + 40, 8))[0] == 0
                count = write(values[1], values[2])
                uc.mem_write(values[3], struct.pack('<I', count)); result = 1
            elif index == 2:
                assert values[0] == 0 and values[2:] == [12288, 4]
                result = allocate(values[1])
            else:
                exits.append(values[0]); uc.emu_stop(); return
            for reg in windows_args + [x86.UC_X86_REG_R10, x86.UC_X86_REG_R11]:
                uc.reg_write(reg, 0xbad)
            uc.reg_write(number, result)

        cpu.hook_add(u.UC_HOOK_CODE, imported, begin=0x30000000, end=0x30000300)
    else:
        segments = macho_segments(image) if macos else elf_segments(image)
        for address, memory, file, disk in segments:
            if memory:
                cpu.mem_map(address, (memory + 4095) // 4096 * 4096)
                cpu.mem_write(address, image[file:file + disk])
        entry = 4194304 + 16384 if macos else struct.unpack_from('<Q', image, 24)[0]

        def syscall(uc, *unused):
            call = uc.reg_read(number)
            values = [uc.reg_read(reg) for reg in args]
            is_x86 = target.startswith('x86')
            if call == (60 if is_x86 else 1 if macos else 93):
                exits.append(values[0]); uc.emu_stop(); return
            if call == (1 if is_x86 else 4 if macos else 64):
                assert values[0] == 1
                result = write(values[1], values[2])
            elif call == (9 if is_x86 else 197 if macos else 222):
                assert values[0] == 0 and values[2] == 3
                assert values[3] == (4098 if macos else 34)
                result = allocate(values[1])
            else:
                raise AssertionError((call, values))
            uc.reg_write(number if is_x86 else args[0], result)
            if macos:
                uc.reg_write(arm.UC_ARM64_REG_NZCV, 0)

        if target.startswith('x86'):
            cpu.hook_add(u.UC_HOOK_INSN, syscall, None, 1, 0, x86.UC_X86_INS_SYSCALL)
        else:
            cpu.hook_add(u.UC_HOOK_INTR, syscall)
    cpu.emu_start(entry, 0, count=20000000)
    assert exits == [status] and bytes(output) == expected, (target, exits, bytes(output))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--require-emulation', action='store_true')
    options = parser.parse_args()
    try:
        import unicorn
        have_emulation = True
    except ImportError:
        have_emulation = False
    assert have_emulation or not options.require_emulation, 'Unicorn is required'
    with tempfile.TemporaryDirectory(prefix='mayc-core-') as directory:
        work = Path(directory)
        for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
            binary = work / target
            image = compile_source(options.compiler, HERE / 'backend/core.may', binary, '--runtime', 'core', '--target', target)
            if target == 'x86_64-linux':
                result = subprocess.run([str(binary)], capture_output=True, timeout=10)
                assert result.returncode == 42 and result.stdout == EXPECTED and not result.stderr, result
            if have_emulation:
                emulate(image, target)
            print(f'PASS {target}: core strings/lists/math/heap/console' + ('' if have_emulation else ' (emulation skipped)'), flush=True)
        for body in ['print(1.5);', 'print({"a": 1});', 'let f: Any = |n: Int| -> Int { return n; }; print(f(1));']:
            source = work / 'unsupported.may'; source.write_text(body)
            binary = work / 'unsupported'
            result = subprocess.run([str(options.compiler), '--runtime', 'core', str(source), '-o', str(binary)], capture_output=True)
            assert result.returncode and b'full runtime' in result.stderr and not binary.exists(), result
        print('PASS unsupported core features fail before output is written', flush=True)
        failures = [
            ('let n: Any = int("1152921504606846975"); print(n + 1);', b'integer overflow\n'),
            ('let n: Any = int("-1152921504606846976"); print(n / -1);', b'integer overflow\n'),
            ('let n: Any = 3; print(n / 0);', b'division by zero\n'),
        ]
        for target in ['x86_64-linux', 'arm64-linux', 'riscv64-linux', 'arm64-macos', 'x86_64-windows']:
            for body, message in failures:
                source = work / 'arithmetic.may'; source.write_text(body)
                binary = work / 'arithmetic'
                image = compile_source(options.compiler, source, binary, '--runtime', 'core', '--target', target)
                if target == 'x86_64-linux':
                    result = subprocess.run([str(binary)], capture_output=True, timeout=10)
                    assert result.returncode == 70 and result.stdout == message, result
                if have_emulation:
                    emulate(image, target, message, 70)
        print('PASS core integer overflow and division errors on every target', flush=True)
        small=work/'small';small.mkdir()
        shutil.copy2(compiler_binary(options.compiler),small/'mayc')
        shutil.copytree(HERE.parent/'runtime',small/'runtime')
        core=small/'runtime/core.may'
        core.write_text(core.read_text().replace('CORE_RETAINED + size > 268435456','CORE_RETAINED + size > 2097152'))
        source=work/'limit.may';source.write_text('for i in 0..10 { alloc(700000); }')
        for target in ['x86_64-linux','arm64-linux','riscv64-linux','arm64-macos','x86_64-windows']:
            binary=work/'limited'
            image=compile_source(small/'mayc',source,binary,'--runtime','core','--target',target)
            if target=='x86_64-linux':
                result=subprocess.run([str(binary)],capture_output=True,timeout=10)
                assert result.returncode==70 and result.stdout==b'core heap limit exceeded\n',result
            if have_emulation: emulate(image,target,b'core heap limit exceeded\n',70)
        print('PASS bounded core retained heap on every target',flush=True)


if __name__ == '__main__':
    main()
