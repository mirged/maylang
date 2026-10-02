#!/usr/bin/env python3
"""Compare optimized literal bits against the original runtime parser."""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LITERALS = ['0.0', '1.0', '0.1', '0.24', '0.65', '0.95', '25.6', '170.0',
            '1.23456789012345678', '123456789012345678901234567890.0',
            '1.0e20', '1.23e-20', '1e308', '1e-308', '5e-324', '2.2250738585072014e-308']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--compiler', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-float-literals-') as directory:
        work = Path(directory)
        # Both compilers link the corrected address helper; only literal lowering differs.
        source = work/'bits.may'
        source.write_text('fun bits(v: Any) -> Nil { let p: Any = addr(v); print(load32(p), load32(p+4)); return; }\n' +
                          '\n'.join(f'bits({literal}); bits(-{literal});' for literal in LITERALS))
        outputs = []
        for compiler, name in [(args.reference, 'reference'), (args.compiler, 'optimized')]:
            result = subprocess.run([str(compiler.resolve()), str(source), '-o', str(work/name)], cwd=ROOT, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr.decode()
            outputs.append(subprocess.check_output([str(work/name)], timeout=10))
        assert outputs[0] == outputs[1], (outputs[0], outputs[1])
        print('PASS exact literal bit parity: signed zero, ordinary decimals, long mantissas and exponents')


if __name__ == '__main__':
    main()
