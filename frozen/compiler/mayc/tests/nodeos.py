#!/usr/bin/env python3
"""x86_64-nodeos: NXF images, runtime selection and target diagnostics.

The checks here mirror what NodeOS's loader (`nodeos_abi::nxf::Image::parse`
and `verify_checksum`) requires before it maps a single page. Running the
images needs NodeOS itself; `make test-maylang` in a NodeOS checkout boots
them in QEMU, including mayc compiling programs and itself on NodeOS.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[3]

HEADER = struct.Struct('<4sHHHHIQQQ' + 'I' * 13 + '16sIII16x')
SEGMENT = struct.Struct('<IIQQQQQ')
CAPABILITY = struct.Struct('<IIII')
RESOURCES = struct.Struct('<QQQQQIIIII20x')
CHECKSUM_OFFSET = 108


def compile_source(compiler, source, output, *options):
    result = subprocess.run([str(compiler), *options, str(source), '-o', str(output)],
                            cwd=ROOT, capture_output=True, timeout=180)
    assert result.returncode == 0, (result.stdout + result.stderr).decode()
    return output.read_bytes()


def table(image, offset, count, stride):
    assert offset + count * stride <= len(image), 'table out of bounds'
    return [image[offset + index * stride:offset + (index + 1) * stride] for index in range(count)]


def parse_nxf(image):
    """Validate an image the way NodeOS's loader does and return its parts."""
    assert len(image) >= 136, 'image shorter than its header'
    fields = HEADER.unpack_from(image)
    magic, version, header_size, arch, abi, flags, entry, base, size = fields[:9]
    (segment_offset, segment_count, reloc_offset, reloc_count, dep_offset, dep_count,
     cap_offset, cap_count, resource_offset, str_offset, str_size, signature_offset,
     _signature_size) = fields[9:22]
    _build_id, checksum, name_offset, _image_version = fields[22:26]
    assert (magic, version, header_size, arch, abi) == (b'NXF\0', 1, 136, 1, 1), fields[:5]
    assert flags & 1 == 0 and reloc_count == 0 and dep_count == 0 and signature_offset == 0
    segments = [SEGMENT.unpack(raw) for raw in table(image, segment_offset, segment_count, SEGMENT.size)]
    capabilities = [CAPABILITY.unpack(raw) for raw in table(image, cap_offset, cap_count, CAPABILITY.size)]
    resources = RESOURCES.unpack(table(image, resource_offset, 1, RESOURCES.size)[0])
    strings = table(image, str_offset, str_size, 1)
    name = b''.join(strings)[name_offset:].split(b'\0')[0].decode()
    executable_entry = False
    for kind, seg_flags, file_offset, file_size, virtual, memory, alignment in segments:
        assert seg_flags & 6 != 6, 'writable and executable segment'
        assert file_size <= memory and file_offset + file_size <= len(image)
        assert virtual + memory <= size, 'segment beyond image size'
        assert file_offset % 4096 == 0 and virtual % 4096 == 0 and alignment == 4096
        if seg_flags & 4 and virtual <= entry < virtual + memory:
            executable_entry = True
    assert executable_entry, 'entry outside an executable segment'
    unsummed = image[:CHECKSUM_OFFSET] + b'\0\0\0\0' + image[CHECKSUM_OFFSET + 4:]
    assert checksum == zlib.crc32(unsummed), 'CRC-32 mismatch'
    return {'base': base, 'entry': entry, 'segments': segments, 'capabilities': capabilities,
            'resources': resources, 'name': name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    options = parser.parse_args()
    compiler = options.compiler.resolve()
    with tempfile.TemporaryDirectory(prefix='mayc-nodeos-') as directory:
        work = Path(directory)
        listing = subprocess.run([str(compiler), '--list-targets'], capture_output=True, timeout=60)
        assert listing.returncode == 0 and b'x86_64-nodeos\tnxf\tfull\n' in listing.stdout, listing
        print('PASS x86_64-nodeos is listed with the full runtime', flush=True)

        sources = {
            'full': ('print("hello");\nlet m: Map<Str, Int> = {"a": 1};\nprint(m);\n', []),
            'core': ('print(map([1, 2], fun(v: Int) -> Int { return v + 1; }));\n', ['--runtime', 'core']),
            'raw': ('syscall(1, 1, addr("raw\\n"), 4);\nsyscall(60, 0);\n', ['--raw']),
        }
        for mode, (text, flags) in sources.items():
            source = work / f'{mode}.may'
            source.write_text(text)
            image = compile_source(compiler, source, work / f'{mode}.nxf', '--target', 'x86_64-nodeos', *flags)
            nxf = parse_nxf(image)
            assert nxf['name'] == mode and nxf['base'] == 0x400000 and nxf['entry'] == 0x1000, nxf
            kinds = [segment[:2] for segment in nxf['segments']]
            assert kinds[:2] == [(1, 5), (3, 3)] and all(kind == (2, 1) for kind in kinds[2:]), kinds
            required = {cap[0] for cap in nxf['capabilities'] if cap[1] == 1}
            assert required == {8, 10, 12}, nxf['capabilities']
            assert nxf['resources'][1] == 8 << 20, nxf['resources']
            # Every syscall site calls the gate; a program reaches NodeOS's own
            # syscall instruction only inside the personality.
            assert image.count(b'\x0f\x05') >= 1
        print('PASS full, core and raw NXF images pass the loader\'s structural and CRC-32 checks', flush=True)

        # NodeOS's kernel copies an image into one buddy block, at most 4 MiB.
        image = compile_source(compiler, ROOT / 'compiler/mayc/main.may', work / 'mayc.nxf', '--target', 'x86_64-nodeos')
        assert len(image) < 4 << 20, f'NodeOS mayc image is {len(image)} bytes'
        print(f'PASS the NodeOS compiler image ({len(image)} bytes) fits the loader\'s 4 MiB copy', flush=True)

        source = work / 'default.may'
        source.write_text('print(1);\n')
        result = subprocess.run([str(compiler), '--target', 'x86_64-nodeos', str(source)],
                                cwd=work, capture_output=True, timeout=180)
        assert result.returncode == 0 and (work / 'default.nxf').is_file(), result
        print('PASS NodeOS output defaults to the .nxf suffix the shell runs', flush=True)

        linux = compile_source(compiler, sources_file(work, 'same.may', 'print("same");\n'), work / 'same')
        assert linux[:4] == b'\x7fELF', 'x86_64-linux output changed format'
        print('PASS x86_64-linux remains the default target on a Linux host', flush=True)

        for text, flags, message in [
            ('__nodeos_syscall(23);\n', [], b'__nodeos_syscall requires --target x86_64-nodeos'),
            ('extern "libc.so.6" {\n    fun abs(n: Int32) -> Int32;\n}\nprint(abs(-3));\n',
             ['--target', 'x86_64-nodeos'], b'x86_64-nodeos has no dynamic loader'),
        ]:
            source = sources_file(work, 'invalid.may', text)
            output = work / 'invalid'
            result = subprocess.run([str(compiler), *flags, str(source), '-o', str(output)],
                                    capture_output=True, timeout=180)
            assert result.returncode != 0 and message in result.stderr and not output.exists(), result
        print('PASS NodeOS-only builtins and C externs are rejected before writing', flush=True)


def sources_file(work, name, text):
    path = work / name
    path.write_text(text)
    return path


if __name__ == '__main__':
    main()
