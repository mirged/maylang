#!/usr/bin/env python3
"""Inspect public behavior reports, fixed-point summaries, and failure output."""
import argparse
from collections import deque
import json
import random
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'toolchain/mayc/mayc_new')
    compiler = compiler_binary(parser.parse_args().compiler)
    with tempfile.TemporaryDirectory(prefix='mayc-reports-') as directory:
        work = Path(directory)
        source = work / 'summary.may'
        artifact = work / 'untouched'
        artifact.write_bytes(b'existing output')

        def report(text, options=(), error=None):
            source.write_text(text)
            command = [str(compiler), '--explain-behavior', *options, str(source), '-o', str(artifact)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
            assert artifact.read_bytes() == b'existing output', result
            assert not source.with_suffix('').exists(), result
            if error:
                assert result.returncode != 0 and result.stdout == '' and error in result.stderr, result
                return result
            assert result.returncode == 0 and result.stderr == '', result
            data = json.loads(result.stdout)
            assert data['schema_version'] == 1 and data['scope'] == 'scalar_effects_v1', data
            assert data['analysis_roots'] == 'explicit_contracts', data
            return data

        program = '''fun leaf(n: Int) -> Int { print(n); return time(); }
fun root(n: Int) -> Int ! {output, clock, output} { return leaf(n); }
fun ignored() -> Int { return syscall(39); }
print(999);
'''
        first = report(program)
        assert first == report(program), 'reports must be reproducible'
        entries = {entry['name']: entry for entry in first['functions']}
        assert set(entries) == {'leaf', 'root'}, entries
        for name, entry in entries.items():
            assert entry['file'] == str(source) and entry['classification'] == 'proven', entry
            assert entry['inferred_effects'] == ['clock', 'output'], entry
            assert entry['range']['start']['line'] == (1 if name == 'leaf' else 2), entry
        assert entries['leaf']['declared_effects'] is None, entries
        assert entries['root']['declared_effects'] == ['clock', 'output'], entries
        for options in [(), ('--raw',), ('--runtime', 'core'), ('--target', 'x86_64-windows')]:
            data = report('fun root(x: Int) -> Int ! {} { return x; }', options)
            assert len(data['functions']) == 1, data
            entry = data['functions'][0]
            assert entry['declared_effects'] == entry['inferred_effects'] == [], entry
        data = report('fun unused() -> Int { return syscall(39); } print(999);')
        assert data['functions'] == [], data
        data = report('fun root() -> Int ! {clock, output} { return 42; }')
        assert data['functions'][0]['inferred_effects'] == [], data
        cyclic = '''fun root(n: Int) -> Int ! {output, clock} { return a(n); }
fun a(n: Int) -> Int { if(n>0) { b(n-1); } return time(); }
fun b(n: Int) -> Int { print(n); return a(n); }
'''
        data = report(cyclic)
        assert len(data['functions']) == 3, data
        assert all(entry['inferred_effects'] == ['clock', 'output'] for entry in data['functions']), data
        for invalid, message in [
            ('fun root() -> Int ! {} { return time(); }', 'effect `clock`'),
            ('fun root() -> Int ! {output} { return true; }', 'expected Int'),
            ('fun root() -> Int ! {output} { return absent(); }', 'unresolved or primitive call'),
            ('fun root(x: Int, x: Int) -> Int ! {} { return x; }', 'duplicate binding'),
        ]:
            report(invalid, error=message)
        result = report('fun root() -> Int ! pure { print(1); return 0; }',
                        ('--diagnostics', 'json'), 'MB-EFFECT-001')
        error = json.loads(result.stderr)['diagnostics'][0]
        assert error['file'] == str(source) and 'root -> print' in error['message'], error
        result = report('''fun long_path() -> Int ! {output} { return middle(); }
fun root() -> Int ! pure { return long_path() + short_path(); }
fun middle() -> Int { print(1); return 0; }
fun short_path() -> Int { print(2); return 0; }
''', ('--diagnostics', 'json'), 'call path: root -> short_path -> print]')
        error = json.loads(result.stderr)['diagnostics'][0]
        assert error['range']['start']['line'] == 4, error
        unknown_program = '''let shared: Int = 7;
fun root() -> Int ! {output, clock} { return long_path() + bad(); }
fun long_path() -> Int { return middle(); }
fun middle() -> Int { return bad(); }
fun bad() -> Int { return shared; }
'''
        result = report(unknown_program, ('--diagnostics', 'json'), 'call path: root -> bad]')
        repeated = report(unknown_program, ('--diagnostics', 'json'), 'call path: root -> bad]')
        assert result.stderr == repeated.stderr, 'unknown diagnostics must be reproducible'
        error = json.loads(result.stderr)['diagnostics'][0]
        assert error['range']['start']['line'] == 5 and error['file'] == str(source), error
        report('''fun root() -> Int ! pure { return long_path() + short_path(); }
fun long_path() -> Int { return middle(); }
fun middle() -> Int { return bad(); }
fun short_path() -> Int { return bad(); }
fun bad() -> Int { return syscall(39); }
''', error='call path: root -> short_path -> bad]')
        report('''let shared: Int = 7;
fun root() -> Int ! pure { return a(1) + bad(); }
fun a(n: Int) -> Int { return b(n); }
fun b(n: Int) -> Int { if(n > 0) { return a(n-1); } return bad(); }
fun bad() -> Int { return shared; }
''', error='call path: root -> bad]')
        report('''let shared: Int = 7;
fun root() -> Int ! pure { return first() + second(); }
fun first() -> Int { return bad(); }
fun second() -> Int { return bad(); }
fun bad() -> Int { return shared; }
''', error='call path: root -> first -> bad]')
        # Previously checked contract roots must not lengthen later discovery
        # paths, and a direct unknown operation beats one in a queued helper.
        report('''fun checked() -> Int ! pure { return 1; }
fun root() -> Int ! pure { return helper() + syscall(39); }
fun helper() -> Int { return syscall(39); }
''', error='call path: root]')
        (work / 'unknown.may').write_text(
            'let shared: Int = 7;\npub fun bad() -> Int { return shared; }\n')
        result = report('''import "unknown.may" as d;
fun root() -> Int ! pure { return helper() + d.bad(); }
fun helper() -> Int { return d.bad(); }
''', ('--diagnostics', 'json'), 'call path: root -> bad]')
        error = json.loads(result.stderr)['diagnostics'][0]
        assert error['file'] == str(work / 'unknown.may'), error
        assert error['range']['start']['line'] == 2, error
        for option in ['--dump-expanded', '--dump']:
            report('fun root() -> Int ! pure { return 1; }', (option,), 'cannot be combined')
        (work / 'dep.may').write_text('pub fun leaf(n: Int) -> Int { print(n); return n; }\n')
        data = report('import "dep.may" as d; fun root() -> Int ! {output} { return d.leaf(1); }')
        entries = {entry['name']: entry for entry in data['functions']}
        assert entries['leaf']['file'] == str(work / 'dep.may'), entries
        assert entries['root']['file'] == str(source), entries
        # A reachability oracle is independent of the compiler's fixed-point
        # propagation, and exercises cycles with different discovery orders.
        rng = random.Random(0xB3A710)
        for case in range(12):
            size = rng.randrange(4, 10)
            edges = {i: [j for j in range(size) if rng.random() < 0.25] for i in range(size)}
            direct = {i: {effect for effect in ['clock', 'output']
                          if case and rng.random() < 0.2} for i in range(size)}
            expected = {}
            for start in range(size):
                seen, pending = set(), [start]
                while pending:
                    node = pending.pop()
                    if node not in seen:
                        seen.add(node)
                        pending.extend(edges[node])
                expected[f'g{start}'] = sorted(set().union(*(direct[node] for node in seen)))
            functions = []
            for node in range(size):
                body = ''.join(f'g{callee}();' for callee in edges[node])
                if 'clock' in direct[node]:
                    body += 'time();'
                if 'output' in direct[node]:
                    body += 'print(0);'
                functions.append(f'fun g{node}() -> Int {{ {body} return 0; }}')
            root = ('fun root() -> Int ! {clock, output} {'
                    + ''.join(f'g{node}();' for node in range(size)) + 'return 0; }')
            text = '\n'.join([*functions, root])
            data = report(text)
            actual = {entry['name']: entry['inferred_effects'] for entry in data['functions']}
            expected['root'] = sorted(set().union(*direct.values()))
            assert actual == expected, (case, edges, direct, data, expected)
            if expected['root']:
                report(text.replace('! {clock, output}', '! {}'), error='exceeds declared ceiling []')
        # Independently compute shortest paths to one unknown body in cyclic
        # graphs. Only g0 is a root; declaration order must not select the path.
        for case in range(12):
            size = rng.randrange(4, 10)
            sink = size - 1
            edges = {i: [j for j in range(size) if rng.random() < 0.3]
                     for i in range(sink)}
            edges[sink] = []
            edges[0].append(1)
            edges[1].append(sink)
            pending = deque([[0]])
            seen = {0}
            while pending:
                path = pending.popleft()
                if path[-1] == sink:
                    break
                for target in edges[path[-1]]:
                    if target not in seen:
                        seen.add(target)
                        pending.append([*path, target])
            expected_path = ' -> '.join(f'g{node}' for node in path)
            functions = []
            for node in range(size):
                body = ''.join(f'g{callee}();' for callee in edges[node])
                body += 'return shared;' if node == sink else 'return 0;'
                contract = ' ! {clock, output}' if node == 0 else ''
                functions.append(f'fun g{node}() -> Int{contract} {{ {body} }}')
            rng.shuffle(functions)
            report('let shared: Int = 7;\n' + '\n'.join(functions),
                   error=f'call path: {expected_path}]')
    print('behavior reports: passed')


if __name__ == '__main__':
    main()
