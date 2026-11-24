"""Anonymous usage counts (src/usage_counts.py) with GitHub mocked out, and what the app counts."""

import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import usage_counts as uc

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class FakeGitHub:
    def __init__(self, fail=False):
        self.issues, self.fail = {}, fail

    def __call__(self, token, method, path, data=None):
        if self.fail:
            raise OSError("offline")
        if path.startswith("/search/issues"):
            return {"items": [{"title": i["title"], "number": n, "body": i["body"]} for n, i in self.issues.items()]}
        if method == "POST":
            n = len(self.issues) + 1
            self.issues[n] = dict(data)
            return {"number": n}
        n = int(path.rsplit("/", 1)[1])
        if method == "PATCH":
            self.issues[n]["body"] = data["body"]
        return self.issues[n]


def run_now(target, args, daemon):
    return mock.Mock(start=lambda: target(*args))


class TestUsageCounts(unittest.TestCase):
    def setUp(self):
        uc._pending.clear()
        uc._issue_number = None

    def test_counts_open_one_issue_then_add_to_it(self):
        gh = FakeGitHub()
        with mock.patch.object(uc, "_api", gh), mock.patch.object(uc.threading, "Thread", side_effect=run_now), \
                mock.patch.object(uc.time, "strftime", return_value="2026-11-24"):
            for _ in range(3):
                uc.count("visits")
            uc.count("find swaps")
            self.assertTrue(uc.maybe_flush("tok", force=True))
            uc._issue_number = None          # a restarted app finds the issue again by title
            uc.count("visits")
            self.assertTrue(uc.maybe_flush("tok", force=True))
        self.assertEqual(len(gh.issues), 1)
        issue = gh.issues[1]
        self.assertEqual((issue["title"], issue["labels"]), ("App usage", ["app-usage"]))
        self.assertEqual(uc._parse(issue["body"]), {"2026-11-24": {"visits": 4, "find swaps": 1}})
        self.assertIn("| 2026-11-24 | 4 |", issue["body"])

    def test_failed_update_keeps_the_counts(self):
        with mock.patch.object(uc, "_api", FakeGitHub(fail=True)), \
                mock.patch.object(uc.threading, "Thread", side_effect=run_now):
            uc.count("visits")
            uc.maybe_flush("tok", force=True)
        self.assertEqual(sum(uc._pending.values()), 1)

    def test_nothing_goes_out_without_a_token_or_within_the_hour(self):
        uc.count("visits")
        with mock.patch.object(uc, "_api") as api:
            self.assertFalse(uc.maybe_flush(None, force=True))
            self.assertFalse(uc.maybe_flush("tok"))   # an hour hasn't passed since import
        api.assert_not_called()

    def test_app_counts_a_visit_once_and_each_tab_when_opened(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.run()
        for tab in ("Analysis", "Analysis", "Matchups"):
            at.session_state["main_tabs"] = tab
            at.run()
        counts = {e: n for (_, e), n in uc._pending.items()}
        self.assertEqual(counts.get("visits"), 1)
        self.assertEqual(counts.get("tab: Analysis"), 1)
        self.assertEqual(counts.get("tab: Matchups"), 1)

    def test_keep_awake_visits_dont_count(self):
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["keepawake"] = "1"
        at.run()
        self.assertNotIn("visits", {e for (_, e) in uc._pending})


if __name__ == "__main__":
    unittest.main()
