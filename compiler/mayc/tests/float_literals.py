#!/usr/bin/env python3
"""Check that float literals compile to correctly rounded binary64 bits."""
import argparse
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
LITERALS = ['0.0', '1.0', '0.1', '0.24', '0.65', '0.95', '25.6', '170.0',
            '1.23456789012345678', '123456789012345678901234567890.0',
            '1.0e20', '1.23e-20', '1e308', '1e-308', '5e-324', '2.2250738585072014e-308']
# Halfway, boundary, overflow and underflow cases that naive decimal scaling misrounds.
HARD = ['9007199254740993.0', '9007199254740995.0', '1e23', '8.98846567431158e307',
        '1.7976931348623157e308', '1.7976931348623158e308', '1.7976931348623159e308', '1e400',
        '2.2250738585072011e-308', '4.9406564584124654e-324', '2.4703282292062328e-324',
        '2.4703282292062327e-324', '1e-400', '0.000000000190821492927058770002',
        '6.07710050630396597660e-11', '0.0027777777777015593', '3.141592653589793238462643383279']


def literals():
    rng = random.Random(907)
    values = LITERALS + HARD
    while len(values) < 400:
        value = struct.unpack('<d', struct.pack('<Q', rng.getrandbits(63)))[0]
        if value == value and value != float('inf'):
            text = repr(value)
            values.append(text if '.' in text or 'e' in text else text + '.0')
    values += ['%.*e' % (rng.randint(0, 25), rng.uniform(1, 10) * 10.0 ** rng.randint(-300, 300)) for _ in range(100)]
    return values


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--compiler', type=Path, required=True)
    p.add_argument('--clang', default='clang')
    args = p.parse_args()
    values = literals()
    expected = ''.join('%d %d\n' % struct.unpack('<II', struct.pack('<d', float(text))) for text in values).encode()
    modes = [('full', []), ('core', ['--runtime', 'core'])]
    if shutil.which(args.clang):
        modes.append(('llvm', ['--target', 'clang-llvm']))
    with tempfile.TemporaryDirectory(prefix='mayc-float-literals-') as directory:
        work = Path(directory)
        source = work / 'bits.may'
        source.write_text('fun bits(v: Any) -> Nil { print(__math_low(v), __math_high(v)); return; }\n' +
                          '\n'.join(f'bits({text});' for text in values))
        for name, flags in modes:
            result = subprocess.run([str(args.compiler.resolve()), *flags, str(source), '-o', str(work / name)],
                                    cwd=ROOT, capture_output=True, timeout=120)
            assert result.returncode == 0, result.stderr.decode()
            output = subprocess.check_output([str(work / name)], timeout=10)
            mismatches = [(text, got, want) for text, got, want in
                          zip(values, output.decode().splitlines(), expected.decode().splitlines()) if got != want]
            assert not mismatches, (name, len(mismatches), mismatches[:5])
        print(f'PASS correctly rounded float literals ({len(values)} values; {", ".join(name for name, _ in modes)})')


if __name__ == '__main__':
    main()
