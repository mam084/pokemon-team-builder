"""Compare two versions of your team (ui/compare.py, Matchups tab)."""

import unittest

import pandas as pd

from src.team import PokemonSet
from tests.test_app import click, fresh, open_tab
from ui.compare import SAVED, team_diff, threat_changes


class TestHelpers(unittest.TestCase):
    def test_team_diff(self):
        a = [PokemonSet("Sneasler", moves=["Close Combat"]), PokemonSet("Kingambit"), PokemonSet("Garchomp")]
        b = [PokemonSet("Sneasler", moves=["Dire Claw"]), PokemonSet("Leafeon"), PokemonSet("Garchomp")]
        self.assertEqual(team_diff(a, b), "Out: Kingambit · In: Leafeon · New set: Sneasler")
        self.assertEqual(team_diff(a, a), "Same Pokémon, same sets")

    def test_threat_changes(self):
        old = pd.DataFrame({"pokemon": ["A", "B", "C"], "answers": ["none", "X (hit 80%)", "Y"]})
        new = pd.DataFrame({"pokemon": ["B", "A", "C"], "answers": ["none", "Z (hit 60%)", "Y"]})
        self.assertEqual(threat_changes(old, new), (["A"], ["B"]))
        self.assertEqual(threat_changes(old, pd.DataFrame()), ([], []))


class TestCompareApp(unittest.TestCase):
    def test_save_swap_compare_restore(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        self.assertFalse(at.exception)
        before = [at.session_state[f"s{i}_species"] for i in range(6)]
        click(at, key="save_version")
        self.assertIn(SAVED, at.session_state)
        self.assertTrue(any("same as the saved version" in c.value for c in at.caption))
        swap = next(b for b in at.button if b.key and b.key.startswith(("swap_", "alt_")))
        swap.click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("Now vs saved version", md)
        self.assertIn("Out:", md)
        self.assertTrue(any(m.label == "Win chance" and m.delta for m in at.metric))
        click(at, key="restore_version")
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], before)
        click(at, key="clear_version")
        self.assertNotIn(SAVED, at.session_state)

    def test_apply_swap_saves_the_version_before_it(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        swap = next(b for b in at.button if b.key and b.key.startswith(("swap_", "alt_")))
        swap.click().run()
        self.assertFalse(at.exception)
        self.assertIn("before swapping out", at.session_state[SAVED]["label"])
        self.assertIn("Now vs before swapping out", " ".join(m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
