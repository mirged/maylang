"""Workspace diagnostic protocol and worker lifecycle checks."""
import os
import signal
import time
from pathlib import Path

from test_lsp import Client


def run_workspace_diagnostics(binary, work):
    folder = work / 'workspace-diagnostics'
    folder.mkdir()
    library = folder / 'library.may'
    library.write_text('pub fun answer(value: Int) -> Int { return value; }\n')
    source = folder / 'main.may'
    text = 'import "library";\nlet value: Int = answer(1);\nprint(value);\n'
    source.write_text(text)
    bad = folder / 'broken.may'
    bad.write_text('print(missing);\n')
    client = Client(binary)
    early_replies = {}

    def pull(previous=(), **params):
        return client.result('workspace/diagnostic', {
            'identifier': 'maylsp', 'previousResultIds': list(previous), **params})

    def by_uri(result):
        reports = result['items']
        assert len({r['uri'] for r in reports}) == len(reports), result
        return {r['uri']: r for r in reports}

    def previous(result):
        return [{'uri': r['uri'], 'value': r['resultId']} for r in result['items'] if 'resultId' in r]

    def replies(ids):
        result = {ident: early_replies.pop(ident) for ident in ids if ident in early_replies}
        while set(result) != ids:
            message = client.receive()
            if 'id' in message:
                assert message['id'] in ids and message['id'] not in result, message
                result[message['id']] = message
            else:
                client.notifications.append(message)
        return result

    def open_doc(path, content, version=1):
        client.send('textDocument/didOpen', {'textDocument': {
            'uri': path.as_uri(), 'languageId': 'maylang', 'version': version, 'text': content}})

    def hover_barrier(pending, early_ids=()):
        hover = client.send('textDocument/hover', {'textDocument': {'uri': source.as_uri()},
            'position': {'line': 1, 'character': 18}}, request=True)
        while True:
            message = client.receive()
            if 'id' not in message:
                client.notifications.append(message)
                continue
            if message['id'] in early_ids:
                assert message['id'] not in early_replies, message
                early_replies[message['id']] = message
                continue
            assert message['id'] == hover, ('workspace pull blocked hover', pending, message)
            assert message.get('result'), message
            return

    def children():
        pid = client.process.pid
        return [int(p) for p in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]

    try:
        initialized = client.result('initialize', {'rootUri': folder.as_uri(),
            'initializationOptions': {'strict': True},
            'capabilities': {'textDocument': {'diagnostic': {'relatedDocumentSupport': True}},
                             'window': {'workDoneProgress': True}}})
        assert initialized['capabilities']['diagnosticProvider']['workspaceDiagnostics'] is True
        for invalid in ({}, {'previousResultIds': 42}, {'previousResultIds': [{'uri': source.as_uri(), 'value': 42}]},
                        {'previousResultIds': [], 'identifier': 'other'},
                        {'previousResultIds': [], 'partialResultToken': []}):
            assert client.request('workspace/diagnostic', invalid)['error']['code'] == -32602
        first = pull(workDoneToken='check')
        reports = by_uri(first)
        assert set(reports) == {source.as_uri(), library.as_uri(), bad.as_uri()}, reports
        assert all(r['kind'] == 'full' and r['version'] is None and r['resultId'] for r in reports.values())
        assert reports[source.as_uri()]['items'] == [] and reports[library.as_uri()]['items'] == []
        assert 'missing' in reports[bad.as_uri()]['items'][0]['message']
        progress = [n['params']['value'] for n in client.notifications
                    if n.get('method') == '$/progress' and n['params']['token'] == 'check']
        assert progress[0]['kind'] == 'begin' and progress[-1]['kind'] == 'end'
        assert any(p.get('percentage') == 100 for p in progress)
        same = pull(previous(first))
        assert all(r['kind'] == 'unchanged' and 'items' not in r for r in same['items']), same
        assert {r['uri']: r['resultId'] for r in first['items']} == {r['uri']: r['resultId'] for r in same['items']}
        assert all(r['kind'] == 'full' for r in pull([{'uri': source.as_uri(), 'value': 'unknown'}])['items'])
        client.notifications = []
        assert pull(previous(first), partialResultToken=7)['items'] == []
        partials = [r for n in client.notifications if n.get('method') == '$/progress'
                    and n['params']['token'] == 7 for r in n['params']['value']['items']]
        assert by_uri({'items': partials}) == by_uri(same)

        # The importing file stays unopened. Its check must see the dirty library.
        dirty = 'pub fun answer(value: Str) -> Int { return 1; }\n'
        open_doc(library, dirty, version=3)
        changed = pull(previous(first))
        reports = by_uri(changed)
        assert reports[library.as_uri()]['version'] == 3
        assert reports[source.as_uri()]['kind'] == 'full'
        assert 'expected Str' in reports[source.as_uri()]['items'][0]['message'], reports
        # Disk changes and deletion notifications cannot overwrite an open buffer.
        library.write_text('print(disk_only_error);\n')
        client.send('workspace/didChangeWatchedFiles', {'changes': [{'uri': library.as_uri(), 'type': 2}]})
        assert 'expected Str' in by_uri(pull())[source.as_uri()]['items'][0]['message']
        library.write_text('pub fun answer(value: Int) -> Int { return value; }\n')
        client.send('textDocument/didClose', {'textDocument': {'uri': library.as_uri()}})
        assert by_uri(pull())[source.as_uri()]['items'] == []
        bad.unlink()
        client.send('workspace/didChangeWatchedFiles', {'changes': [{'uri': bad.as_uri(), 'type': 3}]})
        cleared = by_uri(pull(previous(changed)))[bad.as_uri()]
        assert cleared == {'uri': bad.as_uri(), 'version': None, 'kind': 'full', 'items': []}, cleared
        added = folder / 'added.may'
        added.write_text('print(new_error);\n')
        client.send('workspace/didChangeWatchedFiles', {'changes': [{'uri': added.as_uri(), 'type': 1}]})
        assert by_uri(pull())[added.as_uri()]['items']
        other = work / 'other-diagnostic-root'
        other.mkdir()
        extra = other / 'extra.may'
        extra.write_text('print(other_error);\n')
        client.send('workspace/didChangeWorkspaceFolders', {'event': {
            'added': [{'uri': other.as_uri(), 'name': 'other'}], 'removed': []}})
        multiple = pull()
        assert by_uri(multiple)[extra.as_uri()]['items']
        client.send('workspace/didChangeWorkspaceFolders', {'event': {
            'added': [], 'removed': [{'uri': other.as_uri(), 'name': 'other'}]}})
        assert by_uri(pull(previous(multiple)))[extra.as_uri()] == {
            'uri': extra.as_uri(), 'version': None, 'kind': 'full', 'items': []}

        # A long scan allows deterministic active/queued cancellation and edits.
        for i in range(256):
            (folder / f'check{i:03}.may').write_text(f'let value{i}: Int = {i};\nprint(value{i});\n')
        open_doc(source, text)
        client.result('textDocument/diagnostic', {'textDocument': {'uri': source.as_uri()}})
        pending = client.send('workspace/diagnostic', {'previousResultIds': [],
            'workDoneToken': 'cancel', 'partialResultToken': 'partial'}, request=True)
        hover_barrier(pending)
        worker_pids = children()
        assert len(worker_pids) == 1, worker_pids
        os.kill(worker_pids[0], signal.SIGSTOP)
        individual = client.result('textDocument/diagnostic', {
            'textDocument': {'uri': (folder / 'check000.may').as_uri()}})
        assert individual['items'] == [], individual
        queued = client.send('workspace/diagnostic', {'previousResultIds': []}, request=True)
        client.send('$/cancelRequest', {'id': queued})
        assert replies({queued})[queued]['error']['code'] == -32800
        client.send('window/workDoneProgress/cancel', {'token': 'cancel'})
        assert replies({pending})[pending]['error']['code'] == -32800
        assert all(not Path(f'/proc/{pid}').exists() for pid in worker_pids)
        ends = [n for n in client.notifications if n.get('method') == '$/progress'
                and n['params']['token'] == 'cancel' and n['params']['value']['kind'] == 'end']
        assert len(ends) == 1, ends
        pending = client.send('workspace/diagnostic', {'previousResultIds': []}, request=True)
        hover_barrier(pending)
        client.send('textDocument/didChange', {'textDocument': {'uri': source.as_uri(), 'version': 2},
            'contentChanges': [{'text': text + 'print(latest_error);\n'}]})
        assert replies({pending})[pending]['error']['code'] == -32802
        retry = pull()
        assert all(r['items'] == [] for r in retry['items'] if '/check' in r['uri']), retry
        assert by_uri(retry)[source.as_uri()]['version'] == 2
        assert 'latest_error' in by_uri(retry)[source.as_uri()]['items'][0]['message']
        pending = client.send('workspace/diagnostic', {'previousResultIds': []}, request=True)
        hover_barrier(pending)
        worker = children()
        assert len(worker) == 1, worker
        os.kill(worker[0], signal.SIGSTOP)
        descriptor = os.open(f'/proc/{worker[0]}/fd/1', os.O_WRONLY)
        try:
            os.write(descriptor, b'out of memory\n')
        finally:
            os.close(descriptor)
        os.kill(worker[0], signal.SIGKILL)
        assert replies({pending})[pending]['error']['code'] == -32803
        assert by_uri(pull(previous(retry)))[source.as_uri()]['kind'] == 'unchanged'
        pending = client.send('workspace/diagnostic', {'previousResultIds': []}, request=True)
        hover_barrier(pending)
        active = children()
        assert len(active) == 1, active
        os.kill(active[0], signal.SIGSTOP)
        ids = {pending}
        for _ in range(12):
            ids.add(client.send('workspace/diagnostic', {'previousResultIds': []}, request=True))
        hover_barrier(pending, early_ids=ids)
        shutdown = client.send('shutdown', request=True)
        result = replies(ids | {shutdown})
        assert result[shutdown]['result'] is None
        assert sum(r.get('error', {}).get('code') == -32803 for r in result.values()) == 4
        assert sum(r.get('error', {}).get('code') == -32800 for r in result.values()) == 9
        client.send('exit'); client.process.wait(timeout=5)
        assert client.process.returncode == 0 and not client.process.stderr.read()
        assert all(not Path(f'/proc/{pid}').exists() for pid in active)
        print('PASS workspace diagnostics: unopened files, IDs, progress, dirty imports, deletion, folders, cancellation, stale results and bounded workers', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()
