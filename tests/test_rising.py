"""Rising this week (src/replays.rising) and its section in the Pokémon tab."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.dex import load_dex
from src.replays import rising

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DAY = 86400
END = 1_800_000_000
BASE = ["Incineroar", "Rillaboom", "Garchomp", "Kingambit", "Sinistcha", "Farigiraf"]


def game(t, i, team_a, team_b):
    side = lambda team: {"rating": 1500, "name": f"player{i}"}
    return {"uploadtime": t, "players": {"p1": side(team_a), "p2": {"rating": 1500, "name": f"other{i}"}},
            "preview": {"p1": team_a, "p2": team_b}}


class TestRising(unittest.TestCase):
    def test_finds_what_rose_and_ignores_what_fell(self):
        dex = load_dex("regmc")
        with_gengar = BASE[:5] + ["Gengar"]
        recs = []
        for i in range(600):   # last week: no Gengar; this week: on a third of p1's teams
            recs.append(game(END - 10 * DAY + i, i, BASE, BASE[::-1]))
            recs.append(game(END - 3 * DAY + i, 1000 + i, with_gengar if i % 3 == 0 else BASE, BASE[::-1]))
        up = rising(recs, dex)
        self.assertEqual(up["pokemon"][0]["id"], "gengar")
        self.assertAlmostEqual(up["pokemon"][0]["before"], 0.0)
        self.assertTrue(all(r["share"] > r["before"] for r in up["pokemon"]))
        self.assertNotIn("farigiraf", [r["id"] for r in up["pokemon"]])   # fell when Gengar replaced it

    def test_too_few_teams_shows_nothing(self):
        dex = load_dex("regmc")
        recs = [game(END - 3 * DAY + i, i, BASE, BASE) for i in range(50)]
        self.assertIsNone(rising(recs, dex))

    def test_section_opens_a_riser(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.session_state["main_tabs"] = "Pokémon"
        at.run()
        pills = at.pills(key="rising_pick")
        if not pills.options:
            self.skipTest("no rising data for this format")
        name = list(pills.options)[-1].split("  ")[0]   # options read back as their labels
        pills.set_value(name)
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="poke_name").value, name)


class TestUsageWindow(unittest.TestCase):
    def test_labels_say_what_the_numbers_cover(self):
        from src.usage import load_usage
        u = load_usage("gen9championsvgc2026regmc")
        if u.recent:
            self.assertRegex(u.window(), r"^last \d+ days$")
        import copy
        monthly = copy.copy(u)   # load_usage is cached: don't change the shared one
        monthly.recent, monthly.info = None, {"month": "2026-10"}
        self.assertEqual(monthly.window(), "Smogon, 2026-10")


if __name__ == "__main__":
    unittest.main()
