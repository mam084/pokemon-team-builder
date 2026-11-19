"""
A new regulation: noticing it on Showdown, switching src/formats.py to it, usage built from
replays before Smogon has stats, the health check's grace period, and the app on day one.
"""

import dataclasses
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PTB_WARMUP", "0")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from src.dex import load_dex  # noqa: E402
from src.formats import FORMATS  # noqa: E402
from src.replay_usage import usage_from_replays  # noqa: E402
from src.usage import UsageData  # noqa: E402

FORMATS_TS = '''
		name: "[Gen 9 Champions] BSS Reg M-C",
		name: "[Gen 9 Champions] BSS Reg M-D",
		name: "[Gen 9 Champions] VGC 2026 Reg M-C",
		name: "[Gen 9 Champions] VGC 2026 Reg M-C (Bo3)",
		name: "[Gen 9 Champions] VGC 2026 Reg M-D",
		name: "[Gen 9 Champions] VGC 2026 Reg M-D (Bo3)",
		name: "[Gen 9 Champions] Doubles Custom Game",
'''


def side(name, preview, brought=None, mega=None, moves=None, sheets=None, rating=1400):
    return name, rating, preview, brought or preview[:4], mega, moves or {}, sheets


def record(t, a, b):
    rec = {"uploadtime": t, "players": {}, "preview": {}, "brought": {}, "mega": {}, "moves": {}, "sheets": {}}
    for p, (name, rating, preview, brought, mega, moves, sheets) in zip(("p1", "p2"), (a, b)):
        rec["players"][p] = {"name": name, "rating": rating}
        rec["preview"][p], rec["brought"][p], rec["mega"][p], rec["moves"][p] = preview, brought, mega, moves
        if sheets:
            rec["sheets"][p] = sheets
    return rec


class TestDetectAndSwitch(unittest.TestCase):
    def test_finds_only_the_unknown_regulation(self):
        from new_regulation import new_regulations, showdown_formats
        found = showdown_formats(FORMATS_TS)
        self.assertEqual({f["id"] for f in found}, {"gen9championsbssregmc", "gen9championsbssregmd",
                                                     "gen9championsvgc2026regmc", "gen9championsvgc2026regmd"})
        new = new_regulations(found, set())
        self.assertEqual(list(new), ["regmd"])

    def test_add_switches_the_default_and_keeps_the_rest(self):
        from new_regulation import add_formats
        text = add_formats((ROOT / "src" / "formats.py").read_text(), "gen9championsvgc2026regmd", "2026-12-03",
                           bss="gen9championsbssregmd", limitless="M-D")
        ns: dict = {}
        exec(compile(text, "formats_new", "exec"), ns)
        f = ns["FORMATS"]
        self.assertEqual(ns["DEFAULT_FORMAT"], "gen9championsvgc2026regmd")
        new = f["gen9championsvgc2026regmd"]
        self.assertTrue(new.current)
        self.assertEqual((new.regulation, new.start, new.limitless, new.previous),
                         ("regmd", "2026-12-03", "M-D", "gen9championsvgc2026regmc"))
        self.assertEqual(new.replays, ("gen9championsvgc2026regmd", "gen9championsvgc2026regmdbo3"))
        self.assertTrue(f["gen9championsbssregmd"].current)
        self.assertFalse(f["gen9championsvgc2026regmc"].current)
        self.assertIn("past", f["gen9championsvgc2026regmc"].label)
        self.assertEqual(set(ns["replay_sources"]()), {"gen9championsvgc2026regmd", "gen9championsvgc2026regmdbo3"})
        self.assertEqual(len(f), len(FORMATS) + 2)


class TestReplayUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")

    def records(self, players=40):
        a = ["Charizard", "Venusaur", "Garchomp", "Incineroar", "Farigiraf", "Kingambit"]
        b = ["Sneasler", "Rillaboom", "Incineroar", "Kingambit", "Garchomp", "Basculegion"]
        sheet = [{"species": "Incineroar", "item": "Sitrus Berry", "ability": "Intimidate",
                  "moves": ["Fake Out", "Parting Shot", "Flare Blitz", "Knock Off"]}]
        out = []
        for i in range(players):
            out.append(record(1_800_000_000 + i,
                              side(f"a{i}", a, brought=a[:4], mega="Charizard-Mega-Y" if i % 2 else None,
                                   moves={"Charizard": {"Heat Wave": 2}}),
                              side(f"b{i}", b, sheets=sheet)))
        return out

    def test_shares_megas_and_set_sources(self):
        data = usage_from_replays(self.records(), self.dex, "x", min_teams=10)
        p = data["pokemon"]
        self.assertEqual(data["info"]["teams"], 80)
        self.assertAlmostEqual(p["Incineroar"]["usage"], 100.0)
        self.assertAlmostEqual(p["Sneasler"]["usage"], 50.0)
        # half of Charizard's teams Mega Evolved it: half its usage is the Mega's
        self.assertAlmostEqual(p["Charizard-Mega-Y"]["usage"], 25.0)
        self.assertAlmostEqual(p["Charizard"]["usage"], 25.0)
        self.assertEqual(p["Incineroar"]["set_source"], "sheets")
        self.assertEqual(list(p["Incineroar"]["items"]), ["sitrusberry"])
        self.assertEqual(p["Charizard"]["set_source"], "seen")
        self.assertIn("heatwave", p["Charizard"]["moves"])
        self.assertEqual(list(p["Charizard-Mega-Y"]["items"]), ["charizarditey"])
        self.assertAlmostEqual(p["Sneasler"]["teammates"]["Rillaboom"], 100.0)
        usage = UsageData(data)
        self.assertIsNotNone(usage.popular_set("Incineroar", self.dex))

    def test_previous_regulation_fills_sets(self):
        prev = UsageData({"info": {}, "pokemon": {"Garchomp": {
            "usage": 9, "raw_count": 9, "abilities": {"roughskin": 100}, "items": {"choicescarf": 60},
            "moves": {"earthquake": 90, "dragonclaw": 80}, "spreads": {"Jolly:2/32/0/0/0/32": 50},
            "teammates": {}, "counters": {}}}})
        p = usage_from_replays(self.records(), self.dex, "x", prev=prev, min_teams=10)["pokemon"]
        self.assertEqual(p["Garchomp"]["set_source"], "previous")
        self.assertEqual(p["Garchomp"]["spreads"], {"Jolly:2/32/0/0/0/32": 50})

    def test_too_few_teams(self):
        self.assertIsNone(usage_from_replays(self.records(5), self.dex, "x"))


class TestHealthGrace(unittest.TestCase):
    def test_missing_files_wait_in_a_new_regulation(self):
        import health_check
        import src.formats as formats
        saved = formats.CURRENT
        formats.CURRENT = dataclasses.replace(saved, id="gen9championsvgc2026regzz", regulation="regzz",
                                              start="2026-12-03", replays=())
        try:
            young = health_check.checks("regzz", now=datetime(2026, 12, 10, tzinfo=timezone.utc))
            old = health_check.checks("regzz", now=datetime(2027, 2, 10, tzinfo=timezone.utc))
        finally:
            formats.CURRENT = saved
        waits = [r for r in young if r[2].startswith(health_check.WAITING)]
        self.assertGreaterEqual(len(waits), 4)
        self.assertTrue(all(ok for _, ok, _ in waits))
        self.assertTrue(any(name == "Recommender beats popularity" and not ok for name, ok, _ in old))


class TestDayOne(unittest.TestCase):
    """The app on a regulation with a dex and a week of replays, but no Smogon stats, tournaments or
    learned models yet: every tab renders, with recommendations from replay-built usage."""

    FAKE = "gen9championsvgc2026regzz"

    @classmethod
    def setUpClass(cls):
        from src.replay_usage import path_for, usage_from_replays as build
        from src.replays import load_records
        cls.dex_path = ROOT / "data" / "dex" / "regzz.json"
        cls.dex_path.write_text((ROOT / "data" / "dex" / "regmc.json").read_text())
        src_fmt = FORMATS["gen9championsvgc2026regmc"]
        FORMATS[cls.FAKE] = dataclasses.replace(src_fmt, id=cls.FAKE, label="VGC 2026 Reg Z-Z (Doubles)",
                                                regulation="regzz", replays=(), limitless="",
                                                previous="gen9championsvgc2026regmc")
        records = [r for f in src_fmt.replays for r in load_records(f, days=2)]
        data = build(records, load_dex("regzz"), cls.FAKE)
        cls.usage_path = path_for(cls.FAKE)
        cls.usage_path.write_text(json.dumps(data))

    @classmethod
    def tearDownClass(cls):
        FORMATS.pop(cls.FAKE, None)
        for p in (cls.dex_path, cls.usage_path):
            p.unlink(missing_ok=True)

    def test_every_tab_renders_on_replay_usage(self):
        from streamlit.testing.v1 import AppTest
        from src.usage import load_usage
        usage = load_usage(self.FAKE)
        self.assertTrue(usage.from_replays)
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
        at.session_state["format"] = self.FAKE
        at = at.run()
        b = next(b for b in at.sidebar.button if b.label == "Example team")
        at = b.click().run()
        self.assertEqual(at.session_state["format"], self.FAKE)
        for tab in ["Analysis", "Matchups", "Playbook", "Damage calc", "Recommendations", "Pokémon"]:
            at.session_state["main_tabs"] = tab
            at = at.run()
            self.assertFalse(at.exception, (tab, [e.value for e in at.exception]))
            notes = " ".join(i.value for i in at.info)
            self.assertNotIn("needs usage stats", notes.lower(), tab)
        self.assertTrue(any("aren't out yet" in c.value for c in at.sidebar.caption))


if __name__ == "__main__":
    unittest.main()
