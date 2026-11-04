#!/usr/bin/env python3
"""Measure incoming calls and references on a generated workspace of callers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time

from test_lsp import Client


def tree_rss_kib(pid):
    """Resident memory of a process and all its descendants, in KiB."""
    total = 0
    stack = [pid]
    while stack:
        current = stack.pop()
        try:
            for line in Path(f'/proc/{current}/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    total += int(line.split()[1])
            for task in os.listdir(f'/proc/{current}/task'):
                stack += [int(child) for child in Path(f'/proc/{current}/task/{task}/children').read_text().split()]
        except OSError:
            pass
    return total


def workspace(folder, files, functions):
    folder.mkdir()
    library = folder / 'library.may'
    library.write_text('pub fun shared() -> Int { return 1; }\n')
    for index in range(files):
        body = '\n'.join(f'fun f{index}_{k}(x: Int) -> Int {{ let y: Int = x * {k} + 0; return y + shared(); }}'
                         for k in range(functions))
        (folder / f'm{index:05}.may').write_text('import "library";\n' + body + '\n')
    return library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--files', type=int, default=3000)
    parser.add_argument('--functions', type=int, default=4, help='calling functions per file')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    assert 1 <= args.files * args.functions and args.files < 10000
    binary = args.binary.resolve()
    expected = args.files * args.functions
    report = {'files': args.files, 'functions_per_file': args.functions, 'samples': args.samples,
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'timing': 'fresh server per sample; peak RSS covers the server and its workers; no timing gate',
              'measurements': {}}
    samples = {'callHierarchy/incomingCalls': [], 'textDocument/references': []}
    with tempfile.TemporaryDirectory(prefix='maylsp-call-hierarchy-benchmark-') as directory:
        library = workspace(Path(directory) / 'workspace', args.files, args.functions)
        doc = {'textDocument': {'uri': library.as_uri()}}
        at = {**doc, 'position': {'line': 0, 'character': 9}}
        for _ in range(args.samples):
            for method in samples:
                client = Client(binary)
                peak = [0]
                done = threading.Event()

                def poll():
                    while not done.is_set():
                        peak[0] = max(peak[0], tree_rss_kib(client.process.pid))
                        time.sleep(0.02)
                try:
                    client.result('initialize', {'rootUri': library.parent.as_uri()})
                    items = client.result('textDocument/prepareCallHierarchy', at)
                    params = ({'item': items[0]} if method.startswith('callHierarchy')
                              else {**at, 'context': {'includeDeclaration': False}})
                    sampler = threading.Thread(target=poll)
                    sampler.start()
                    start = time.monotonic()
                    reply = client.request(method, params)
                    elapsed = time.monotonic() - start
                    done.set()
                    sampler.join()
                    assert 'error' not in reply, reply
                    count = (sum(len(group['fromRanges']) for group in reply['result'])
                             if method.startswith('callHierarchy') else len(reply['result']))
                    assert count == expected, (method, count, expected)
                    samples[method].append({'seconds': round(elapsed, 3), 'peak_rss_mib': round(peak[0] / 1024, 1)})
                    client.stop()
                finally:
                    done.set()
                    if client.process.poll() is None:
                        client.process.kill()
                        client.process.wait()
    for method, values in samples.items():
        report['measurements'][method] = {
            'median_seconds': statistics.median(v['seconds'] for v in values),
            'median_peak_rss_mib': statistics.median(v['peak_rss_mib'] for v in values),
            'result_count': expected, 'samples': values}
        print(method, report['measurements'][method]['median_seconds'], 's',
              report['measurements'][method]['median_peak_rss_mib'], 'MiB', flush=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
