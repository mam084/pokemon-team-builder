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


class TestFieldClash(unittest.TestCase):
    """One weather and one terrain per team (src/builder.clashes_field)."""

    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.rain = PokemonSet("Sableye", ability="Prankster", moves=["Rain Dance", "Encore"])
        cls.sun = PokemonSet("Charizard", item="Charizardite Y", ability="Blaze", moves=["Heat Wave"])
        cls.sand = PokemonSet("Tyranitar", ability="Sand Stream", moves=["Rock Slide"])
        cls.grass = PokemonSet("Rillaboom", ability="Grassy Surge", moves=["Fake Out"])
        cls.psychic = PokemonSet("Indeedee-F", ability="Psychic Surge", moves=["Follow Me"])

    def test_setters(self):
        self.assertEqual(B.field_setters(self.sun, self.dex)["weather"], {"sun"})    # by its Mega's ability
        self.assertEqual(B.field_setters(self.rain, self.dex)["weather"], {"rain"})  # by move
        self.assertEqual(B.field_setters(self.grass, self.dex)["terrain"], {"grassyterrain"})
        self.assertEqual(B.field_setters(NONE, self.dex), {"weather": set(), "terrain": set()})

    def test_clash_only_when_on(self):
        with mock.patch.object(B, "NO_FIELD_CLASH", True):
            self.assertTrue(B.clashes_field(self.rain, [self.sun], self.dex))
            self.assertTrue(B.clashes_field(self.sand, [NONE, self.rain], self.dex))
            self.assertTrue(B.clashes_field(self.psychic, [self.grass], self.dex))
            self.assertFalse(B.clashes_field(self.sun, [self.sun], self.dex))      # same weather
            self.assertFalse(B.clashes_field(self.sun, [self.grass], self.dex))    # weather + terrain is fine
            self.assertFalse(B.clashes_field(self.rain, [NONE], self.dex))         # first weather
        with mock.patch.object(B, "NO_FIELD_CLASH", False):
            self.assertFalse(B.clashes_field(self.rain, [self.sun], self.dex))


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

    def test_core_only_pairs_with_the_core(self):
        tm = self.usage.teammates
        core = tm.index["baxcalibur"]
        def pull(only):
            with mock.patch.object(B, "CORE_ONLY", only):
                teams = build_teams("Baxcalibur", self.dex, self.usage)
            self.assertEqual(len(teams), 3)
            ids = [tm.index.get(self.dex.sheet_id(self.dex.get_species(p.species))) for t in teams for p in t.sets[1:]]
            return sum(tm.W[core, j] for j in ids if j is not None)
        self.assertGreater(pull(True), pull(False))

    def test_one_plan_builds_full_teams(self):
        with mock.patch.object(B, "NO_MIXED_SPEED", True):
            teams = build_teams("Baxcalibur", self.dex, self.usage)
        self.assertEqual(len(teams), 3)
        for t in teams:
            self.assertEqual(len(t.sets), 6)


if __name__ == "__main__":
    unittest.main()


class TestScoreLine(unittest.TestCase):
    def test_one_headline_number(self):
        from src.team_rating import details_line, score_line
        self.assertEqual(score_line(63.4), "Team score 63 (Solid): rates above 63% of tournament teams")
        self.assertEqual(details_line({"proven": ("Shaky", 30), "paper": ("Solid", 60)}, 0.51),
                         "Proven: Shaky · On paper: Solid · 51.0% learned win chance vs the meta teams")
        self.assertEqual(details_line(None, None), "")
class TestSetReason(unittest.TestCase):
    """Built teams' reasons: no cautions, and speed claims only when the set backs them up."""

    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")

    def test_drops_cautions_and_unbacked_speed_claims(self):
        slow = PokemonSet("Rillaboom", nature="Adamant", sps={"hp": 32, "atk": 32, "spe": 2})
        fast = PokemonSet("Rillaboom", nature="Jolly", sps={"atk": 32, "spe": 32})
        why = ("plays into your Tailwind: base 85 Speed doubles to outspeed; players pair it with Gliscor (1.7x); "
               "rarely run next to Excadrill (0.4x); resists Water")
        self.assertEqual(B.set_reason(why, slow, self.dex), "players pair it with Gliscor (1.7x); resists Water")
        self.assertTrue(B.set_reason(why, fast, self.dex).startswith("plays into your Tailwind"))
        self.assertNotIn("rarely run next to", B.set_reason(why, fast, self.dex))
        tr = "plays into your Trick Room: slow (base 40 Speed); resists Fire"
        self.assertEqual(B.set_reason(tr, fast, self.dex), "resists Fire")
        self.assertEqual(B.set_reason(tr, slow, self.dex), tr)
        self.assertEqual(B.set_reason("rarely run next to X (0.3x)", slow, self.dex), "solid all-round pick")

    def test_built_reasons_have_no_cautions(self):
        usage = load_usage("gen9championsvgc2026regmc")
        if usage is None:
            self.skipTest("no shipped usage data")
        for t in build_teams("Gliscor", self.dex, usage):
            for r in t.reasons:
                self.assertNotIn("rarely run next to", r)
