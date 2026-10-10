#!/usr/bin/env python3
"""Structured original locations and bounded recovery across declarations."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--compiler',type=Path,default=ROOT/'toolchain/mayc/mayc_new')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mayc-diagnostics-') as directory:
        work=Path(directory); source=work/'app.may'; library=work/'library.may'; binary=work/'output'
        library.write_text('fun a() -> Int { return "bad"; }\nfun b() -> Bool { return 7; }\n')
        source.write_text('import "library";\nlet c: Int = "wrong";\n')
        def check(expected):
            result=subprocess.run([str(args.compiler.resolve()),'--diagnostics','json',str(source),'-o',str(binary)],capture_output=True,timeout=60)
            assert result.returncode != 0 and not binary.exists(),result
            report=json.loads(result.stderr)
            assert report['schema_version']==1,report
            records=report['diagnostics']; assert len(records)==expected,report
            for record in records:
                assert record['severity']=='error' and record['code'].startswith('E_') and record['range']['start']['line']>=1,record
                assert record['column_unit']=='utf8-byte'
            return records
        records=check(3)
        assert {(Path(r['file']).name,r['range']['start']['line']) for r in records} == {('library.may',1),('library.may',2),('app.may',2)},records
        assert all(record['stage']=='type' for record in records)
        print('PASS multiple type errors preserve original import paths and lines',flush=True)
        nested = work/'nested'; nested.mkdir()
        leaf = nested/'leaf.may'; leaf.write_text('pub fun broken() -> Int { return "bad"; }\n')
        library.write_text('from "nested/leaf" import broken;\nfun use() -> Int { return broken(); }\n')
        source.write_text('import "library";\nprint(42);\n')
        records = check(1)
        assert records[0]['file'] == str(leaf) and records[0]['range']['start']['line'] == 1, records
        print('PASS nested selective imports preserve original diagnostic ranges',flush=True)
        source.write_text('fun broken() -> Int { let n = ; return 1; }\nlet bad = ;\nlet good = 1;\n')
        records=check(2); assert all(record['stage']=='parse' for record in records)
        print('PASS parser recovery across block and statement boundaries',flush=True)
        source.write_text('\n'.join(f'let value{i} = ;' for i in range(40)))
        check(20)
        source.write_text('let message = "héllo";\nlet number: Int = message;\n')
        records=check(1); assert records[0]['range']['start']['line']==2
        source.write_text('let text = "🙂"; let number: Int = text;\n')
        records=check(1)
        assert records[0]['range']['start']['column'] == source.read_text().encode().index(b'let number') + 1, records
        result=subprocess.run([str(args.compiler.resolve()),str(source),'-o',str(binary)],capture_output=True,timeout=60)
        assert b'^' in result.stderr and b'expected Int, found Str' in result.stderr,result
        assert source.read_bytes().strip() in result.stderr and result.stderr.endswith(b'^^^\n'), result
        unicode_path = work/'šaltinis🙂.may'; unicode_path.write_text('let n: Int = "bad";\n')
        result=subprocess.run([str(args.compiler.resolve()),'--diagnostics','json','--check',str(unicode_path)],capture_output=True,timeout=60)
        assert json.loads(result.stderr)['diagnostics'][0]['file'] == str(unicode_path), result
        source.write_text('print(42);')
        result=subprocess.run([str(args.compiler.resolve()),'--diagnostics','json','--check',str(source)],capture_output=True,timeout=60)
        assert result.returncode==0 and not result.stderr,result
        print('PASS bounded errors, text carets, Unicode source and successful checks',flush=True)


if __name__=='__main__':
    main()
