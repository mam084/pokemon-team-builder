"""Start here card, feedback link (ui/start_here.py) and prefs in browser storage (ui/team_store.py)."""

import json
import unittest

from streamlit.testing.v1 import AppTest

from tests.test_app import APP, click
from ui.start_here import FEEDBACK_URL, HIDDEN
from ui.team_store import PREFS_KEY, STORAGE_KEY, _clean_prefs


def visitor(prefs=None) -> AppTest:
    """A visitor whose browser storage has been read (AppTest has no browser for the component)."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["my_teams"] = {}
    at.session_state["my_prefs"] = dict(prefs or {})
    return at.run()


def text(at):
    return " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)


class TestStartHere(unittest.TestCase):
    def test_new_visitor_sees_it_and_example_replaces_it(self):
        at = visitor()
        self.assertFalse(at.exception)
        self.assertIn("Start here.", text(at))
        self.assertIn("Plan a game", text(at))
        click(at, key="start_example")
        self.assertNotIn("Start here.", text(at))                   # a team: the card is gone
        self.assertTrue(any("Next: the **Matchups** tab" in s.value for s in at.success))

    def test_hide_is_remembered(self):
        at = visitor()
        click(at, key="start_hide")
        self.assertNotIn("Start here.", text(at))
        writes = at.session_state["my_teams_write"]["writes"]
        self.assertEqual(json.loads(writes[PREFS_KEY]), {HIDDEN: True})
        self.assertEqual(json.loads(writes[STORAGE_KEY]), {})        # My teams untouched
        self.assertNotIn("Start here.", text(visitor({HIDDEN: True})))

    def test_waits_for_browser_storage(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        self.assertNotIn("Start here.", text(at))                   # not before we know it wasn't hidden

    def test_feedback_link_on_every_page(self):
        at = visitor()
        self.assertTrue(any(FEEDBACK_URL in c.value for c in at.caption))
        self.assertTrue(any(FEEDBACK_URL in c.value for c in at.sidebar.caption))

    def test_clean_prefs(self):
        self.assertEqual(_clean_prefs(json.dumps({"a": True, "b": "x", "c": 3, "d": False})),
                         {"a": True, "d": False})
        for junk in ["", "nope", "[1]", None]:
            self.assertEqual(_clean_prefs(junk), {})


if __name__ == "__main__":
    unittest.main()
