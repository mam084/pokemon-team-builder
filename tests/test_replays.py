"""Replay parsing on real Showdown logs (tests/fixtures/replays) and replay analysis."""

import json
import unittest
from pathlib import Path

from src.replay_parse import PLAYERS, is_usable, parse_log, parse_packed_team
from src.replays import species_stats

FIXTURES = Path(__file__).parent / "fixtures" / "replays"


def load(name):
    data = json.loads((FIXTURES / name).read_text())
    return parse_log(data["log"], data)


class ReplayParseTest(unittest.TestCase):
    def test_real_logs(self):
        for path in sorted(FIXTURES.glob("*.json")):
            rec = load(path.name)
            self.assertTrue(is_usable(rec), path.name)
            for p in PLAYERS:
                preview = set(rec["preview"][p])
                self.assertEqual(len(rec["preview"][p]), 6)
                self.assertLessEqual(len(rec["brought"][p]), 4 if not rec["forfeit"] else 6)
                self.assertTrue(set(rec["brought"][p]) <= preview, (path.name, rec["brought"][p], preview))
                self.assertEqual(len(rec["leads"][p]), 2)
                self.assertTrue(set(rec["leads"][p]) <= set(rec["brought"][p]))
            self.assertIn(rec["winner"], PLAYERS)
            self.assertGreater(rec["turns"], 0)

    def test_open_team_sheets(self):
        rec = load("gen9championsvgc2026regmcbo3-2714431328.json")
        sheet = rec["sheets"]["p1"]
        self.assertEqual(len(sheet), 6)
        self.assertEqual(sheet[0]["species"], "Mr. Mime")
        self.assertIn("FakeOut", sheet[0]["moves"])

    def test_packed_team(self):
        team = parse_packed_team("Cat|Incineroar|SitrusBerry|Intimidate|FakeOut,FlareBlitz||||||50|]"
                                 "Garchomp||ChoiceScarf|RoughSkin|Earthquake|Jolly||M|||50|")
        self.assertEqual([t["species"] for t in team], ["Incineroar", "Garchomp"])
        self.assertEqual(team[0]["item"], "SitrusBerry")

    def test_species_stats(self):
        recs = [load(p.name) for p in sorted(FIXTURES.glob("*.json"))]
        rows = species_stats(recs, min_previews=1)
        self.assertTrue(rows)
        for r in rows:
            self.assertGreaterEqual(r["brought %"], r["leads %"] - 1e-9)


if __name__ == "__main__":
    unittest.main()
