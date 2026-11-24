"""Rising this week (src/replays.rising) and its section in the Pokémon tab."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.dex import load_dex
from src.replays import rising

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DAY = 86400
SUNDAY = 1_795_910_400                       # Sun 2026-11-29 00:00 UTC
WED = SUNDAY + 3 * DAY + 12 * 3600            # Wed 2026-12-02 12:00 UTC
BASE = ["Incineroar", "Rillaboom", "Garchomp", "Kingambit", "Sinistcha", "Farigiraf"]


def game(t, i, team_a, team_b):
    side = lambda team: {"rating": 1500, "name": f"player{i}"}
    return {"uploadtime": t, "players": {"p1": side(team_a), "p2": {"rating": 1500, "name": f"other{i}"}},
            "preview": {"p1": team_a, "p2": team_b}}


def two_weeks(this_week_start, this_week_end, gengar_every=3):
    """Last full week without Gengar; this week with Gengar on a third of p1's teams."""
    with_gengar = BASE[:5] + ["Gengar"]
    recs = []
    for i in range(600):
        recs.append(game(this_week_start - 7 * DAY + 3600 + i * 60, i, BASE, BASE[::-1]))
        t = this_week_start + 60 + i * ((this_week_end - this_week_start - 120) // 600)
        recs.append(game(t, 1000 + i, with_gengar if i % gengar_every == 0 else BASE, BASE[::-1]))
    return recs


class TestRising(unittest.TestCase):
    def test_weeks_start_on_sunday(self):
        from src.replays import week_start
        self.assertEqual(week_start(WED), SUNDAY)
        self.assertEqual(week_start(SUNDAY), SUNDAY)
        self.assertEqual(week_start(SUNDAY - 1), SUNDAY - 7 * DAY)   # Saturday night is last week

    def test_finds_what_rose_since_sunday_and_ignores_what_fell(self):
        dex = load_dex("regmc")
        up = rising(two_weeks(SUNDAY, WED), dex, now=WED)
        self.assertEqual((up["first_day"], up["before_first_day"], up["before_last_day"]),
                         ("2026-11-29", "2026-11-22", "2026-11-28"))
        self.assertEqual(up["pokemon"][0]["id"], "gengar")
        self.assertAlmostEqual(up["pokemon"][0]["before"], 0.0)
        self.assertTrue(all(r["share"] > r["before"] for r in up["pokemon"]))
        self.assertNotIn("farigiraf", [r["id"] for r in up["pokemon"]])   # fell when Gengar replaced it

    def test_early_sunday_compares_the_last_two_full_weeks(self):
        dex = load_dex("regmc")
        recs = two_weeks(SUNDAY - 7 * DAY, SUNDAY)   # the rise happened last week
        recs += [game(SUNDAY + 600 + i, 5000 + i, BASE, BASE) for i in range(20)]   # Sunday so far: 20 teams
        up = rising(recs, dex, now=SUNDAY + 3600)
        self.assertEqual((up["first_day"], up["last_day"]), ("2026-11-22", "2026-11-28"))
        self.assertEqual(up["pokemon"][0]["id"], "gengar")

    def test_too_few_teams_shows_nothing(self):
        dex = load_dex("regmc")
        recs = [game(WED - i, i, BASE, BASE) for i in range(50)]
        self.assertIsNone(rising(recs, dex, now=WED))

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
