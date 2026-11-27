"""The one-line game plan on built teams (src/team_plan.py)."""

import unittest

from src.dex import load_dex
from src.team import PokemonSet, empty_sps
from src.team_plan import plan_line


def mon(species, moves, ability="", item="", nature="Serious", sps=None):
    spread = empty_sps()
    spread.update(sps or {"hp": 2, "atk": 32, "spe": 32})
    return PokemonSet(species, item=item, ability=ability, nature=nature, moves=moves, sps=spread)


class TestPlanLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.team = [
            mon("Gliscor", ["Tailwind", "Protect", "High Horsepower", "Acrobatics"], "Hyper Cutter"),
            mon("Incineroar", ["Fake Out", "Parting Shot", "Flare Blitz", "Knock Off"], "Intimidate"),
            mon("Rillaboom", ["Fake Out", "Grassy Glide", "Wood Hammer", "High Horsepower"], "Grassy Surge"),
            mon("Gholdengo", ["Nasty Plot", "Make It Rain", "Shadow Ball", "Protect"], "Good as Gold"),
            mon("Primarina", ["Hyper Voice", "Moonblast", "Protect", "Calm Mind"], "Liquid Voice"),
            mon("Annihilape", ["Close Combat", "Rage Fist", "Protect", "Ice Punch"], "Defiant"),
        ]

    def test_lead_covers_the_speed_setter(self):
        line = plan_line(self.team, self.dex)
        self.assertTrue(line.startswith("Lead Gliscor + "), line)
        self.assertRegex(line, r"(Incineroar|Rillaboom)'s Fake Out buys Gliscor a free Tailwind")
        lead = line.split(":")[0]
        self.assertFalse("Incineroar" in lead and "Rillaboom" in lead, line)   # not two Fake Outs

    def test_one_setup_sweeper_and_the_rest_flex(self):
        line = plan_line(self.team, self.dex)
        self.assertEqual(line.count("(sets up)"), 1, line)   # Gholdengo and Primarina both set up: one closes
        self.assertIn("Swap in ", line)
        named = [p.species for p in self.team if p.species in line]
        self.assertEqual(len(named), 6, line)                 # 4 to bring + 2 to swap in

    def test_closers_use_the_speed_plan(self):
        self.assertIn("under Tailwind", plan_line(self.team, self.dex))

    def test_core_always_comes(self):
        team = self.team[3:] + self.team[:3]   # Gholdengo is the core now; it isn't a lead
        bring = plan_line(team, self.dex).split("Swap in")[0]
        self.assertIn("Gholdengo", bring)

    def test_singles_and_short_teams(self):
        line = plan_line(self.team, self.dex, doubles=False)
        self.assertTrue(line.startswith("Lead Gliscor: Gliscor sets Tailwind turn one."), line)
        self.assertIn(", ", line.split("Swap in")[1])          # three to swap in: commas
        self.assertEqual(plan_line(self.team[:3], self.dex), "")
