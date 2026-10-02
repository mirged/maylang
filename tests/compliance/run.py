#!/usr/bin/env python3
"""Run self-hosted Maylang compliance checks; return nonzero on regressions."""
from pathlib import Path
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
(HERE / 'build').mkdir(exist_ok=True)
for script in ('cases_core.py', 'cases_extended.py', 'cases_boundaries.py'):
    result = subprocess.run([sys.executable, str(HERE / script)])
    if result.returncode:
        raise SystemExit(result.returncode)
results = []
for name in ('results.json', 'round2.json', 'followup.json'):
    results.extend(json.loads((HERE / name).read_text()))
report = {
    'compiler': __import__('os').environ.get('MAYC', 'toolchain/mayc/mayc_new'),
    'passed': sum(r['passed'] is True for r in results),
    'failed': sum(r['passed'] is False for r in results),
    'observations': sum(r['passed'] is None for r in results),
    'results': results,
}
(HERE / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(f"{report['passed']} passed, {report['failed']} failed, {report['observations']} observations")
raise SystemExit(bool(report['failed']))
