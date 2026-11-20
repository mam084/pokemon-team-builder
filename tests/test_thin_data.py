"""The 'Little data on X' note (src/core_report.thin_data / thin_note; scripts/thin_core_lab.py)."""

import unittest

import numpy as np

from src.core_report import THIN_EVIDENCE, thin_data, thin_note
from src.dex import load_dex
from src.synergy import TeammateModel
from src.usage import load_usage


class TestThinData(unittest.TestCase):
    def model(self, counts):
        m = TeammateModel(list(counts))
        m.counts = np.array(list(counts.values()), dtype=float)
        return m

    def test_threshold_and_bins(self):
        m = self.model({"a": 50, "b": 150, "c": 300, "d": THIN_EVIDENCE, "e": 5000})
        self.assertEqual(thin_data("a", m)["top10"], 0.55)
        self.assertEqual(thin_data("b", m)["top10"], 0.59)
        self.assertEqual(thin_data("c", m)["top10"], 0.70)
        self.assertIsNone(thin_data("d", m))
        self.assertIsNone(thin_data("e", m))
        self.assertEqual(thin_data("unknown", m)["evidence"], 0.0)   # never seen: thinnest
        self.assertIsNone(thin_data("a", None))

    def test_note_wording(self):
        thin = {"evidence": 150, "top10": 0.59, "overall": 0.87}
        text = thin_note("Feraligatr-Mega", thin, 7, 4, 103)
        self.assertIn("7 tournament teams from 4 players, 103 rated games", text)
        self.assertIn("about 59% of the time (87% overall)", text)
        self.assertIn("Pokémon tab", text)
        self.assertIn("no tournament teams", thin_note("Glalie-Mega", thin, 0, 0, 56))
        self.assertIn("1 tournament team,", thin_note("X", thin, 1, 1, 10))
        short = thin_note("X", thin, point_to_tab=False)
        self.assertNotIn("(", short.split(".")[0])
        self.assertNotIn("Pokémon tab", short)

    def test_real_data(self):
        usage, dex = load_usage("gen9championsvgc2026regmc"), load_dex("regmc")
        root = lambda n: dex.sheet_id(dex.get_species(n))  # noqa: E731
        self.assertIsNotNone(thin_data(root("Feraligatr"), usage.teammates))
        self.assertIsNone(thin_data(root("Incineroar"), usage.teammates))


if __name__ == "__main__":
    unittest.main()
