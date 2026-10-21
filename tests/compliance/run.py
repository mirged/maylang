#!/usr/bin/env python3
"""Run self-hosted Maylang compliance checks; return nonzero on regressions."""
import json

from common import COMPILER, REPORTS, run_cases
import cases_boundaries
import cases_core
import cases_extended

cases, fixtures = {}, {}
for module in (cases_core, cases_extended, cases_boundaries):
    duplicate = cases.keys() & module.CASES.keys()
    assert not duplicate, f'{module.__name__} redefines {sorted(duplicate)}'
    cases.update(module.CASES)
    fixtures.update(getattr(module, 'FIXTURES', {}))
results = run_cases(cases, fixtures)
report = {
    'compiler': str(COMPILER),
    'passed': sum(r['passed'] for r in results),
    'failed': sum(not r['passed'] for r in results),
    'results': results,
}
REPORTS.mkdir(parents=True, exist_ok=True)
(REPORTS / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(f"{report['passed']} passed, {report['failed']} failed")
raise SystemExit(bool(report['failed']))
