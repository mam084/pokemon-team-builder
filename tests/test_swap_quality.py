"""Swap quality changes (Nov 21): Players' pick by teammate fit, backing labels, Same role off by default.
Evidence: scripts/swap_quality_lab.py (outcomes) and scripts/swap_choice_lab.py (what players choose)."""

import unittest

import pandas as pd

from src.dex import load_dex
from src.swaps import PLAYERS_PICK, backing
from ui.matchups_tab import BACKING_NOTE, backing_note, cached_swaps, team_key
from tests.test_app import click, fresh, open_tab

FMT = "gen9championsvgc2026regmc"


class TestBacking(unittest.TestCase):
    def test_backing(self):
        self.assertEqual(backing(0.2, 0.5), "both")
        self.assertEqual(backing(-0.3, 0.9), "win model only")
        self.assertEqual(backing(0.4, -0.1), "fit only")
        self.assertEqual(backing(-0.1, -0.1), "neither")

    def test_note_only_for_real_upgrades(self):
        row = lambda **kw: pd.Series({"backing": "win model only", "score change": 8.0, **kw})  # noqa: E731
        self.assertEqual(backing_note(row()), BACKING_NOTE["win model only"])
        self.assertEqual(backing_note(row(backing="both")), BACKING_NOTE["both"])
        self.assertEqual(backing_note(row(**{"score change": 0.0})), "")      # not an upgrade
        self.assertEqual(backing_note(row(backing="fit only")), "")
        self.assertEqual(backing_note(row(backing=None)), "")


class TestSwapsOutput(unittest.TestCase):
    def team(self):
        from src.paste import parse_paste
        from ui.sidebar import SAMPLE_TEAM
        return parse_paste(SAMPLE_TEAM, load_dex("regmc"))[0]

    def test_players_pick_is_ranked_by_fit_and_backing_is_set(self):
        team = self.team()
        pm = cached_swaps(FMT, team_key(team), None, "neutral", False, 3)
        self.assertEqual(set(pm["pick"]), {"Best upgrade", PLAYERS_PICK})
        for _, g in pm.groupby("slot"):
            fits = list(g[g["pick"] == PLAYERS_PICK]["fit"])
            self.assertEqual(fits, sorted(fits, reverse=True))
        best = cached_swaps(FMT, team_key(team), None, "neutral", False, None)
        self.assertTrue(set(best["backing"].dropna()) <= {"both", "fit only", "win model only", "neither"})
        self.assertTrue(best["backing"].notna().all())


class TestDefaults(unittest.TestCase):
    def test_same_role_off_and_how_it_works(self):
        at = open_tab(click(fresh(), label="Example team"), "Matchups")
        self.assertFalse(at.toggle(key="swap_same_role").value)
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("Players' pick", md)
        self.assertIn("How well it works", md)


if __name__ == "__main__":
    unittest.main()
