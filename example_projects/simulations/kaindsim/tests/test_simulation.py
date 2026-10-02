#!/usr/bin/env python3
"""Black-box checks of the native program, exported ledger and replay controls."""
import csv
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path("kaindsim").resolve()


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kaindsim-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_sim(self, name, *options):
        prefix = self.root / name
        result = subprocess.run([str(BINARY), *options, "--out", str(prefix)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(prefix.with_suffix(".json").read_text()), prefix

    def assert_ledger(self, data):
        self.assertEqual(len(data["cells"]), 96)
        for run in data["runs"]:
            frames, ledger = run["frames"], run["ledger"]
            self.assertEqual(len(frames), data["steps"] + 1)
            cumulative_damage = 0
            pumped = 0
            for tick, frame in enumerate(frames):
                self.assertEqual(frame["tick"], tick)
                self.assertEqual(len(frame["water"]), 96)
                self.assertTrue(all(type(w) is int and w >= 0 for w in frame["water"]))
                self.assertEqual(frame["stored"], sum(frame["water"]))
                self.assertEqual(frame["balance"], 0)
                exposure = sum(c["people"] for c, w in zip(data["cells"], frame["water"]) if w > 8)
                self.assertEqual(frame["exposed"], exposure)
                cumulative_damage += sum(max(0, w - 8) * c["people"]
                                         for c, w in zip(data["cells"], frame["water"]))
                self.assertEqual(frame["damage"], cumulative_damage)
                self.assertLessEqual(frame["pumped"] - pumped, data["budget"])
                self.assertGreaterEqual(frame["pumped"] - pumped, 0)
                pumped = frame["pumped"]
            self.assertEqual(ledger["damage"], cumulative_damage)
            self.assertEqual(ledger["peak"], max(f["exposed"] for f in frames))
            self.assertEqual(ledger["pumped"], pumped)
            self.assertEqual(ledger["rain"], sum(f["rain"] for f in frames) * 96)
            self.assertEqual(ledger["rain"] + ledger["river"] + ledger["sea"],
                             frames[-1]["stored"] + ledger["drained"] + ledger["soaked"] + pumped)

    def test_comparison_conservation_and_exports(self):
        data, prefix = self.run_sim("compare", "compare", "--steps", "144")
        self.assert_ledger(data)
        self.assertEqual([r["policy"] for r in data["runs"]], ["none", "homes", "canal"])
        rain = [[f["rain"] for f in r["frames"]] for r in data["runs"]]
        self.assertEqual(rain[0], rain[1])
        self.assertEqual(rain[0], rain[2])
        self.assertEqual(len({r["ledger"]["river"] for r in data["runs"]}), 1)
        baseline, homes, canal = data["runs"]
        self.assertEqual(baseline["ledger"]["pumped"], 0)
        self.assertLess(homes["ledger"]["damage"], baseline["ledger"]["damage"])
        self.assertNotEqual(homes["frames"], canal["frames"])
        with prefix.with_suffix(".csv").open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 3 * 145)
        for row, frame in zip(rows, [f for r in data["runs"] for f in r["frames"]]):
            self.assertEqual(int(row["stored"]), frame["stored"])
            self.assertEqual(int(row["exposure_index"]), frame["damage"])
        html = prefix.with_suffix(".html").read_text()
        embedded = re.search(r'<script id="experiment" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(embedded)
        self.assertEqual(json.loads(embedded.group(1)), data)
        self.assertNotRegex(html, r'<(?:script|link)[^>]+(?:src|href)="https?://')
        if shutil.which("node"):
            subprocess.run(["node", str(Path(__file__).with_name("test_replay.js")),
                            str(prefix.with_suffix(".html"))], check=True, timeout=10)

    def test_seeded_replay_and_policy_isolation(self):
        first, _ = self.run_sim("first", "run", "--steps", "48", "--seed", "7", "--policy", "homes")
        second, _ = self.run_sim("second", "run", "--steps", "48", "--seed", "7", "--policy", "homes")
        other, _ = self.run_sim("other", "run", "--steps", "48", "--seed", "8", "--policy", "homes")
        compared, _ = self.run_sim("compared", "compare", "--steps", "48", "--seed", "7")
        self.assertEqual(first, second)
        self.assertNotEqual(first["runs"][0]["frames"], other["runs"][0]["frames"])
        self.assertEqual(first["runs"][0], compared["runs"][1])

    def test_zero_budget_is_passive_for_every_policy(self):
        data, _ = self.run_sim("zero", "compare", "--steps", "48", "--budget", "0", "--seed", "0")
        self.assert_ledger(data)
        for run in data["runs"]:
            self.assertEqual(run["frames"], data["runs"][0]["frames"])
            self.assertEqual(run["ledger"], data["runs"][0]["ledger"])

    def test_maximum_duration_and_budget(self):
        data, _ = self.run_sim("maximum", "compare", "--steps", "360", "--budget", "96",
                               "--seed", "2147483645")
        self.assert_ledger(data)

    def test_invalid_options_do_not_export(self):
        for options in [("--steps", "0"), ("--steps", "361"), ("--steps", "oops"),
                        ("--budget", "-1"), ("--budget", "97"), ("--seed", "-1"),
                        ("--seed", "2147483646"), ("--policy", "magic"),
                        ("--unknown", "1"), ("--steps",)]:
            with self.subTest(options=options):
                result = subprocess.run([str(BINARY), "run", *options], cwd=self.root,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("kaindsim:", result.stdout)
                self.assertEqual(list(self.root.iterdir()), [])
        result = subprocess.run([str(BINARY), "run", "--out", str(self.root / "missing" / "run")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
