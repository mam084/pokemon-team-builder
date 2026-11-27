"""The command-line builder (scripts/build.py), the one-speed-plan rule and the weak-team flag."""

import contextlib
import io
import unittest
from unittest import mock

import src.builder as B
from src.builder import build_teams, mixes_speed, speed_modes
from src.dex import load_dex
from src.paste import parse_paste
from src.team import PokemonSet
from src.team_rating import is_weak
from src.usage import load_usage
from scripts import build as cli


def run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


TR = PokemonSet("Farigiraf", moves=["Trick Room", "Protect"])
TW = PokemonSet("Whimsicott", moves=["Tailwind", "Moonblast"])
BOTH = PokemonSet("Gallade", moves=["Trick Room", "Tailwind"])
NONE = PokemonSet("Incineroar", moves=["Fake Out", "Flare Blitz"])


class TestSpeedPlan(unittest.TestCase):
    def test_speed_modes(self):
        self.assertEqual(speed_modes(TR), {"Trick Room"})
        self.assertEqual(speed_modes(BOTH), {"Trick Room", "Tailwind"})
        self.assertEqual(speed_modes(NONE), set())

    def test_mixes_only_when_on(self):
        with mock.patch.object(B, "NO_MIXED_SPEED", True):
            self.assertTrue(mixes_speed(TW, [TR]))
            self.assertTrue(mixes_speed(BOTH, [TW, NONE]))
            self.assertFalse(mixes_speed(TR, [TR]))       # same plan
            self.assertFalse(mixes_speed(TW, [NONE]))     # first plan
            self.assertFalse(mixes_speed(NONE, [TR]))     # no plan
            self.assertFalse(mixes_speed(TW, [BOTH]))     # the core sets both: keep both
        with mock.patch.object(B, "NO_MIXED_SPEED", False):
            self.assertFalse(mixes_speed(TW, [TR]))


class TestWeakFlag(unittest.TestCase):
    def test_needs_every_lens(self):
        self.assertTrue(is_weak({"paper": ("Weak", 10), "proven": ("Weak", 12)}))
        self.assertTrue(is_weak({"paper": ("Weak", 10), "proven": ("Untested", None)}))
        self.assertFalse(is_weak({"paper": ("Strong", 80), "proven": ("Weak", 5)}))   # strong on paper
        self.assertFalse(is_weak({"paper": ("Weak", 10), "proven": ("Solid", 60)}))   # proven by real teams
        self.assertFalse(is_weak(None))


class TestBuildCli(unittest.TestCase):
    """Uses the shipped Reg M-C data (skips if it's missing)."""

    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.usage = load_usage("gen9championsvgc2026regmc")
        if cls.usage is None:
            raise unittest.SkipTest("no shipped usage data")

    def test_builds_and_prints_pastes(self):
        code, out, _ = run("Garganacl", "--teams", "2")
        self.assertEqual(code, 0)
        self.assertIn("Usual partners", out)
        self.assertIn("Team 1", out)
        self.assertIn("Team 2", out)
        self.assertIn("Garganacl @", out)

    def test_paste_only_round_trips(self):
        code, out, _ = run("Garganacl", "--teams", "2", "--paste-only")
        self.assertEqual(code, 0)
        blocks = [b for b in out.split("=== [gen9championsvgc2026regmc] Garganacl ") if b.strip()]
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            sets, _ = parse_paste(block.split("===", 1)[1], self.dex)
            self.assertEqual(len(sets), 6)
            self.assertEqual(sets[0].species, "Garganacl")

    def test_unknown_pokemon(self):
        code, _, err = run("Notamon")
        self.assertEqual(code, 1)
        self.assertIn("isn't in", err)

    def test_diversity_spreads_partners(self):
        def partners(weight):
            with mock.patch.object(B, "DIVERSITY_WEIGHT", weight):
                teams = build_teams("Baxcalibur", self.dex, self.usage)
            return len({p.species for t in teams for p in t.sets[1:]})
        self.assertGreater(partners(10.0), partners(0.0))

    def test_one_plan_builds_full_teams(self):
        with mock.patch.object(B, "NO_MIXED_SPEED", True):
            teams = build_teams("Baxcalibur", self.dex, self.usage)
        self.assertEqual(len(teams), 3)
        for t in teams:
            self.assertEqual(len(t.sets), 6)


if __name__ == "__main__":
    unittest.main()
