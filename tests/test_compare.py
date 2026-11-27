"""Compare two versions of your team (ui/compare.py, Matchups tab)."""

import unittest

import pandas as pd

from src.team import PokemonSet
from tests.test_app import click, fresh, open_tab
from ui.compare import SAVED, STEPS, _pts, team_diff, threat_changes


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

    def test_pts(self):
        self.assertEqual(_pts(0.031, True), "+3 pts")
        self.assertEqual(_pts(-0.01, True), "-1 pt")
        self.assertEqual(_pts(-0.004, True), "no change")      # not "-0 pts"
        self.assertEqual(_pts(0.001, False), "no change")


class TestCompareApp(unittest.TestCase):
    def test_save_swap_compare_restore(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        self.assertFalse(at.exception)
        before = [at.session_state[f"s{i}_species"] for i in range(6)]
        click(at, key="save_version")
        self.assertIn(SAVED, at.session_state)
        self.assertTrue(any("same as the saved version" in c.value for c in at.caption))
        click(at, key="find_swaps")
        # Some alternatives don't move the win chance (they're listed whether or not they help, and which
        # come first depends on the retrained models), so try them until one does, restoring in between.
        keys = [b.key for b in at.button if b.key and b.key.startswith(("swap_", "alt_"))]
        moved = False
        for key in keys[:8]:
            next(b for b in at.button if b.key == key).click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            md = " ".join(m.value for m in at.markdown)
            self.assertIn("Now vs saved version", md)
            self.assertIn("Out:", md)
            if any(m.label == "Win chance" and m.delta for m in at.metric):
                moved = True
                break
            click(at, key="restore_version")
            click(at, key="find_swaps") if any(b.key == "find_swaps" for b in at.button) else None
        self.assertTrue(moved, "no swap changed the win chance")
        click(at, key="restore_version")
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], before)
        click(at, key="clear_version")
        self.assertNotIn(SAVED, at.session_state)

    def test_apply_swap_saves_the_version_before_it(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        click(at, key="find_swaps")
        swap = next(b for b in at.button if b.key and b.key.startswith(("swap_", "alt_")))
        swap.click().run()
        self.assertFalse(at.exception)
        self.assertIn("before swapping out", at.session_state[SAVED]["label"])
        self.assertIn("Now vs before swapping out", " ".join(m.value for m in at.markdown))


    def test_several_changes_in_a_row(self):
        def swap(at, last=False):
            if not any(b.key and b.key.startswith(("swap_", "alt_")) for b in at.button):
                click(at, key="find_swaps")
            found = [b for b in at.button if b.key and b.key.startswith(("swap_", "alt_"))]
            (found[-1] if last else found[0]).click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            return [at.session_state[f"s{i}_species"] for i in range(6)]

        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        start = [at.session_state[f"s{i}_species"] for i in range(6)]
        first = swap(at)
        self.assertEqual(len(at.session_state[STEPS]), 2)
        self.assertNotIn("undo_step", [b.key for b in at.button])            # one change: total == last
        swap(at)
        swap(at, last=True)
        self.assertEqual(len(at.session_state[STEPS]), 4)                     # saved + 3 changes
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("(3 changes)", md)
        self.assertIn("**Last change**", md)                                 # what the latest one did alone
        self.assertTrue(any("step" in d.value.columns and len(d.value) == 4 for d in at.dataframe))
        click(at, key="undo_step")                                           # one step back, not to the start
        self.assertEqual(len(at.session_state[STEPS]), 3)
        at.selectbox(key="step_pick").set_value(1).run()
        click(at, key="go_step")
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], first)
        self.assertEqual(len(at.session_state[STEPS]), 2)
        click(at, key="restore_version")
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], start)
        self.assertEqual(at.session_state[STEPS], [at.session_state[SAVED]["key"]])


if __name__ == "__main__":
    unittest.main()
