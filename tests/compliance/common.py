"""Shared runner for self-hosted compiler compliance cases."""
from pathlib import Path
import json
import os
import resource
import subprocess

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
COMPILER = Path(os.environ.get('MAYC', str(ROOT / 'toolchain/mayc/mayc_new')))
REJECT = {
    'missing_expr', 'missing_brace', 'dangling_operator', 'huge_literal',
    'return_top', 'module_private', 'duplicate_params', 'module_shared_name',
    'module_selective_hidden', 'integer_positive_overflow', 'integer_negative_overflow',
}

def limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2))

def run(args, timeout):
    try:
        result = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True,
                                timeout=timeout, preexec_fn=limits)
        return {'exit': result.returncode,
                'stdout': result.stdout.decode(errors='replace')[:4000],
                'stdout_hex': result.stdout.hex()[:8000],
                'stderr': result.stderr.decode(errors='replace')[:4000]}
    except subprocess.TimeoutExpired:
        return {'timeout': timeout}

def run_cases(cases, report_name):
    (WORK / 'build').mkdir(exist_ok=True)
    results = []
    for name, (source, expected) in cases.items():
        path = WORK / (name + '.may')
        path.write_text(source + '\n')
        binary = WORK / 'build' / name
        binary.unlink(missing_ok=True)
        # This suite tests legacy runtime faults and coercions deliberately.
        # Strict compile-time contracts have their own default-mode suite.
        compiled = run([COMPILER, '--legacy', path, '-o', binary], 30)
        executed = None
        if name in REJECT:
            passed = compiled.get('exit', 0) > 0 and not binary.exists() and bool(compiled.get('stderr'))
        elif compiled.get('exit') == 0:
            executed = run([binary], 3)
            passed = executed.get('exit') == 0 and executed.get('stdout_hex') == expected.encode().hex()
        else:
            passed = False
        results.append({'name': name, 'expected': 'compile error' if name in REJECT else expected,
                        'compile': compiled, 'run': executed, 'passed': passed})
        print(f"{'PASS' if passed else 'FAIL'} {name}" +
              ('' if passed else ': ' + json.dumps(executed or compiled, ensure_ascii=False)), flush=True)
    (WORK / report_name).write_text(json.dumps(results, indent=2, ensure_ascii=False) + '\n')
