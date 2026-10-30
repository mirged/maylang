#!/usr/bin/env python3
"""Compare JSON control-character escaping with an independent parser."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    args = parser.parse_args()
    controls = ''.join(chr(index) for index in range(32))
    text = controls + '"\\λ🙂日本'
    source_code = r'''
mut controls: Any = "";
for index: Int in 0..32 { controls += chr(index); }
let text: Any = controls + "\"\\λ🙂日本";
let document: Any = {};
document[text] = [text, "a\0b", {"nested": text}];
print(json_stringify(text));
print(json_stringify(document));
print(json_stringify(json_parse(json_stringify(document))));
'''
    expected = [text, {text: [text, 'a\0b', {'nested': text}]}]
    with tempfile.TemporaryDirectory(prefix='mayc-json-') as directory:
        source = Path(directory) / 'json.may'
        source.write_text(source_code)
        for target in ['x86_64-linux']:
            binary = Path(directory) / target
            subprocess.run([str(args.compiler.resolve()), '--target', target, str(source),
                            '-o', str(binary)], check=True, capture_output=True, timeout=120)
            result = subprocess.run([str(binary)], capture_output=True, timeout=20)
            assert result.returncode == 0 and not result.stderr, result
            lines = result.stdout.decode().splitlines()
            assert len(lines) == 3, result.stdout
            assert [json.loads(line) for line in lines] == expected + expected[1:], result.stdout
            assert all(byte >= 32 for line in result.stdout.splitlines() for byte in line), result.stdout
            print(f'PASS JSON U+0000–U+001F, quotes, backslashes, Unicode, keys and roundtrips on {target}', flush=True)


if __name__ == '__main__':
    main()
