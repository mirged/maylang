#!/usr/bin/env python3
"""Measure streamed cold and unchanged workspace pulls without timing gates."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

from test_lsp import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--files', type=int, default=1024)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    assert 2 <= args.files <= 10032
    binary = args.binary.resolve()
    report = {'files': args.files, 'workspace_file_limit': 10000,
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'measurements': {}, 'timing': 'one cold streamed pull and one unchanged buffered pull, each interleaved with hover; no timing gate'}
    with tempfile.TemporaryDirectory(prefix='maylsp-diagnostic-benchmark-') as directory:
        folder = Path(directory)
        paths = [folder / f'file{i:05}.may' for i in range(args.files)]
        for i, path in enumerate(paths):
            path.write_text(f'let value: Int = {i};\nprint(value);\n')
        source = paths[0]
        client = Client(binary)
        try:
            client.result('initialize', {'rootUri': folder.as_uri(), 'initializationOptions': {'strict': True}})
            doc = {'textDocument': {'uri': source.as_uri()}}
            client.send('textDocument/didOpen', {'textDocument': {
                'uri': source.as_uri(), 'text': source.read_text(), 'version': 1, 'languageId': 'maylang'}})
            assert client.result('textDocument/diagnostic', doc)['items'] == []
            previous = []
            for name, params in [('cold', {'previousResultIds': [], 'partialResultToken': 'reports', 'workDoneToken': 'work'}),
                                 ('unchanged', None)]:
                if params is None:
                    params = {'previousResultIds': previous}
                start = time.monotonic()
                pending = client.send('workspace/diagnostic', params, request=True)
                hover = client.send('textDocument/hover', {**doc, 'position': {'line': 1, 'character': 7}}, request=True)
                reports, received, progress = {}, {}, []
                while len(received) < 2:
                    reply = client.receive(timeout=40)
                    if 'id' not in reply:
                        if reply.get('method') == '$/progress':
                            value = reply['params']['value']
                            if reply['params']['token'] == 'reports':
                                for item in value['items']:
                                    assert item['uri'] not in reports, item
                                    reports[item['uri']] = item
                                if len(reports) % 1000 == 0:
                                    print(f'{name}: {len(reports)} files checked', flush=True)
                            else:
                                progress.append(value)
                        continue
                    assert 'error' not in reply and reply['id'] in (pending, hover), reply
                    received[reply['id']] = (time.monotonic() - start, reply['result'])
                result = received[pending][1]
                if name == 'cold':
                    assert result['items'] == []
                    assert progress[0]['kind'] == 'begin' and progress[-1]['kind'] == 'end'
                    assert any(p.get('percentage') == 100 for p in progress)
                    bad = [r for r in reports.values() if r['kind'] != 'full' or r['items']]
                    assert not bad, bad[:3]
                else:
                    assert len({r['uri'] for r in result['items']}) == len(result['items'])
                    reports = {r['uri']: r for r in result['items']}
                    assert all(r['kind'] == 'unchanged' and 'items' not in r for r in reports.values())
                assert len(reports) == min(args.files, 10000), len(reports)
                assert reports[source.as_uri()]['version'] == 1
                assert all(r['version'] is None for uri, r in reports.items() if uri != source.as_uri())
                ids = [{'uri': uri, 'value': item['resultId']} for uri, item in reports.items()]
                if previous:
                    assert previous == ids
                previous = ids
                report['measurements'][name] = {'diagnostics_ms': round(received[pending][0] * 1000, 3),
                    'hover_ms': round(received[hover][0] * 1000, 3), 'result_count': len(reports)}
                print(name, report['measurements'][name], flush=True)
            if args.files > 10000:
                omitted = next(p for p in paths if p.as_uri() not in reports)
                result = client.result('workspace/diagnostic', {'previousResultIds': previous[:-1] + [
                    {'uri': omitted.as_uri(), 'value': 'previous-report'}]})
                assert len(result['items']) == 10000
                assert omitted.as_uri() not in {r['uri'] for r in result['items']}, 'scan limit cleared an existing omitted file'
                report['scan_limit_preserves_omitted_diagnostics'] = True
            client.stop()
        finally:
            if client.process.poll() is None:
                client.process.kill(); client.process.wait()
    args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
