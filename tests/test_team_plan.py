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

    def test_leads_with_speed_control_and_one_fake_out(self):
        line = plan_line(self.team, self.dex)
        self.assertTrue(line.startswith("Lead Gliscor + "), line)
        self.assertIn("Tailwind", line)
        self.assertIn("Fake Out", line)
        lead = line.split(";")[0]
        self.assertFalse("Incineroar" in lead and "Rillaboom" in lead, line)   # not two Fake Outs

    def test_closers_are_attackers_from_the_back(self):
        back = plan_line(self.team, self.dex).split(";")[1]
        self.assertIn("(sets up)", back)
        self.assertNotIn("Gliscor", back)

    def test_singles_and_short_teams(self):
        self.assertTrue(plan_line(self.team, self.dex, doubles=False).startswith("Lead Gliscor (Tailwind)"))
        self.assertEqual(plan_line(self.team[:3], self.dex), "")
