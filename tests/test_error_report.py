"""Automatic error reports (src/error_report.py) and the tab guard in app.py, with GitHub mocked out."""

import os
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import error_report

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def boom():
    from src.dex import load_dex
    load_dex("regmc").species["not-a-pokemon"]   # KeyError from this repo's code


class TestErrorReport(unittest.TestCase):
    def setUp(self):
        error_report._sent.clear()

    def raised(self) -> BaseException:
        try:
            boom()
        except KeyError as e:
            return e

    def test_signature_names_the_tab_type_and_line(self):
        sig = error_report.signature("Matchups", self.raised())
        self.assertRegex(sig, r"^Matchups: KeyError at tests/test_error_report\.py:\d+$")

    def test_new_error_opens_an_issue_and_a_repeat_comments(self):
        calls = []

        def fake_api(token, method, path, data=None):
            calls.append((method, path, data))
            if path.startswith("/search/issues"):
                opened = [c for c in calls if c[0] == "POST" and c[1].endswith("/issues")]
                return {"items": [{"title": opened[0][2]["title"], "number": 7}] if opened else []}
            return {}

        with mock.patch.object(error_report, "_api", fake_api), \
                mock.patch.object(error_report.threading, "Thread") as thread:
            thread.side_effect = lambda target, args, daemon: mock.Mock(start=lambda: target(*args))
            self.assertTrue(error_report.report("Matchups", self.raised(), "https://x/?team=abc", "tok"))
            self.assertFalse(error_report.report("Matchups", self.raised(), "", "tok"))   # within the hour
            error_report._sent.clear()
            self.assertTrue(error_report.report("Matchups", self.raised(), "", "tok"))
        posts = [c for c in calls if c[0] == "POST"]
        self.assertTrue(posts[0][1].endswith("/issues"))
        self.assertEqual(posts[0][2]["labels"], ["app-error"])
        self.assertIn("https://x/?team=abc", posts[0][2]["body"])
        self.assertTrue(posts[1][1].endswith("/issues/7/comments"))

    def test_no_token_only_logs(self):
        with mock.patch.object(error_report, "_api") as api:
            self.assertFalse(error_report.report("Team", self.raised(), "", None))
        api.assert_not_called()

    def test_github_failure_never_raises(self):
        with mock.patch.object(error_report, "_api", side_effect=OSError("offline")):
            error_report._send("tok", "sig", "body")   # logged, not raised


class TestTabGuard(unittest.TestCase):
    def test_broken_tab_shows_a_message_and_other_tabs_work(self):
        import ui.playbook_tab as pb
        old = os.environ.pop("PTB_RAISE", None)
        try:
            with mock.patch.object(pb, "playbook_tab", side_effect=ValueError("simulated")), \
                    mock.patch("src.error_report.report") as report:
                at = AppTest.from_file(APP, default_timeout=120).run()
                at.session_state["main_tabs"] = "Playbook"
                at.run()
                self.assertFalse(at.exception)
                self.assertTrue(any("Playbook tab hit a problem" in e.value for e in at.error))
                report.assert_called_once()
                at.session_state["main_tabs"] = "Analysis"
                at.run()
                self.assertFalse(at.exception)
                self.assertFalse(at.error)
        finally:
            if old is not None:
                os.environ["PTB_RAISE"] = old


if __name__ == "__main__":
    unittest.main()
