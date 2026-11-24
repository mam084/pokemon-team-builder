"""Team links: encoding round-trips, bad links fail softly, and the app restores and syncs the URL."""

import base64
import unittest
import zlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.dex import load_dex
from src.paste import parse_paste
from src.share import decode_team, encode_team
from tests.test_core import GARGANACL_TEAM

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class TestShareTokens(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.team, _ = parse_paste(GARGANACL_TEAM, self.dex)

    def test_round_trip(self):
        token = encode_team(self.team)
        self.assertLess(len(token), 800)                      # comfortably short for a URL
        self.assertTrue(all(c.isalnum() or c in "-_" for c in token))
        again, warnings = decode_team(token, self.dex)
        self.assertEqual(warnings, [])
        self.assertEqual([p.to_dict() for p in again], [p.to_dict() for p in self.team])

    def test_empty(self):
        self.assertEqual(encode_team([]), "")
        self.assertEqual(decode_team("", self.dex), ([], []))

    def test_bad_links_fail_softly(self):
        for token in ["not-a-real-token", "%%%", "A" * 5000, encode_team(self.team)[:-20]]:
            team, warnings = decode_team(token, self.dex)
            self.assertEqual(team, [], token[:20])
            self.assertTrue(warnings)

    def test_zip_bomb_refused(self):
        bomb = base64.urlsafe_b64encode(zlib.compress(b"A" * 5_000_000)).decode().rstrip("=")
        team, warnings = decode_team(bomb, self.dex)
        self.assertEqual(team, [])
        self.assertTrue(warnings)

    def test_illegal_content_is_reported(self):
        team, _ = parse_paste("Garganacl\n- Spore", self.dex)
        decoded, _ = decode_team(encode_team(team), self.dex)
        self.assertEqual(decoded[0].moves, ["Spore"])  # kept, and flagged by the legality checks in the app


    def test_bad_stat_points_dont_break_the_import(self):
        team, _ = parse_paste("Garchomp\nEVs: abc HP / 3.5 Def / 99999 Atk / -4 SpD / 32 Spe\n- Earthquake", self.dex)
        self.assertEqual({k: v for k, v in team[0].sps.items() if v}, {"atk": 255, "spe": 32})

    def test_markup_is_stripped_from_pastes_and_links(self):
        evil = "<img id=x src=y>"
        team, _ = parse_paste(f"{evil} (Garchomp) @ {evil}\n- {evil}", self.dex)
        decoded, _ = decode_team(encode_team(team), self.dex)
        for p in (team[0], decoded[0]):
            self.assertNotIn("<", p.nickname + p.item + "".join(p.moves))

    def test_compare_label_from_a_link_is_plain_text(self):
        from ui.url_state import clean_label
        self.assertEqual(clean_label("[Click](https://evil.com) v2 <b>"), "v2 b")
        self.assertEqual(clean_label(None), "saved version")

class TestAppUrl(unittest.TestCase):
    def test_link_loads_team_and_edits_update_url(self):
        dex = load_dex("regmc")
        team, _ = parse_paste(GARGANACL_TEAM, dex)
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["f"] = "gen9championsvgc2026regmc"
        at.query_params["team"] = encode_team(team)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.session_state["s0_species"], "Garganacl")
        self.assertEqual(at.session_state["s5_species"], "Gholdengo")

        remove = next(b for b in at.button if b.key == "s5_rm")
        at = remove.click().run()
        decoded, _ = decode_team(at.query_params["team"][0] if isinstance(at.query_params["team"], list)
                                 else at.query_params["team"], dex)
        self.assertEqual(len(decoded), 5)

    def test_broken_link_shows_warning(self):
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["team"] = "garbage"
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("link" in w.value for w in at.warning))  # in the page: the sidebar is hidden on a phone


    def test_pokemon_from_another_format_is_taken_off_not_a_crash(self):
        team, _ = parse_paste("Shedinja @ Focus Sash\n- Shadow Sneak\n\n" + GARGANACL_TEAM, load_dex("regmc"))
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["f"] = "gen9championsvgc2026regmc"
        at.query_params["team"] = encode_team(team)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Took Shedinja off" in w.value for w in at.warning))
        self.assertNotIn("Shedinja", at.query_params["team"][0] if at.query_params.get("team") else "")

    def test_switching_to_an_older_regulation_takes_off_newer_pokemon(self):
        team, _ = parse_paste("Salamence @ Salamencite\n- Hyper Voice\n\n" + GARGANACL_TEAM, load_dex("regmc"))
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["f"] = "gen9championsvgc2026regmc"
        at.query_params["team"] = encode_team(team)
        at.run()
        at.selectbox(key="format").set_value("gen9championsvgc2026regmb").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Took Salamence off" in w.value for w in at.warning))

if __name__ == "__main__":
    unittest.main()
