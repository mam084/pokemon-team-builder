"""My teams (ui/team_store.py, Team tab) and Compare's saved version in the link (ui/url_state.py)."""

import json
import unittest

from streamlit.testing.v1 import AppTest

from tests.test_app import APP, click, open_tab
from ui.team_store import MAX_TEAMS, NAME_MAX, _clean

FMT = "gen9championsvgc2026regmc"


class TestClean(unittest.TestCase):
    def test_keeps_only_well_formed_entries(self):
        raw = json.dumps({"ok": {"team": "abc", "f": FMT, "saved": "2026-11-20T10:00"},
                          "no team": {"f": FMT}, "bad": "x", "n" * 80: {"team": "t", "f": FMT}})
        out = _clean(raw)
        self.assertEqual(list(out), ["ok", "n" * NAME_MAX])
        self.assertEqual(out["ok"]["saved"], "2026-11-20")
        for junk in ["", "not json", "[1, 2]", None, 5]:
            self.assertEqual(_clean(junk), {})
        many = json.dumps({f"t{i}": {"team": "t", "f": FMT} for i in range(MAX_TEAMS + 10)})
        self.assertEqual(len(_clean(many)), MAX_TEAMS)


def with_store(teams=None) -> AppTest:
    """The app with the browser's list already read (AppTest has no browser for the component)."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["my_teams"] = dict(teams or {})
    return at.run()


class TestMyTeams(unittest.TestCase):
    def test_save_load_delete(self):
        at = click(with_store(), label="Example team")
        self.assertFalse(at.exception)
        at.text_input(key="my_team_name").input("Sun main").run()
        click(at, key="my_team_save")
        saved = at.session_state["my_teams"]
        self.assertEqual(list(saved), ["Sun main"])
        self.assertEqual(saved["Sun main"]["f"], FMT)
        write = at.session_state["my_teams_write"]
        from ui.team_store import STORAGE_KEY
        self.assertEqual(json.loads(write["writes"][STORAGE_KEY]), saved)          # what the browser is told to keep
        species = [at.session_state[f"s{i}_species"] for i in range(6)]

        click(at, label="Clear team")
        from ui.common import NONE
        self.assertEqual(at.session_state["s0_species"], NONE)
        click(at, key="my_team_load")
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], species)
        self.assertTrue(any("Loaded “Sun main”" in s.value for s in at.success))

        click(at, key="my_team_delete")
        self.assertEqual(at.session_state["my_teams"], {})
        self.assertGreater(at.session_state["my_teams_write"]["write_id"], write["write_id"])

    def test_blank_name_uses_the_suggestion_and_resave_replaces(self):
        at = click(with_store(), label="Example team")
        click(at, key="my_team_save")
        click(at, key="my_team_save")
        self.assertEqual(list(at.session_state["my_teams"]), ["Aerodactyl + Sylveon + …"])

    def test_waits_for_the_browser_list(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Reading the teams saved" in c.value for c in at.caption))


class TestSavedVersionInLink(unittest.TestCase):
    def test_round_trip(self):
        at = open_tab(click(with_store(), label="Example team"), "Matchups")
        click(at, key="save_version")
        click(at, key="find_swaps")
        swap = next(b for b in at.button if b.key and b.key.startswith(("swap_", "alt_")))
        swap.click().run()
        params = dict(at.query_params)
        self.assertIn("v", params)
        self.assertEqual(params["vl"], ["saved version"] if isinstance(params["vl"], list) else "saved version")

        flat = {k: (v[0] if isinstance(v, list) else v) for k, v in params.items()}
        again = AppTest.from_file(APP, default_timeout=120)
        again.query_params.update(flat)
        again.session_state["my_teams"] = {}
        again.run()
        again = open_tab(again, "Matchups")
        self.assertFalse(again.exception)
        md = " ".join(m.value for m in again.markdown)
        self.assertIn("Now vs saved version", md)

    def test_no_v_when_same_as_team(self):
        at = open_tab(click(with_store(), label="Example team"), "Matchups")
        click(at, key="save_version")
        self.assertNotIn("v", dict(at.query_params))


if __name__ == "__main__":
    unittest.main()
