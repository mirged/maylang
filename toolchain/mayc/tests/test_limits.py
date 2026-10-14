#!/usr/bin/env python3
"""Independent oracles and subprocess/failure behavior of the limits runner."""
from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import limits


class LimitsTests(unittest.TestCase):
    def test_periodic_oracles_match_naive_workloads(self):
        for count in (1, 7, 17, 1023, 1024, 2051):
            for seed in (0, 1, 42):
                calls = sum(sum((j + 1) * (((i + seed) % 1024) + j) for j in range(8)) for i in range(count))
                self.assertEqual(limits.oracle('calls', count, seed, 0), calls)
                collections = sum(2 * ((i + seed) % 1024) + 10 + i % 17 for i in range(count))
                self.assertEqual(limits.oracle('collections', count, seed, 0), collections)
        count = 1048576 + 13
        value, expected = 42, 0
        for _ in range(count):
            value = (value * 17 + 23) % 1048576
            signed = value - 524288
            quotient = abs(signed) // 8 * (-1 if signed < 0 else 1)
            expected += quotient + signed - quotient * 8
        self.assertEqual(limits.oracle('arithmetic', count, 42, 0), expected)

    def test_signed_remainder_contract(self):
        rng = random.Random(1)
        for _ in range(1000):
            value, divisor = rng.randrange(-(1 << 60), 1 << 60), rng.choice([1, 2, 8, 1024, -2])
            quotient = limits.trunc_div(value, divisor)
            remainder = value - quotient * divisor
            self.assertLess(abs(remainder), abs(divisor))
            self.assertTrue(remainder == 0 or (remainder < 0) == (value < 0))

    def test_timeout_and_errors_retain_logs_and_usage(self):
        args = SimpleNamespace(timeout=.1, memory_mib=512, cpu=None)
        with tempfile.TemporaryDirectory(prefix='limits-runner-test-') as temporary:
            directory = Path(temporary)
            result = limits.execute([sys.executable, '-c', 'while True: pass'], directory, 'timeout', args)
            self.assertEqual(result['category'], 'timeout')
            self.assertLess(result['exit'], 0)
            self.assertTrue(Path(result['stdout']).is_file())
            self.assertTrue((directory / 'timeout.json').is_file())
            self.assertGreater(result['peak_rss_kib'], 0)
            result = limits.execute([sys.executable, '-c', 'import sys; print("fixture", file=sys.stderr); sys.exit(70)'],
                                    directory, 'failure', args, timeout=10)
            self.assertEqual(result['exit'], 70)
            self.assertEqual(result['category'], 'exited')
            with self.assertRaises(ValueError):
                limits.require_run(result)
            self.assertEqual(Path(result['stderr']).read_text(), 'fixture\n')

    def test_runtime_instrumentation_rejects_changed_anchors(self):
        with patch.object(Path, 'read_text', return_value='different runtime'):
            with self.assertRaisesRegex(ValueError, 'anchor changed'):
                limits.instrument_runtime(4)


if __name__ == '__main__':
    unittest.main()
