#!/usr/bin/env python3
"""Measure navigation at the workspace indexing limit and interleaved hover."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

from navigation_fixture import workspace
from test_lsp import Client, position


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--files', type=int, default=10000)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    assert 2 <= args.files <= 10032
    binary = args.binary.resolve()
    report = {'files': args.files, 'workspace_file_limit': 10000,
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'measurements': {}, 'timing': 'single cold workspace request with an immediately queued hover; no timing gate'}
    with tempfile.TemporaryDirectory(prefix='maylsp-navigation-benchmark-') as directory:
        path, _, source = workspace(Path(directory) / 'workspace', args.files)
        doc = {'textDocument': {'uri': path.as_uri()}}
        at = {**doc, 'position': position(source, 'shared'), 'context': {'includeDeclaration': True}}
        client = Client(binary)
        try:
            client.result('initialize', {'rootUri': path.parent.as_uri()})
            client.send('textDocument/didOpen', {'textDocument': {
                'uri': path.as_uri(), 'text': source, 'version': 1, 'languageId': 'maylang'}})
            assert client.result('textDocument/diagnostic', doc)['items'] == []
            for method, params in [('textDocument/references', at),
                                   ('textDocument/rename', {**at, 'newName': 'renamed'}),
                                   ('workspace/symbol', {'query': 'shared'})]:
                start = time.monotonic()
                navigation = client.send(method, params, request=True)
                hover = client.send('textDocument/hover', at, request=True)
                received = {}
                while len(received) < 2:
                    reply = client.receive(timeout=40)
                    if 'id' not in reply: continue
                    assert 'error' not in reply and reply['id'] in (hover, navigation), reply
                    received[reply['id']] = (time.monotonic()-start, reply['result'])
                elapsed, result = received[navigation]
                count = len(result['changes']) if method.endswith('rename') else len(result)
                assert count == (1 if method == 'workspace/symbol' else min(args.files, 10000)), (method, count)
                report['measurements'][method] = {'navigation_ms': round(elapsed*1000, 3),
                    'hover_ms': round(received[hover][0]*1000, 3), 'result_count': count}
                print(method, report['measurements'][method], flush=True)
            client.stop()
        finally:
            if client.process.poll() is None:
                client.process.kill(); client.process.wait()
    args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
