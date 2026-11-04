#!/usr/bin/env python3
"""Target selection, isolated output contexts, relocations and raw diagnostics.

The ARM64, RISC-V, Mach-O and PE checks were removed with their targets; the
last versions are in the `frozen-archive` tag.
"""
import argparse
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def compiler_binary(compiler):
    """Resolve the repository launcher before copying a compiler with sidecars."""
    compiler = compiler.resolve()
    directory = ROOT / 'compiler/mayc'
    if compiler in (directory / 'mayc', directory / 'mayc_new'):
        result = subprocess.run([str(compiler), '--version'], cwd=ROOT,
                                capture_output=True, timeout=300)
        assert result.returncode == 0, result.stderr.decode()
        return directory / 'build/bin/mayc_new'
    return compiler


def compile_source(compiler, source, binary, *options):
    result = subprocess.run([str(compiler), *options, str(source), '-o', str(binary)],
                            cwd=ROOT, capture_output=True, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr).decode()
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    options = parser.parse_args()
    compiler = options.compiler.resolve()
    with tempfile.TemporaryDirectory(prefix='mayc-backends-') as directory:
        work = Path(directory)
        context = work / 'context'
        compile_source(compiler, HERE / 'backend/context.may', context)
        result = subprocess.run([str(context)], capture_output=True, timeout=10)
        assert result.returncode == 0 and result.stdout == (b'true true true true\n' * 3 + b'true true\n' * 2), result
        print('PASS interleaved emission contexts, labels, data, image and release', flush=True)
        # Compile a relocation-table stress program against a small runtime.
        # The compiler itself keeps its normal heap; only the emitted fixture
        # gets the limit. Large contiguous list growth previously exhausted
        # fragmented heaps despite ample total free space during self-hosting.
        probe = work / 'mayc'
        shutil.copy2(compiler_binary(compiler), probe)
        shutil.copytree(ROOT / 'compiler/mayc/runtime', work / 'runtime')
        host = work / 'runtime/fat_linux.may'
        assert host.read_text().count('mut sz: Any = 268435456;') == 1
        host.write_text(host.read_text().replace('mut sz: Any = 268435456;', 'mut sz: Any = 8388608;'))
        (work / 'native.may').symlink_to(ROOT / 'compiler/mayc/native.may')
        (work / 'prelude.may').symlink_to(ROOT / 'stdlib/prelude.may')
        fixups = work / 'fixups'
        compile_source(probe, HERE / 'backend/fixups.may', fixups)
        result = subprocess.run([str(fixups)], capture_output=True, timeout=30)
        assert result.returncode == 0 and result.stdout == b'fixups-ok\n' and not result.stderr, result
        print('PASS 65,537 ordered relocations and table replacement on an 8 MiB heap', flush=True)
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
        image = compile_source(compiler, source, binary, '--raw')
        assert list(elf_segments(image)), 'no loadable segments'
        assert subprocess.run([str(binary)], timeout=10).returncode == 0
        print('PASS signed power-of-two quotient/remainder against Python oracle', flush=True)

        # Fat struct fixed-slot reads (#134): a field of a statically known
        # struct is loaded from its declared entry slot behind the layout guard
        # (entries == receiver + 48) instead of the field cache. The guards for
        # slot 0 and slot 1 are distinctive instructions; --no-opt keeps the
        # cache path and must not emit them.
        slots = work / 'record-slots.may'
        slots.write_text('struct Pair { x: Int, y: Int }\n'
                         'let p: Pair = Pair(1, 2);\n'
                         'mut total: Int = 0;\nmut i: Int = 0;\n'
                         'while (i < 10) { total += p.x + p.y; p.x += 1; i += 1; }\n'
                         'print(total, p.x);\n')
        listings = {}
        for label, options in [('optimized', ()), ('no-opt', ('--no-opt',))]:
            binary = work / f'record-slots-{label}'
            compile_source(compiler, slots, binary, *options)
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stdout == b'75 11\n', run
            disassembly = subprocess.check_output(
                ['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)
            listings[label] = ' '.join(disassembly.split())
        guard = 'lea r8,[rax+0x30]'
        slot0 = 'cmp QWORD PTR [rax+0x38],r8'
        slot1 = 'cmp QWORD PTR [rax+0x58],r8'
        assert guard in listings['optimized'] and slot0 in listings['optimized'] and slot1 in listings['optimized'], \
            'fat struct field slots are not read by offset in the optimized build'
        assert guard not in listings['no-opt'] and slot1 not in listings['no-opt'], \
            'fat struct field slots are read by offset under --no-opt'
        print('PASS fat struct fields load from their fixed slot only when optimized', flush=True)

        # Fat enum payload reads (#134 step 4): a variant pattern proves the
        # tag, so match reads the tag entry (slot 0) and the payload entries by
        # fixed slot behind the same layout guard. Slot 2 of a two-field
        # payload is the distinctive one; --no-opt probes through rt_map_get
        # and must not emit any slot guard.
        payloads = work / 'enum-payloads.may'
        payloads.write_text('enum E { A(x: Int), B(y: Int, z: Int) }\n'
                            'fun f(v: E) -> Int {\n'
                            '    match (v) {\n'
                            '        A(x) => { return x; },\n'
                            '        B(y, z) => { return y + z; }\n'
                            '    }\n'
                            '    return 0;\n'
                            '}\n'
                            'mut total: Int = 0;\nmut i: Int = 0;\n'
                            'while (i < 10) { total += f(A(1)) + f(B(2, 3)); i += 1; }\n'
                            'print(total, f(B(2, 3)));\n')
        listings = {}
        for label, options in [('optimized', ()), ('no-opt', ('--no-opt',))]:
            binary = work / f'enum-payloads-{label}'
            compile_source(compiler, payloads, binary, *options)
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stdout == b'60 5\n', run
            disassembly = subprocess.check_output(
                ['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)
            listings[label] = ' '.join(disassembly.split())
        tag_slot = 'cmp QWORD PTR [rax+0x38],r8'
        payload_slot2 = 'cmp QWORD PTR [rax+0x78],r8'
        assert tag_slot in listings['optimized'] and payload_slot2 in listings['optimized'], \
            'enum match payload slots are not read by offset in the optimized build'
        assert tag_slot not in listings['no-opt'] and payload_slot2 not in listings['no-opt'], \
            'enum match payload slots are read by offset under --no-opt'
        print('PASS enum match payloads load from their fixed slot only when optimized', flush=True)
        # Native main (#132): a top-level body whose values are all machine
        # words compiles as native code, and `print` boxes each argument by
        # pushing its fat type word as an immediate. --no-opt keeps the tagged
        # main, so the boxing sequence and the image must differ.
        native_main = work / 'main-native.may'
        native_main.write_text('mut i: Int = 0;\nmut acc: Int = 0;\n'
                               'while (i < 10) { acc += i * 3; i += 1; }\n'
                               'print(acc);\nprint(acc > 100);\n')
        images = {}
        listings = {}
        for label, options in [('optimized', ()), ('no-opt', ('--no-opt',))]:
            binary = work / f'main-native-{label}'
            images[label] = compile_source(compiler, native_main, binary, *options)
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stdout == b'135\ntrue\n', run
            disassembly = subprocess.check_output(
                ['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)
            body = re.sub(r'^\s*[0-9a-f]+:\s*', '', disassembly, flags=re.M)
            listings[label] = ' '.join(body.split())
        assert images['optimized'] != images['no-opt'], \
            'the native main produced the same image as the tagged main'
        assert 'push 0x2 push rax' in listings['optimized'] and 'push 0x1 push rax' in listings['optimized'], \
            'the optimized build does not box print arguments from a native main'
        assert 'push 0x2 push rax' not in listings['no-opt'] and 'push 0x1 push rax' not in listings['no-opt'], \
            'the tagged main boxes print arguments with an immediate type word'
        print('PASS native main boxes word arguments and differs from --no-opt', flush=True)
        # Native Float loop bodies (#132): a Float function with a loop compiles
        # as native words. The loop-carried Float local keeps an XMM home (xmm8
        # or higher) and the arithmetic is SSE, while the fat backend's
        # per-operation type-word checks (`cmp r9,0x3`) are absent. --no-opt
        # keeps the loop tagged, so the images and the markers differ.
        float_loops = work / 'float-loops-native.may'
        float_loops.write_text('fun run(n: Int, x: Float) -> Float {\n'
                               '    mut acc: Float = x;\n'
                               '    mut i: Int = 0;\n'
                               '    while (i < n) { acc = acc * 1.5 + 0.25; i += 1; }\n'
                               '    return acc;\n'
                               '}\n'
                               'print(run(100, 1.0));\n')
        images = {}
        bodies = {}
        for label, options in [('optimized', ()), ('no-opt', ('--no-opt',))]:
            binary = work / f'float-loops-{label}'
            images[label] = compile_source(compiler, float_loops, binary, *options)
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stdout == b'6.098417663028227e17\n', run
            disassembly = subprocess.check_output(
                ['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)
            inside = False
            lines = []
            for line in disassembly.splitlines():
                if re.match(r'^[0-9a-f]+ <', line):
                    inside = 'module0::run' in line
                    continue
                if inside: lines.append(line)
            bodies[label] = ' '.join(' '.join(lines).split())
        assert images['optimized'] != images['no-opt'], \
            'the native Float loop produced the same image as the tagged loop'
        assert 'mulsd' in bodies['optimized'] and 'addsd' in bodies['optimized'], \
            'the optimized Float loop does not compute with SSE'
        assert 'xmm8' in bodies['optimized'], 'the Float loop local has no XMM home'
        assert 'cmp r9,0x3' not in bodies['optimized'], \
            'the native Float loop keeps the fat type-word checks'
        assert 'cmp r9,0x3' in bodies['no-opt'] or 'movsd' in bodies['no-opt'], \
            'the tagged Float loop does not use the fat Float path'
        print('PASS native Float loop bodies keep an XMM home and lose the type checks', flush=True)
        # Native Float main (#132b): a top-level body whose values are all Int,
        # Bool or Float machine words is emitted as native code too, so Float
        # print arguments are boxed with the type word 3 as an immediate and
        # the fat backend's per-operation checks are absent. --no-opt keeps the
        # tagged main, so the image and the markers differ.
        float_main = work / 'float-main-native.may'
        float_main.write_text('mut a: Float = 1.5;\n'
                              'mut i: Int = 0;\n'
                              'while (i < 3) { a = a * 2.0 + 0.5; i += 1; }\n'
                              'print(a, a > 2.0);\n')
        images = {}
        mains = {}
        for label, options in [('optimized', ()), ('no-opt', ('--no-opt',))]:
            binary = work / f'float-main-{label}'
            images[label] = compile_source(compiler, float_main, binary, *options)
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stdout == b'15.5 true\n', run
            disassembly = subprocess.check_output(
                ['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)
            # main is the code after _start, up to the next labelled function.
            inside = False
            lines = []
            for line in disassembly.splitlines():
                match = re.match(r'^[0-9a-f]+ <([^>]+)>:', line)
                if match:
                    if inside: break
                    inside = match.group(1) == '_start'
                    continue
                if inside: lines.append(line)
            mains[label] = ' '.join(' '.join(lines).split())
        assert images['optimized'] != images['no-opt'], \
            'the native Float main produced the same image as the tagged main'
        assert 'push 0x3' in mains['optimized'], \
            'the optimized build does not box a Float print argument as type 3'
        assert 'cmp r9,0x3' not in mains['optimized'], \
            'the native Float main keeps the fat type-word checks'
        assert 'push 0x3' not in mains['no-opt'] and 'cmp r9,0x3' in mains['no-opt'], \
            'the tagged main does not use the fat Float path'
        print('PASS native Float main boxes type 3 and loses the type checks', flush=True)
        for args, message in [(['--target', 'bogus'], b'unknown target'),
                              (['--target'], b'requires a target name'),
                              (['--target', 'arm64-linux'], b'target arm64-linux is not supported'),
                              (['--runtime', 'core'], b'runtime core is not supported')]:
            output = work / 'invalid'
            command = [str(compiler), *args]
            if args != ['--target']:
                command += [str(HERE / 'backend/bench.may'), '-o', str(output)]
            result = subprocess.run(command, capture_output=True)
            assert result.returncode != 0 and message in result.stderr and not output.exists(), result
        print('PASS target diagnostics reject unsupported output before writing', flush=True)
        # Raw string intrinsics need a literal; x86-64 once silently read garbage.
        for call, message in [('addr(s)', b'raw addr/cstr requires a string literal'),
                              ('cstr(s)', b'raw addr/cstr requires a string literal'),
                              ('len(s)', b'raw len requires a string literal')]:
            source = work / 'raw_literal.may'
            source.write_text(f'fun main() -> Int {{ let s: Str = "abc"; let v: Any = {call}; return 0; }}\nmain();\n')
            for target in ['x86_64-linux']:
                output = work / 'raw_literal'
                result = subprocess.run([str(compiler), '--raw', '--target', target, str(source), '-o', str(output)], capture_output=True)
                assert result.returncode != 0 and message in result.stderr and not output.exists(), (target, call, result)
        print('PASS raw addr, cstr and len reject non-literal strings', flush=True)


if __name__ == '__main__':
    main()
