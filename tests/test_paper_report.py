"""Why a team rates as it does on paper (src/paper_report.py)."""

import unittest
from unittest import mock

from src import paper_report as P


class TestBreakdown(unittest.TestCase):
    def test_groups_averages_and_fixes(self):
        model = {"model": {"features": ["OHKOs", "2HKOs", "tool: Fake Out", "tool: Recovery", "bulk (mean)"],
                           "coef": [1.0, 1.0, 1.0, -1.0, 1.0]}}
        pushes = {"A": [("OHKOs", -0.2), ("2HKOs", -0.1), ("tool: Fake Out", -0.08), ("bulk (mean)", 0.1)],
                  "B": [("OHKOs", -0.2), ("tool: Recovery", -0.08), ("species: x", 0.2)]}
        with mock.patch.object(P, "contributions", lambda m, a, b: pushes[b["name"]]), \
                mock.patch.object(P, "predict_match", lambda m, a, b: {"A": 0.6, "B": 0.4}[b["name"]]):
            out = P.breakdown(model, [{"name": "me"}], [{"name": "A"}, {"name": "B"}], ["Rain", "Sun"],
                              weights=[1.0, 3.0])
        parts = {g: (v, fix) for g, v, fix in out["parts"]}
        # damage calcs: (1 x -0.3 + 3 x -0.2) / 4 x 25 = -5.6
        self.assertAlmostEqual(parts["Damage calcs"][0], -5.625)
        self.assertIn("Hit the meta harder", parts["Damage calcs"][1])
        self.assertEqual(out["parts"][0][0], "Damage calcs")              # most costly first
        self.assertIn("won more often", parts["Fake Out"][1])             # positive coefficient: add it
        self.assertIn("won a little less often", parts["Recovery"][1])    # negative: you have more
        self.assertEqual(parts["Pokémon picks"][1], "")                   # a gain needs no fix
        self.assertEqual(out["toughest"][0], ("Sun", 0.4))
        self.assertAlmostEqual(out["average"], (0.6 + 3 * 0.4) / 4)

    def test_empty(self):
        self.assertEqual(P.breakdown({"model": {"features": [], "coef": []}}, [], [])["parts"], [])

    def test_group_names(self):
        self.assertEqual(P.group_of("outspeeds (share)"), "Speed")
        self.assertEqual(P.group_of("tool: Intimidate"), "Intimidate")
        self.assertEqual(P.group_of("species: garchomp"), "Pokémon picks")
