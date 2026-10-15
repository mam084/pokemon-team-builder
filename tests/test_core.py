"""
Unit tests for the type chart, name normalization, and teammate recommender.

Run with:
    python -m unittest discover -s tests -v
"""

import unittest

import pandas as pd

from src.name_utils import normalize_name
from src.recommend import recommend_teammates
from src.type_chart import ALL_TYPES, defensive_multiplier, get_multiplier, team_weaknesses


# Gen 6+ type chart, written out independently of src/type_chart.py so the
# two can be checked against each other.
SUPER_EFFECTIVE = {
    "normal": [], "fire": ["grass", "ice", "bug", "steel"], "water": ["fire", "ground", "rock"],
    "electric": ["water", "flying"], "grass": ["water", "ground", "rock"],
    "ice": ["grass", "ground", "flying", "dragon"], "fighting": ["normal", "ice", "rock", "dark", "steel"],
    "poison": ["grass", "fairy"], "ground": ["fire", "electric", "poison", "rock", "steel"],
    "flying": ["grass", "fighting", "bug"], "psychic": ["fighting", "poison"],
    "bug": ["grass", "psychic", "dark"], "rock": ["fire", "ice", "flying", "bug"],
    "ghost": ["psychic", "ghost"], "dragon": ["dragon"], "dark": ["psychic", "ghost"],
    "steel": ["ice", "rock", "fairy"], "fairy": ["fighting", "dragon", "dark"],
}
NOT_VERY_EFFECTIVE = {
    "normal": ["rock", "steel"], "fire": ["fire", "water", "rock", "dragon"],
    "water": ["water", "grass", "dragon"], "electric": ["electric", "grass", "dragon"],
    "grass": ["fire", "grass", "poison", "flying", "bug", "dragon", "steel"],
    "ice": ["fire", "water", "ice", "steel"], "fighting": ["poison", "flying", "psychic", "bug", "fairy"],
    "poison": ["poison", "ground", "rock", "ghost"], "ground": ["grass", "bug"],
    "flying": ["electric", "rock", "steel"], "psychic": ["psychic", "steel"],
    "bug": ["fire", "fighting", "poison", "flying", "ghost", "steel", "fairy"],
    "rock": ["fighting", "ground", "steel"], "ghost": ["dark"], "dragon": ["steel"],
    "dark": ["fighting", "dark", "fairy"], "steel": ["fire", "water", "electric", "steel"],
    "fairy": ["fire", "poison", "steel"],
}
IMMUNE = {
    "normal": ["ghost"], "electric": ["ground"], "fighting": ["ghost"], "poison": ["steel"],
    "ground": ["flying"], "psychic": ["dark"], "ghost": ["normal"], "dragon": ["fairy"],
}


class TestTypeChart(unittest.TestCase):
    def test_every_matchup_matches_reference_chart(self):
        for attacking in ALL_TYPES:
            for defending in ALL_TYPES:
                if defending in SUPER_EFFECTIVE[attacking]:
                    expected = 2.0
                elif defending in NOT_VERY_EFFECTIVE[attacking]:
                    expected = 0.5
                elif defending in IMMUNE.get(attacking, []):
                    expected = 0.0
                else:
                    expected = 1.0
                with self.subTest(attacking=attacking, defending=defending):
                    self.assertEqual(get_multiplier(attacking, defending), expected)

    def test_eighteen_types(self):
        self.assertEqual(len(ALL_TYPES), 18)
        self.assertIn("fairy", ALL_TYPES)

    def test_single_type_matchups(self):
        self.assertEqual(get_multiplier("water", "fire"), 2.0)
        self.assertEqual(get_multiplier("fire", "water"), 0.5)
        self.assertEqual(get_multiplier("normal", "normal"), 1.0)

    def test_immunities(self):
        self.assertEqual(get_multiplier("ground", "flying"), 0.0)
        self.assertEqual(get_multiplier("ghost", "normal"), 0.0)
        self.assertEqual(get_multiplier("dragon", "fairy"), 0.0)

    def test_dual_types_multiply(self):
        # Ice is 4x against Grass/Ground (e.g. Torterra)
        self.assertEqual(defensive_multiplier(["grass", "ground"], "ice"), 4.0)
        # Electric does nothing to Water/Ground (e.g. Swampert): 2x * 0x
        self.assertEqual(defensive_multiplier(["water", "ground"], "electric"), 0.0)
        # Fire is neutral against Water/Grass: 0.5x * 2x
        self.assertEqual(defensive_multiplier(["water", "grass"], "fire"), 1.0)

    def test_team_weaknesses_shape(self):
        team = [["fire"], ["water", "flying"], ["steel", "fairy"]]
        result = team_weaknesses(team)
        self.assertEqual(set(result), set(ALL_TYPES))
        self.assertTrue(all(len(v) == len(team) for v in result.values()))
        self.assertEqual(result["electric"], [1.0, 4.0, 1.0])


class TestNormalizeName(unittest.TestCase):
    def test_pokeapi_and_smogon_names_match(self):
        pairs = [
            ("ogerpon-wellspring", "Ogerpon-Wellspring"),
            ("tapu-koko", "Tapu Koko"),
            ("mr-mime", "Mr. Mime"),
            ("farfetchd", "Farfetch'd"),
            ("type-null", "Type: Null"),
        ]
        for pokeapi, smogon in pairs:
            with self.subTest(smogon=smogon):
                self.assertEqual(normalize_name(pokeapi), normalize_name(smogon))


class TestRecommendTeammates(unittest.TestCase):
    def setUp(self):
        rows = [
            ("Great Tusk", "Gholdengo", 30.0),
            ("Great Tusk", "Kingambit", 25.0),
            ("Great Tusk", "Dragapult", 10.0),
            ("Kingambit", "Gholdengo", 20.0),
            ("Kingambit", "Great Tusk", 28.0),
        ]
        df = pd.DataFrame(rows, columns=["pokemon", "teammate", "co_occurrence_pct"])
        df["name_key"] = df["pokemon"].map(normalize_name)
        self.df = df

    def test_scores_sum_across_team_members(self):
        recs = recommend_teammates(self.df, ["great tusk", "kingambit"])
        top = recs[0]
        self.assertEqual(top["name"], "Gholdengo")
        self.assertEqual(top["score"], 50.0)
        self.assertEqual(len(top["paired_with"]), 2)

    def test_excludes_pokemon_already_on_team(self):
        recs = recommend_teammates(self.df, ["great tusk", "kingambit"])
        names = {r["name"] for r in recs}
        self.assertNotIn("Kingambit", names)
        self.assertNotIn("Great Tusk", names)

    def test_top_n_and_ordering(self):
        recs = recommend_teammates(self.df, ["great tusk"], top_n=2)
        self.assertEqual([r["name"] for r in recs], ["Gholdengo", "Kingambit"])

    def test_unknown_pokemon_returns_empty(self):
        self.assertEqual(recommend_teammates(self.df, ["missingno"]), [])


if __name__ == "__main__":
    unittest.main()
