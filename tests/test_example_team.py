"""
The sidebar's Example team: a regulation's hand-picked team, else its newest big tournament winner, else
(before its first tournaments) the last regulation's pick while it's still legal.
"""

import dataclasses
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("PTB_WARMUP", "0")

from src.dex import DEX_DIR, Dex, load_dex  # noqa: E402
from src.formats import FORMATS  # noqa: E402
from src.legality import check_team  # noqa: E402
from src.paste import parse_paste  # noqa: E402
import ui.sidebar as sidebar  # noqa: E402

MC = "gen9championsvgc2026regmc"


class TestExampleTeam(unittest.TestCase):
    def test_pinned_example_for_the_current_regulation(self):
        paste, text = sidebar.example_for(MC, load_dex("regmc"))
        self.assertEqual(paste, sidebar.SAMPLE_TEAM)
        self.assertIn("Reg M-C", text)

    def test_newest_big_winner_without_a_pinned_team(self):
        dex = load_dex("regmc")
        with mock.patch.dict(sidebar.PINNED, clear=True):
            found = sidebar.example_for(MC, dex)
        self.assertIsNotNone(found)
        paste, text = found
        team, warnings = parse_paste(paste, dex)
        self.assertEqual(len(team), 6)
        self.assertFalse(warnings)
        self.assertFalse([i for i in check_team(team, dex) if i.level == "error"])
        self.assertIn("player tournament", text)

    def test_last_regulations_pick_before_any_tournaments(self):
        fake = "gen9championsvgc2026regzz"
        FORMATS[fake] = dataclasses.replace(FORMATS[MC], id=fake, regulation="regzz", previous=MC)
        try:
            with mock.patch.object(sidebar, "_newest_winner", return_value=None):
                paste, text = sidebar.example_for(fake, load_dex("regmc"))
                self.assertEqual(paste, sidebar.SAMPLE_TEAM)
                self.assertIn("last regulation", text)
                # not legal in the new regulation (here: an empty dex has none of its Pokémon): no example
                raw = json.loads((DEX_DIR / "regmc.json").read_text())
                empty = Dex({**raw, "species": {}})
                self.assertIsNone(sidebar.example_for(fake, empty))
        finally:
            FORMATS.pop(fake, None)


if __name__ == "__main__":
    unittest.main()
