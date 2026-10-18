#!/usr/bin/env python3
"""Process-level regressions for the MayWar assembler, MARS and tournament."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

if len(sys.argv) < 2:
    sys.exit("usage: test_maywar.py MAYWAR_BINARY   (or run `may build test`)")
BINARY = Path(sys.argv.pop(1)).resolve()
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def maywar(*args, check=True):
    proc = subprocess.run([str(BINARY), *args], capture_output=True, text=True, timeout=120)
    if check and proc.returncode != 0:
        raise AssertionError(f"maywar {' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}{proc.stderr}")
    return proc


class WarriorFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, source, name="w.red"):
        path = Path(self.tmp.name) / name
        path.write_text(source)
        return str(path)

    def lifetime(self, source, cycles=200):
        """Cycles a warrior survives running alone."""
        out = maywar("watch", self.write(source), "--delay", "0", "--speed", "100000",
                     "--cycles", str(cycles), "--core", "800").stdout
        match = re.search(r"ran for (\d+) cycles", ANSI.sub("", out))
        self.assertIsNotNone(match, out[-400:])
        return int(match.group(1))


class AssemblerTests(WarriorFiles):
    def test_builtin_listing(self):
        out = maywar("check", "dwarf").stdout.splitlines()
        self.assertEqual(out[:2], [";name Dwarf", ";author A. K. Dewdney"])
        self.assertIn("        ORG    1", out)
        self.assertEqual(out[-4:], [
            "0000    DAT.F  #0, #0",
            "0001 >  ADD.AB #4, $-1",
            "0002    MOV.I  $-2, @-2",
            "0003    JMP.B  $-2, $0",
        ])

    def test_labels_equ_and_expressions(self):
        src = """;name Exprs
;author tester
size    EQU     (3 + 4) * 2
gap     EQU     size - 4
top:    MOV     #size % 5, @last
        ADD.F   last, top
        SUB.X   *gap, {-1
        CMP     >top, <-2
last    DAT     -gap
        ORG     top+1
"""
        out = maywar("check", self.write(src)).stdout.splitlines()
        self.assertEqual(out[:2], [";name Exprs", ";author tester"])
        self.assertEqual(out[2:], [
            "        ORG    1",
            "0000    MOV.AB #4, @4",
            "0001 >  ADD.F  $3, $-1",
            "0002    SUB.X  *10, {-1",
            "0003    SEQ.I  >-3, <-2",
            "0004    DAT.F  #0, $-10",
        ])

    def test_default_modifiers(self):
        src = "MOV 1, #2\nADD #1, 2\nSLT 1, 2\nSLT #1, 2\nJMZ 1, 2\nNOP\nDAT 1, 2\nSNE 1, 2\n"
        mods = re.findall(r"\b[A-Z]{3}\.[A-Z]+", maywar("check", self.write(src)).stdout)
        self.assertEqual(mods, ["MOV.B", "ADD.AB", "SLT.B", "SLT.AB", "JMZ.B", "NOP.F", "DAT.F", "SNE.I"])

    def test_end_sets_start_and_stops_reading(self):
        src = "a  DAT 0\nb  JMP a\n   END b\n   this is not redcode\n"
        out = maywar("check", self.write(src)).stdout
        self.assertIn("0001 >  JMP.B  $-1, $0", out)

    def test_errors_report_lines_and_fail(self):
        src = "start MOV 0, 1\n      JMP.Q nowhere\nstart DAT 0\n      ADD #1,\n      MOV 0, 1 +\n      JMP nowhere\n"
        proc = maywar("check", self.write(src), check=False)
        self.assertEqual(proc.returncode, 1)
        lines = proc.stdout.strip().splitlines()
        self.assertTrue(any("line 2: unknown modifier `Q`" in l for l in lines), lines)
        self.assertTrue(any("line 3: label `start` is defined twice" in l for l in lines), lines)
        self.assertTrue(any("line 4: missing operand after `,`" in l for l in lines), lines)
        self.assertTrue(any("line 6: unknown label `nowhere`" in l for l in lines), lines)
        self.assertTrue(any("line 5: expression ends unexpectedly" in l for l in lines), lines)

    def test_length_limit(self):
        proc = maywar("check", self.write("NOP\n" * 101), check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("warrior has 101 instructions; the limit is 100", proc.stdout)

    def test_unknown_warrior(self):
        proc = maywar("battle", "imp", "no-such-warrior", check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("neither a file nor a built-in warrior", proc.stdout)


class SemanticsTests(WarriorFiles):
    def test_dat_kills(self):
        self.assertEqual(self.lifetime("DAT 0\n"), 1)

    def test_nop_falls_through(self):
        self.assertEqual(self.lifetime("NOP\nNOP\nDAT 0\n"), 3)

    def test_division_by_zero_kills(self):
        self.assertEqual(self.lifetime("DIV #0, 1\nJMP -1\nDAT 1, 1\n"), 1)
        self.assertEqual(self.lifetime("MOD.AB #2, 1\nJMP -1\nDAT 1, 1\n"), 200)

    def test_djn_counts_down(self):
        self.assertEqual(self.lifetime("DJN 0, #5\nDAT 0\n"), 6)

    def test_seq_and_sne_skip(self):
        # Cells 10 and 11 are both empty, so they compare equal.
        tail = "DAT 0\nNOP\nDAT 0\n"
        self.assertEqual(self.lifetime("SEQ.I 10, 11\n" + tail), 3)
        self.assertEqual(self.lifetime("SNE.I 10, 11\n" + tail), 2)
        self.assertEqual(self.lifetime("SLT #0, 1\n" + "DAT 0, 7\nNOP\nDAT 0\n"), 3)

    def test_jmz_and_jmn(self):
        self.assertEqual(self.lifetime("JMZ 2, 3\nDAT 0\nNOP\nDAT 0\n"), 3)
        self.assertEqual(self.lifetime("JMN 2, 3\nDAT 0\nNOP\nDAT 0\n"), 2)

    def test_spl_runs_both_processes(self):
        # Each process takes one turn per cycle, so two processes ending at a
        # DAT after three instructions in total die on cycle 3.
        self.assertEqual(self.lifetime("SPL 2\nDAT 0\nDAT 0\n"), 3)

    def test_predecrement_and_postincrement(self):
        # `<` decrements before use; `>` increments after the copy, so the
        # pointer moves on and the imp-like loop survives.
        self.assertEqual(self.lifetime("MOV 0, >2\nJMP -1\nDAT 0, 5\n", cycles=150), 150)
        self.assertEqual(self.lifetime("JMP @1\nDAT 0, 1\nNOP\nDAT 0\n"), 3)
        self.assertEqual(self.lifetime("JMP @1\nDAT 0, 2\nNOP\nDAT 0\n"), 2)
        self.assertEqual(self.lifetime("JMP <1\nDAT 0, 2\nNOP\nDAT 0\n"), 3)

    def test_builtins_survive_alone(self):
        for name in ["imp", "dwarf", "mice", "silkworm", "lookout", "nosferatu"]:
            out = ANSI.sub("", maywar("watch", name, "--delay", "0", "--speed", "100000").stdout)
            self.assertIn("ran for 80000 cycles", out, name)


class MatchTests(unittest.TestCase):
    def test_battle_is_deterministic(self):
        first = maywar("battle", "mice", "dwarf", "--rounds", "6", "--seed", "7").stdout
        second = maywar("battle", "mice", "dwarf", "--rounds", "6", "--seed", "7").stdout
        strip = lambda s: re.sub(r"\(\d+ ms\)", "", s)
        self.assertEqual(strip(first), strip(second))

    def test_classic_matchups(self):
        def wins(a, b):
            out = maywar("battle", a, b, "--rounds", "10").stdout
            return [int(n) for n in re.findall(r"(\d+) wins", out)]
        mice, dwarf = wins("mice", "dwarf")
        self.assertGreater(mice, dwarf)  # replicators outlast simple bombers
        silk, dwarf = wins("silkworm", "dwarf")
        self.assertGreater(silk, dwarf)
        imp, dwarf = wins("imp", "dwarf")
        self.assertEqual(imp, 0)  # an imp cannot kill anything

    def test_hill_table(self):
        out = maywar("hill", "imp", "dwarf", "mice", "--rounds", "4").stdout
        self.assertIn("MayWar hill: 3 warriors, 4 rounds per pairing", out)
        rows = [l for l in out.splitlines() if re.match(r"\s+\d  ", l)]
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0].lstrip().startswith("1  "))


if __name__ == "__main__":
    unittest.main()
