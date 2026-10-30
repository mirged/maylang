#!/usr/bin/env python3
"""Inspect real IR snapshots after frontend release and source-row mutation."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from backends import ROOT, compiler_binary


INSPECT = '''let originals: Any = [];
        for original: Any in FUNC_HEAD {
            if (original.behaviorSummary != nil) { push(originals, original); }
        }
        ir_program(ctx);
        for original: Any in originals {
            push(original.behaviorSummary.effects, "poison");
            original.behaviorSummary.classification = "changed";
            if (original.behaviorContract == true) { push(original.behaviorEffects, "poison"); }
        }
        let summaries: Any = [];
        let signatures: Any = {};
        let typed_ir: Any = {};
        let unknown: Any = [];
        let parameter_rows: Any = {};
        for emitted: Any in ctx.functions {
            if (emitted.behaviorSummary != nil) { push(summaries, emitted.behaviorSummary); }
            if (emitted.strictSignature != nil) {
                let parameters: Any = [];
                for parameter: Any in emitted.strictSignature.arguments { push(parameters, parameter.name); }
                signatures[symbol_name(emitted.p, emitted.l)] = {
                    "parameters": parameters, "result": emitted.strictSignature.result.name
                };
            }
            let operations: Any = [];
            for instruction: Any in emitted.ir.code {
                if (instruction.op == E_BIN) {
                    push(operations, [
                        instruction.extra.left.valueType.name,
                        instruction.extra.right.valueType.name,
                        instruction.result.valueType.name
                    ]);
                }
            }
            if (len(operations) != 0) { typed_ir[symbol_name(emitted.p, emitted.l)] = operations; }
            let rows: Any = [];
            for parameter: Any in emitted.parr {
                if (parameter.annotation.name == "Function" and parameter.annotation.behaviorEffects != nil) {
                    push(rows, parameter.annotation.behaviorEffects);
                }
            }
            if (len(rows) != 0) { parameter_rows[symbol_name(emitted.p, emitted.l)] = rows; }
            if (ends_with(symbol_name(emitted.p, emitted.l), "::hidden")) {
                push(unknown, emitted.behaviorSummary ?? nil);
            }
        }
        print(json_stringify({"summaries": summaries, "signatures": signatures, "unknown": unknown,
            "typed_ir": typed_ir, "parameter_rows": parameter_rows,
            "frontend_released": len(FUNC_HEAD) == 0 and MAINBODY == 0 and RUNTIME_BODY == 0}));
        syscall(60, 0);'''


def run(command):
    return subprocess.run([str(arg) for arg in command], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT / 'compiler/mayc/mayc_new')
    compiler = compiler_binary(parser.parse_args().compiler)
    mayc = ROOT / 'compiler/mayc'
    with tempfile.TemporaryDirectory(prefix='mayc-behavior-ir-') as directory:
        work = Path(directory)
        # Instrument the actual driver at its IR boundary, retaining its real
        # parsing, effect/type/name checking and lowering paths. The inserted
        # inspection exits before machine-code emission or output replacement.
        text = (mayc / 'main.may').read_text()
        assert text.count('ir_program(ctx);') == 2
        text = text.replace('import "src/', f'import "{mayc}/src/')
        text = text.replace('ir_program(ctx);', INSPECT)
        driver_source = work / 'inspect.may'
        driver_source.write_text(text)
        driver = work / 'inspect'
        result = run([compiler, driver_source, '-o', driver])
        assert result.returncode == 0, result
        for name in ['runtime.may', 'native.may', 'runtime']:
            (work / name).symlink_to(mayc / name)
        (work / 'prelude.may').symlink_to(ROOT / 'stdlib/prelude.may')

        source = work / 'program.may'
        artifact = work / 'preserved'
        artifact.write_bytes(b'keep')

        def inspect(program, options=(), *, scope='scalar_effects_v1', parameter_rows=None):
            source.write_text(program)
            result = run([driver, *options, source, '-o', artifact])
            assert result.returncode == 0 and not result.stderr, result
            assert artifact.read_bytes() == b'keep'
            data = json.loads(result.stdout)
            assert data['frontend_released'] and data['unknown'] == [None], data
            assert data['parameter_rows'] == (parameter_rows or {}), data
            entries = {entry['name']: entry for entry in data['summaries']}
            for name, entry in entries.items():
                assert entry['symbol'] == f'{source}::{name}', entry
                assert entry['schema_version'] == 1 and entry['scope'] == scope, entry
                assert entry['classification'] == 'proven', entry
                assert 'poison' not in entry['inferred_effects'], entry
                assert 'poison' not in (entry['declared_effects'] or []), entry
            return entries

        program = '''fun leaf(n: Int) -> Int { return n + 1; }
fun log() -> Int { print(time()); return 1; }
fun root() -> Int ! {output, clock} { return log() + leaf(41); }
fun unused() -> Int ! pure { return 0; }
fun hidden() -> Int { return 0; }
root(); hidden();
'''
        first = inspect(program)
        assert first == inspect(program), 'IR metadata must be reproducible'
        assert set(first) == {'leaf', 'log', 'root'}, first
        result = run([driver, source, '-o', artifact])
        snapshot = json.loads(result.stdout)
        signatures = snapshot['signatures']
        assert signatures[f'{source}::leaf'] == {'parameters': ['Int'], 'result': 'Int'}, signatures
        assert signatures[f'{source}::log'] == {'parameters': [], 'result': 'Int'}, signatures
        assert signatures[f'{source}::root'] == {'parameters': [], 'result': 'Int'}, signatures
        assert snapshot['typed_ir'][f'{source}::leaf'] == [['Int', 'Int', 'Int']], snapshot
        assert first['root']['declared_effects'] == ['clock', 'output'], first
        assert first['log']['inferred_effects'] == first['root']['inferred_effects'] == ['clock', 'output'], first
        assert first['leaf']['inferred_effects'] == [], first
        assert first['leaf']['declared_effects'] is first['log']['declared_effects'] is None, first
        raw = inspect('fun leaf(n: Int) -> Int { return n * 2; } '
            'fun root() -> Int ! pure { return leaf(21); } '
            'fun hidden() -> Int { return 0; } root(); hidden();', ('--raw',))
        assert set(raw) == {'leaf', 'root'}, raw
        assert raw['root']['declared_effects'] == raw['root']['inferred_effects'] == [], raw
        assert inspect('fun hidden() -> Int { return 0; } hidden();') == {}
        callbacks = inspect('fun root(f: Fn() -> Int ! {output}) -> Int ! {output} { return f(); } '
            'fun noisy() -> Int { print(1); return 1; } '
            'fun hidden() -> Int { return syscall(39); } root(noisy); hidden();',
            scope='scalar_callable_effects_v1', parameter_rows={f'{source}::root': [['output']]})
        assert set(callbacks) == {'root', 'noisy'}, callbacks
        assert callbacks['root']['declared_effects'] == callbacks['root']['inferred_effects'] == ['output'], callbacks
        source.write_text('fun root() -> Int ! pure { print(1); return 0; } root();')
        result = run([driver, source, '-o', artifact])
        assert result.returncode != 0 and not result.stdout and 'MB-EFFECT-001' in result.stderr, result
        assert artifact.read_bytes() == b'keep'
    print('behavior IR snapshots: passed')


if __name__ == '__main__':
    main()
