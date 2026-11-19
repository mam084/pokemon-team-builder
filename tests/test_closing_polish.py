"""Cosmetic formes in replays, sibling-forme sets, item/move fit, the sheet whole-set rule, turn 1."""

import unittest

from src.dex import load_dex
from src.replays import canonical, turn1_table
from src.usage import item_fits_moves, load_usage


class TestForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.usage = load_usage("gen9championsvgc2026regmc")

    def test_cosmetic_formes_count_as_their_base_in_replays(self):
        rec = {"preview": {"p1": ["Maushold-Four", "Sinistcha-Masterpiece"], "p2": ["Vivillon-Polar"]},
               "brought": {"p1": ["Maushold-Four"], "p2": []}, "leads": {"p1": ["Maushold-Four"], "p2": []},
               "moves": {"p1": {"Maushold-Four": {"Follow Me": 1}}, "p2": {}},
               "turn1": {"p1": [["Maushold-Four", "Follow Me", "Maushold-Four"]], "p2": []},
               "faints": [[3, "p1", "Maushold-Four"]], "sheets": {"p1": [{"species": "Maushold-Four"}]}}
        rec = canonical(rec)
        self.assertEqual(rec["preview"]["p1"], ["Maushold", "Sinistcha"])
        self.assertEqual(rec["preview"]["p2"], ["Vivillon"])
        self.assertEqual(list(rec["moves"]["p1"]), ["Maushold"])
        self.assertEqual(rec["turn1"]["p1"][0][0], "Maushold")
        self.assertEqual(rec["faints"][0][2], "Maushold")
        self.assertEqual(rec["sheets"]["p1"][0]["species"], "Maushold")

    def test_rare_forme_borrows_its_siblings_set(self):
        self.assertEqual(self.usage.sibling("Squawkabilly-Yellow", self.dex), "Squawkabilly")
        s = self.usage.popular_set("Squawkabilly-Yellow", self.dex)
        self.assertIsNotNone(s)
        self.assertEqual(s.species, "Squawkabilly-Yellow")
        self.assertIn(s.ability, self.dex.get_species("Squawkabilly-Yellow").abilities)
        self.assertIsNone(self.usage.sibling("Arcanine-Hisui", self.dex))  # different types and stats

    def test_choice_items_skip_protect(self):
        self.assertFalse(item_fits_moves("choicescarf", ["protect", "nightdaze"], self.dex))
        self.assertTrue(item_fits_moves("choicescarf", ["trick", "nightdaze"], self.dex))
        self.assertFalse(item_fits_moves("assaultvest", ["trick"], self.dex))
        self.assertTrue(item_fits_moves("lifeorb", ["protect"], self.dex))
        for name, _ in self.usage.ranked(80):
            p = self.usage.popular_set(name, self.dex)
            if p is not None and p.item:
                from src.dex import to_id
                self.assertTrue(item_fits_moves(to_id(p.item), [to_id(m) for m in p.moves], self.dex), (name, p))

    def test_whole_set_only_when_most_sheets_share_it(self):
        from src.sheet_sets import apply
        pset = self.usage._popular_set("Espeon", self.dex)
        sheets = {k: v for k, v in (self.usage.sheet_sets or {}).items()}
        from src.sheet_sets import sheet_key
        key = sheet_key(pset, self.dex)
        sheets[key] = {"n": 20, "mode": ["helpinghand", "protect", "psychic", "shadowball"], "mode_n": 3,
                       "top4": ["expandingforce", "protect", "shadowball", "psychic"]}
        self.assertIn("Expanding Force", apply(pset, self.dex, sheets).moves)
        sheets[key] = {**sheets[key], "mode_n": 12}
        self.assertIn("Helping Hand", apply(pset, self.dex, sheets).moves)


class TestTurn1(unittest.TestCase):
    def test_against_each_lead(self):
        def rec(move, their):
            return {"leads": {"p1": ["Incineroar", "Garchomp"], "p2": [their, "Kingambit"]},
                    "turn1": {"p1": [["Incineroar", move, their]], "p2": []}}
        recs = [rec("Fake Out", "Sneasler")] * 20 + [rec("Parting Shot", "Indeedee-F")] * 20
        t = turn1_table(recs, min_games=15)
        self.assertEqual(t["Incineroar"]["n"], 40)
        self.assertEqual(t["Incineroar"]["vs"]["Indeedee-F"]["moves"][0], ["Parting Shot", 1.0])
        self.assertEqual(t["Incineroar"]["vs"]["Sneasler"]["moves"][0], ["Fake Out", 1.0])
        self.assertNotIn("Garchomp", t)  # no turn-1 move recorded for it


if __name__ == "__main__":
    unittest.main()
