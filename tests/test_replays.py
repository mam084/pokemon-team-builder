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

    def test_mega_turn_weather_and_field(self):
        rec = load("gen9championsvgc2026regmc-2714429391.json")
        self.assertEqual(rec["mega"], {"p1": "Staraptor-Mega", "p2": "Golisopod-Mega"})
        self.assertEqual(rec["mega_turn"], {"p1": 1, "p2": 1})
        # Pelipper's Rain on turn 2, Tyranitar's Sand on turn 3, both again on turn 6, gone on turn 11
        self.assertEqual(rec["weather"][:2], [[2, "RainDance", "p2", "Pelipper"], [3, "Sandstorm", "p1", "Tyranitar"]])
        self.assertEqual(rec["weather"][-1], [11, "none", None, None])
        self.assertEqual(len(rec["weather"]), 5)                       # [upkeep] lines aren't changes
        self.assertIn([3, "sidestart", "Tailwind", "p1", "Staraptor"], rec["field"])
        self.assertIn([6, "sideend", "Tailwind", "p1", None], rec["field"])
        bo3 = load("gen9championsvgc2026regmcbo3-2714431328.json")
        self.assertEqual(bo3["mega_turn"], {"p1": None, "p2": None})   # no Megas that game
        self.assertEqual(bo3["weather"], [])
        self.assertEqual(bo3["field"][:2], [[1, "sidestart", "Tailwind", "p1", "Gliscor"],
                                            [1, "sidestart", "Tailwind", "p2", "Gliscor"]])

    def test_weather_from_a_move_and_trick_room(self):
        log = "\n".join([
            "|player|p1|A|1|1500", "|player|p2|B|2|1500",
            "|poke|p1|Torkoal, L50|", "|poke|p1|Indeedee-F, L50|", "|poke|p2|Froslass, L50|", "|poke|p2|Kingambit, L50|",
            "|start", "|switch|p1a: T|Torkoal, L50|100/100", "|switch|p1b: I|Indeedee-F, L50|100/100",
            "|switch|p2a: F|Froslass, L50|100/100", "|switch|p2b: K|Kingambit, L50|100/100",
            "|-weather|SunnyDay|[from] ability: Drought|[of] p1a: T",
            "|-fieldstart|move: Psychic Terrain|[from] ability: Psychic Surge|[of] p1b: I",
            "|turn|1",
            "|move|p1b: I|Trick Room|p1b: I", "|-fieldstart|move: Trick Room|[of] p1b: I",
            "|move|p2a: F|Protect|p2a: F",
            "|turn|2",
            "|detailschange|p2a: F|Froslass-Mega, L50", "|-mega|p2a: F|Froslass|Froslassite",
            "|-weather|Snow|[from] ability: Snow Warning|[of] p2a: F",
            "|move|p2a: F|Snowscape|p2a: F", "|-weather|Snow",
            "|win|B",
        ])
        rec = parse_log(log)
        self.assertEqual(rec["mega_turn"], {"p1": None, "p2": 2})     # Protect turn 1, Mega Evolved turn 2
        self.assertEqual(rec["weather"], [[0, "SunnyDay", "p1", "Torkoal"], [2, "Snow", "p2", "Froslass"],
                                          [2, "Snow", "p2", "Froslass"]])   # the last from a move: its user
        self.assertEqual(rec["field"], [[0, "fieldstart", "Psychic Terrain", "p1", "Indeedee-F"],
                                        [1, "fieldstart", "Trick Room", "p1", "Indeedee-F"]])

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
