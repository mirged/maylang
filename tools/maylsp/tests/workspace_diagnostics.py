"""Workspace diagnostic protocol and worker lifecycle checks."""
import os
import signal
import time
from pathlib import Path

from test_lsp import Client


def run_workspace_cache_directories(binary, work):
    folder = work / 'workspace-cache-directories'
    folder.mkdir()
    source = folder / 'main.may'
    source.write_text('print(1);\n')
    cache = folder / '.may/store'
    cache.mkdir(parents=True)
    (cache / 'generated.may').write_text('not valid Maylang')
    dotted = folder / 'sources.may'
    dotted.mkdir()
    nested = dotted / 'nested.may'
    nested.write_text('let value: Int = "wrong";\n')
    client = Client(binary)
    try:
        client.result('initialize', {'rootUri': folder.as_uri()})
        client.send('workspace/didCreateFiles', {'files': [{'uri': (folder / '.may').as_uri()}]})
        result = client.result('workspace/diagnostic', {'previousResultIds': []})
        reports = {row['uri']: row for row in result['items']}
        assert set(reports) == {source.as_uri(), nested.as_uri()}, reports
        assert not reports[source.as_uri()]['items'] and reports[nested.as_uri()]['items'], reports
        symbols = client.result('workspace/symbol', {'query': 'value'})
        assert any(row['location']['uri'] == nested.as_uri() for row in symbols), symbols
        rejected = client.request('textDocument/hover', {'textDocument': {'uri': dotted.as_uri()},
                                                       'position': {'line': 0, 'character': 0}})
        assert rejected['error']['code'] == -32602 and rejected['error']['message'] == 'document not found', rejected
        client.stop()
        assert not client.process.stderr.read()
        print('PASS .may build-cache exclusion and source directories ending in .may', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()


def run_workspace_memory(binary, work):
    # A fixed 32-entry worker used to combine 4,800 typed functions into one
    # AST, exhaust its heap, then parse the fatal stdout as a JSON number.
    folder = work / 'diagnostic-heavy-imports'
    folder.mkdir()
    for module in range(12):
        (folder / f'lib{module}.may').write_text('\n'.join(
            f'pub fun function_{module}_{i}(value: Int) -> Int {{ return value + {i}; }}'
            for i in range(400)))
        (folder / f'app{module}.may').write_text(
            f'import "lib{module}.may" as lib;\nprint(lib.function_{module}_0(42));\n')
    client = Client(binary)
    try:
        client.result('initialize', {'rootUri': folder.as_uri(),
                                     'initializationOptions': {'strict': True}})
        pending = client.send('workspace/diagnostic', {'previousResultIds': [],
                              'partialResultToken': 'heavy'}, request=True)
        reports = {}
        while True:
            message = client.receive(timeout=120)
            if message.get('method') == '$/progress' and message['params']['token'] == 'heavy':
                for report in message['params']['value']['items']:
                    assert report['uri'] not in reports, report
                    assert report['kind'] == 'full' and not report['items'], report
                    reports[report['uri']] = report
            if message.get('id') == pending:
                assert message.get('result') == {'items': []}, message
                break
        assert len(reports) == 24, len(reports)
        previous = [{'uri': uri, 'value': item['resultId']} for uri, item in reports.items()]
        unchanged = client.result('workspace/diagnostic', {'previousResultIds': previous})
        assert len(unchanged['items']) == 24 and all(row['kind'] == 'unchanged' for row in unchanged['items'])
        client.stop()
        assert not client.process.stderr.read()
        print('PASS imported workspace memory bounds: 4,800 functions, complete reports and cached reuse', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()


def run_large_diagnostic_frames(binary, work):
    folder = work / 'diagnostic-frames'
    folder.mkdir()
    (folder / 'main.may').write_text('print(1);\n')
    client = Client(binary)
    try:
        client.result('initialize', {'rootUri': folder.as_uri()})
        first = client.result('workspace/diagnostic', {'previousResultIds': []})
        # A legal near-limit frame must not materialize one list element per
        # byte before parsing it. Follow it with another pull to check recovery.
        response = client.request('unknown/method', {'blob': 'x' * (15 * 1024 * 1024)})
        assert response['error']['code'] == -32601, response
        same = client.result('workspace/diagnostic', {'previousResultIds': [
            {'uri': r['uri'], 'value': r['resultId']} for r in first['items']]})
        assert same['items'][0]['kind'] == 'unchanged', same
        client.stop()
        print('PASS near-limit JSON frames and subsequent diagnostic pulls', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()


def run_diagnostic_restart(binary, work):
    folder = work / 'diagnostic-restart'
    folder.mkdir()
    source = folder / 'main.may'
    source.write_text('print(1);\n')
    doc = {'textDocument': {'uri': source.as_uri()}}
    document_id = None
    previous = []
    for iteration in range(2):
        client = Client(binary)
        try:
            client.result('initialize', {'rootUri': folder.as_uri()})
            document = client.result('textDocument/diagnostic', {**doc, 'previousResultId': document_id})
            workspace = client.result('workspace/diagnostic', {'previousResultIds': previous})
            assert document['kind'] == 'full' and workspace['items'][0]['kind'] == 'full'
            if iteration:
                assert document['resultId'] != document_id
                assert workspace['items'][0]['resultId'] != previous[0]['value']
                assert document['items'] and workspace['items'][0]['items']
            document_id = document['resultId']
            previous = [{'uri': source.as_uri(), 'value': workspace['items'][0]['resultId']}]
            client.stop()
        finally:
            if client.process.poll() is None:
                client.process.kill(); client.process.wait()
        source.write_text('print(changed_on_disk);\n')
    print('PASS diagnostic IDs invalidate across server restarts and disk changes', flush=True)


def run_workspace_batch_errors(binary, work):
    folder = work / 'workspace-batch-errors'
    folder.mkdir()
    for i in range(40):
        (folder / f'bad{i:02}.may').write_text('print(missing);\n' if i % 2 else 'let value = "unterminated\n')
    clean = folder / 'clean.may'
    clean.write_text('let value: Int = 1;\nprint(value);\n')
    library = folder / 'library.may'
    library.write_text('pub fun answer() -> Int { return 1; }\n')
    isolated = folder / 'isolated.may'
    isolated.write_text('print(answer());\n')
    client = Client(binary)
    try:
        client.result('initialize', {'rootUri': folder.as_uri(), 'initializationOptions': {'strict': True}})
        result = client.result('workspace/diagnostic', {'previousResultIds': []})
        reports = {r['uri']: r for r in result['items']}
        assert len(reports) == 43, len(reports)
        assert reports[clean.as_uri()]['items'] == [] and reports[library.as_uri()]['items'] == []
        assert all(reports[(folder / f'bad{i:02}.may').as_uri()]['items'] for i in range(40))
        assert 'answer' in reports[isolated.as_uri()]['items'][0]['message'], reports[isolated.as_uri()]
        client.stop()
        print('PASS workspace batch error isolation, recovery limits and module visibility', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()


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
        unicode_id = client.request('workspace/diagnostic', {'previousResultIds': previous(first)}, identifier='workspace-🚀')
        assert all(r['kind'] == 'unchanged' for r in unicode_id['result']['items']), unicode_id
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
        library.unlink()
        client.send('workspace/didChangeWatchedFiles', {'changes': [{'uri': library.as_uri(), 'type': 3}]})
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
        failure = replies({pending})[pending]['error']
        assert failure['code'] == -32803 and 'signal 9' in failure['message'], failure
        assert 'invalid JSON' not in failure['message'], failure
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
        assert client.process.returncode == 0 and client.process.stderr.read() == b'out of memory\n'
        assert all(not Path(f'/proc/{pid}').exists() for pid in active)
        print('PASS workspace diagnostics: unopened files, IDs, progress, dirty imports, deletion, folders, cancellation, stale results and bounded workers', flush=True)
    finally:
        if client.process.poll() is None:
            client.process.kill(); client.process.wait()
