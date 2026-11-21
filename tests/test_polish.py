"""Nov 20 review fixes: swap labels, no mirror match on the Pokémon tab, the full-team recommendation list,
threat-card wording, the Playbook pointer, and no background warm-up."""

import unittest
from pathlib import Path

import pandas as pd

from tests.test_app import click, fresh, open_tab
from ui.matchups_tab import change_text, pick_label

ROOT = Path(__file__).resolve().parent.parent


class TestSwapLabels(unittest.TestCase):
    def row(self, **kw):
        base = {"pick": "Best upgrade", "score": 98.0, "score change": 0.4, "win change": None,
                "overall change": 0.0}
        base.update(kw)
        return pd.Series(base)

    def test_upgrade_is_never_about_the_same(self):
        same = self.row()
        self.assertEqual(change_text(same), "team score 98 (about the same)")
        self.assertEqual(pick_label(same), "Best alternative")
        up = self.row(**{"score change": 3.0})
        self.assertEqual(pick_label(up), "Best upgrade")
        self.assertEqual(pick_label(self.row(**{"score change": -5.0})), "Best alternative")
        self.assertEqual(pick_label(self.row(pick="Most similar")), "Most similar")
        win = self.row(score=None, **{"score change": None, "win change": 0.1})
        self.assertEqual(pick_label(win), "Best alternative")
        self.assertEqual(pick_label(self.row(score=None, **{"score change": None, "win change": 1.5})),
                         "Best upgrade")


class TestMirror(unittest.TestCase):
    def test_no_mirror_in_core_matchups(self):
        from src.builder import core_set
        from src.core_report import core_matchups
        from src.dex import load_dex
        from src.usage import load_usage
        usage, dex = load_usage("gen9championsvgc2026regmc"), load_dex("regmc")
        for name in ["Sneasler", "Charizard", "Garchomp"]:
            r = core_matchups(core_set(name, dex, usage), usage, dex)
            names = [x[0] for x in r["beats"] + r["threats"]]
            self.assertTrue(names)
            self.assertFalse([n for n in names if n.split("-")[0] == name], name)


class TestAppPolish(unittest.TestCase):
    def test_full_team_shows_three_picks_then_all(self):
        at = open_tab(click(fresh(), label="Example team"), "Recommendations")
        self.assertFalse(at.exception)
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("3. ", md)
        self.assertNotIn("4. ", md)
        at = at.toggle(key="rec_show_all").set_value(True).run()
        self.assertFalse(at.exception)
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("10. ", md)

    def test_threat_cards_and_playbook_wording(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        caps = " ".join(c.value for c in at.caption)
        self.assertNotIn("Beats it 1-on-1", caps)
        self.assertTrue("Your answers (win 1-on-1)" in caps or "Nothing on your team wins 1-on-1" in caps)
        at = open_tab(at, "Playbook")
        caps = " ".join(c.value for c in at.caption)
        self.assertIn("are on the Battle plan tab", caps)

    def test_swaps_run_on_request(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        keys = [b.key for b in at.button if b.key]
        self.assertIn("find_swaps", keys)
        self.assertFalse([k for k in keys if k.startswith(("swap_", "alt_"))])   # not searched yet
        click(at, key="find_swaps")
        self.assertFalse(at.exception)
        self.assertTrue([b for b in at.button if b.key and b.key.startswith(("swap_", "alt_"))])
        self.assertNotIn("find_swaps", [b.key for b in at.button])
        at = open_tab(open_tab(at, "Analysis"), "Matchups")                      # stays on for the visit
        self.assertTrue([b for b in at.button if b.key and b.key.startswith(("swap_", "alt_"))])

    def test_no_background_warmup(self):
        self.assertFalse((ROOT / "ui" / "warmup.py").exists())
        self.assertNotIn("warmup", (ROOT / "app.py").read_text())


if __name__ == "__main__":
    unittest.main()
