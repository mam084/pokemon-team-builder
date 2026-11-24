"""
Core tests: type chart, Champions stat math, paste round-trips, legality,
usage parsing and analysis. Recommender and matchups: test_recommend.py; builder,
swaps and the learned models: test_builder_swaps.py.

The dex tests run against the real exported data in data/dex/, so they also
catch a broken or stale export. Usage tests use a small synthetic file in
tests/fixtures/ laid out exactly like Smogon's chaos JSON.

Run with:  python -m unittest discover -s tests -v
"""

import json
import unittest
from pathlib import Path

from src.analysis import (build_members, offense_by_type, coverage_vs_meta, defense_matrix, defense_summary, role_checklist,
                          speed_table)
from src.dex import load_dex, to_id
from src.legality import check_team, is_legal
from src.paste import export_paste, parse_paste
from src.matchup import threat_report
from src.stats import calc_stat, calc_stats, parse_spread, sp_problems
from src.team import PokemonSet
from src.type_chart import (ALL_TYPES, ability_defensive_multiplier, defensive_multiplier,
                            get_multiplier)
from src.usage import UsageData, trim_chaos

FIXTURES = Path(__file__).resolve().parent / "fixtures"

GARGANACL_TEAM = """
Garganacl @ Leftovers
Ability: Purifying Salt
Level: 50
EVs: 32 HP / 2 Def / 32 SpD
Careful Nature
- Salt Cure
- Body Press
- Iron Defense
- Wide Guard

Chompy (Garchomp) (F) @ Garchompite Z
Ability: Rough Skin
Level: 50
EVs: 2 HP / 32 SpA / 32 Spe
Timid Nature
- Draco Meteor
- Earth Power
- Flamethrower
- Protect

Rillaboom @ Miracle Seed
Ability: Grassy Surge
Level: 50
EVs: 32 HP / 32 Atk / 2 SpD
Adamant Nature
- Fake Out
- Grassy Glide
- Wood Hammer
- U-turn

Sinistcha @ Mental Herb
Ability: Hospitality
Level: 50
EVs: 32 HP / 32 Def / 2 SpD
Bold Nature
- Matcha Gotcha
- Rage Powder
- Strength Sap
- Protect

Incineroar @ Sitrus Berry
Ability: Intimidate
Level: 50
EVs: 32 HP / 2 Atk / 32 SpD
Careful Nature
- Fake Out
- Flare Blitz
- Parting Shot
- Throat Chop

Gholdengo @ Life Orb
Ability: Good as Gold
Level: 50
EVs: 2 HP / 32 SpA / 32 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Nasty Plot
- Protect
"""


def sample_usage() -> UsageData:
    raw = json.loads((FIXTURES / "chaos_sample.json").read_text())
    return UsageData(trim_chaos(raw, fmt="gen9championsvgc2026regmc", month="2026-10", cutoff=1630))


class TestTypeChart(unittest.TestCase):
    def test_basic_matchups(self):
        self.assertEqual(get_multiplier("fire", "grass"), 2.0)
        self.assertEqual(get_multiplier("water", "fire"), 2.0)
        self.assertEqual(get_multiplier("fire", "water"), 0.5)
        self.assertEqual(get_multiplier("fire", "fire"), 0.5)
        self.assertEqual(get_multiplier("normal", "normal"), 1.0)

    def test_immunities(self):
        self.assertEqual(get_multiplier("normal", "ghost"), 0.0)
        self.assertEqual(get_multiplier("ghost", "normal"), 0.0)
        self.assertEqual(get_multiplier("ground", "flying"), 0.0)
        self.assertEqual(get_multiplier("electric", "ground"), 0.0)
        self.assertEqual(get_multiplier("psychic", "dark"), 0.0)
        self.assertEqual(get_multiplier("dragon", "fairy"), 0.0)
        self.assertEqual(get_multiplier("poison", "steel"), 0.0)
        self.assertEqual(get_multiplier("fighting", "ghost"), 0.0)

    def test_dual_types(self):
        self.assertEqual(defensive_multiplier(["grass", "flying"], "ice"), 4.0)
        self.assertEqual(defensive_multiplier(["water", "ground"], "grass"), 4.0)
        self.assertEqual(defensive_multiplier(["water", "ground"], "electric"), 0.0)

    def test_matches_showdown_type_chart(self):
        """Our hand-written chart must agree with the one exported from Showdown."""
        chart = load_dex("regmc").typechart
        for atk in ALL_TYPES:
            for dfn in ALL_TYPES:
                self.assertEqual(get_multiplier(atk, dfn), chart[atk.title()][dfn.title()], (atk, dfn))

    def test_abilities(self):
        self.assertEqual(ability_defensive_multiplier(["dragon"], "ground", "levitate"), 0.0)
        self.assertEqual(ability_defensive_multiplier(["rock"], "ghost", "purifyingsalt"), 0.5)
        self.assertEqual(ability_defensive_multiplier(["fire", "dark"], "water", "intimidate"), 2.0)


class TestVariablePower(unittest.TestCase):
    """Weight-, Speed- and HP-based moves (the dex lists them at base power 0). Rules match Pokemon
    Showdown's basePowerCallback: 500 random weight/Speed pairs agreed when this was written."""

    @staticmethod
    def battler(weight=100.0, spe=100, ability="", item=""):
        from types import SimpleNamespace
        from src.damage import Battler
        return Battler(form=SimpleNamespace(weightkg=weight), stats={"spe": spe}, ability=ability, item=item)

    def test_power_rules(self):
        from src.damage import variable_power
        b = self.battler
        self.assertEqual(variable_power({"id": "lowkick"}, b(), b(weight=240)), 120)    # Garganacl
        self.assertEqual(variable_power({"id": "grassknot"}, b(), b(weight=43)), 60)    # Sneasler
        self.assertEqual(variable_power({"id": "lowkick"}, b(), b(weight=9.9)), 20)
        self.assertEqual(variable_power({"id": "heavyslam"}, b(weight=500), b(weight=100)), 120)
        self.assertEqual(variable_power({"id": "heatcrash"}, b(weight=150), b(weight=100)), 40)
        self.assertEqual(variable_power({"id": "heavyslam"}, b(weight=150, ability="heavymetal"), b(weight=100)), 80)
        self.assertEqual(variable_power({"id": "lowkick"}, b(), b(weight=240, item="floatstone")), 100)
        self.assertEqual(variable_power({"id": "gyroball"}, b(spe=50), b(spe=200)), 101)
        self.assertEqual(variable_power({"id": "gyroball"}, b(spe=20), b(spe=300)), 150)
        self.assertEqual(variable_power({"id": "electroball"}, b(spe=200), b(spe=50)), 150)
        self.assertEqual(variable_power({"id": "electroball"}, b(spe=50, item="choicescarf"), b(spe=100)), 40)
        self.assertEqual(variable_power({"id": "reversal"}, b(), b()), 20)

    def test_low_kick_does_damage(self):
        dex = load_dex("regmc")
        if dex.get_species("Kingambit") is None or not dex.get_species("Kingambit").weightkg:
            self.skipTest("dex without weights")
        from src.damage import calc_sets
        king = PokemonSet(species="Kingambit", item="Black Glasses", ability="Defiant", nature="Adamant",
                          moves=["Low Kick"], sps={"atk": 32, "hp": 32})
        target = PokemonSet(species="Incineroar", ability="Intimidate", moves=["Fake Out"])
        result = calc_sets(king, target, "Low Kick", dex)
        self.assertGreater(min(result.rolls), 0)
        self.assertIn("80 base power", result.notes)   # Incineroar weighs 83 kg

    def test_pixilate_and_low_kick_coverage(self):
        dex = load_dex("regmc")
        team, _ = parse_paste("""Sylveon @ Fairy Feather
Ability: Pixilate
- Hyper Voice

Kingambit @ Black Glasses
Ability: Defiant
- Low Kick
""", dex)
        off = offense_by_type(build_members(team, dex))
        self.assertEqual(off.loc["Dark", "best"], 2.0)     # Pixilate Hyper Voice is Fairy
        self.assertEqual(off.loc["Normal", "best"], 2.0)   # Low Kick is Fighting


class TestStats(unittest.TestCase):
    def test_champions_formula(self):
        # Garganacl: HP 100 / Def 130 / SpD 90 / Spe 35, Careful 32 HP / 2 Def / 32 SpD
        careful = {"plus": "spd", "minus": "spa"}
        stats = calc_stats({"hp": 100, "atk": 100, "def": 130, "spa": 45, "spd": 90, "spe": 35},
                           {"hp": 32, "def": 2, "spd": 32}, careful)
        self.assertEqual(stats, {"hp": 207, "atk": 120, "def": 152, "spa": 58, "spd": 156, "spe": 55})

    def test_nature_truncates(self):
        self.assertEqual(calc_stat(151, 32, "spe", {"plus": "spe"}), 223)  # (151+32+20)*1.1 = 223.3
        self.assertEqual(calc_stat(35, 0, "spe", {"minus": "spe"}), 49)    # 55*0.9 = 49.5

    def test_sp_limits(self):
        self.assertEqual(sp_problems({"hp": 32, "def": 2, "spd": 32}), [])
        self.assertTrue(sp_problems({"hp": 33}))
        self.assertTrue(sp_problems({"hp": 32, "def": 32, "spd": 32}))

    def test_parse_spread(self):
        nature, sps = parse_spread("Careful:32/0/2/0/32/0")
        self.assertEqual(nature, "Careful")
        self.assertEqual(sps, {"hp": 32, "atk": 0, "def": 2, "spa": 0, "spd": 32, "spe": 0})


class TestDex(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")

    def test_ids(self):
        self.assertEqual(to_id("Rotom-Wash"), "rotomwash")
        self.assertEqual(to_id("Farfetch’d"), "farfetchd")

    def test_mega_forms(self):
        form = self.dex.battle_form("Garchomp", "Garchompite Z")
        self.assertEqual(form.name, "Garchomp-Mega-Z")
        self.assertEqual(self.dex.battle_form("Garchomp", "Leftovers").name, "Garchomp")
        self.assertIn("Charizardite Y", self.dex.mega_options("Charizard"))

    def test_selectable_excludes_battle_forms(self):
        names = {s.name for s in self.dex.selectable_species()}
        self.assertIn("Garganacl", names)
        self.assertNotIn("Garchomp-Mega-Z", names)
        self.assertNotIn("Palafin-Hero", names)

    def test_items_hide_other_stones(self):
        items = self.dex.legal_items("Garganacl")
        self.assertIn("Leftovers", items)
        self.assertNotIn("Charizardite Y", items)

    def test_learnsets(self):
        self.assertTrue(self.dex.can_learn("Garganacl", "Salt Cure"))
        self.assertFalse(self.dex.can_learn("Garganacl", "Spore"))


class TestPasteAndLegality(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")

    def test_parse(self):
        team, warnings = parse_paste(GARGANACL_TEAM, self.dex)
        self.assertEqual(warnings, [])
        self.assertEqual(len(team), 6)
        chomp = team[1]
        self.assertEqual((chomp.species, chomp.nickname, chomp.item), ("Garchomp", "Chompy", "Garchompite Z"))
        self.assertEqual(team[0].sps["spd"], 32)
        self.assertEqual(team[0].moves[0], "Salt Cure")

    def test_round_trip(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        again, _ = parse_paste(export_paste(team), self.dex)
        self.assertEqual([p.to_dict() for p in team], [p.to_dict() for p in again])

    def test_mega_name_in_paste(self):
        team, _ = parse_paste("Garchomp-Mega-Z\nAbility: Levitate\n- Protect", self.dex)
        self.assertEqual((team[0].species, team[0].item), ("Garchomp", "Garchompite Z"))

    def test_sample_team_is_legal(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        self.assertTrue(is_legal(team, self.dex), check_team(team, self.dex))

    def test_clauses_and_limits(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        team[2].item = "Leftovers"                # duplicate item
        team[3].sps = {**team[3].sps, "spe": 32}  # 98 SP
        team[4].moves[0] = "Spore"                # can't learn
        messages = " ".join(i.message for i in check_team(team, self.dex) if i.level == "error")
        self.assertIn("Item Clause", messages)
        self.assertIn("Stat Points", messages)
        self.assertIn("can't learn Spore", messages)

    def test_mega_count(self):
        two = [PokemonSet("Garchomp", item="Garchompite Z"), PokemonSet("Charizard", item="Charizardite Y")]
        self.assertFalse(any("Mega Stones" in i.message for i in check_team(two, self.dex)))  # normal
        three = two + [PokemonSet("Froslass", item="Froslassite")]
        self.assertTrue(any("only one can Mega Evolve" in i.message for i in check_team(three, self.dex)))


class TestUsage(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.usage = sample_usage()

    def test_trim(self):
        self.assertEqual(self.usage.info["battles"], 12345)
        self.assertNotIn("Rare Mon", self.usage.pokemon)       # below the usage floor
        self.assertEqual(self.usage.ranked(1)[0][0], "Rillaboom")
        self.assertAlmostEqual(self.usage.section("Garganacl", "items")["leftovers"], 70.0)

    def test_teammates_and_lift(self):
        self.assertAlmostEqual(self.usage.teammate_pct("Garganacl", "Rillaboom"), 60.0)
        self.assertAlmostEqual(self.usage.lift("Garganacl", "Sinistcha"), 5.0)

    def test_pair_lift(self):
        lift, known = self.usage.pair_lift("Garganacl", "Sinistcha")
        self.assertTrue(known)
        self.assertGreater(lift, 1.5)                        # 5x raw, shrunk a little
        self.assertLess(lift, 5.0)
        lift, known = self.usage.pair_lift("Sneasler", "Politoed")  # in neither top list
        self.assertFalse(known)
        self.assertLessEqual(lift, 1.0)

    def test_popular_set_respects_item_clause(self):
        pset = self.usage.popular_set("Garganacl", self.dex, taken_items={"Leftovers"})
        self.assertEqual(pset.item, "Sitrus Berry")
        self.assertEqual(pset.nature, "Careful")
        self.assertEqual(len(pset.moves), 4)
        self.assertTrue(all(self.dex.can_learn("Garganacl", m) for m in pset.moves))


class TestAnalysis(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.usage = sample_usage()
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        self.members = build_members(team, self.dex)

    def test_megas_and_abilities_applied(self):
        matrix = defense_matrix(self.members)
        self.assertIn("Garchomp-Mega-Z", matrix.columns)
        self.assertEqual(matrix.loc["Ground", "Garchomp-Mega-Z"], 0.0)      # Levitate
        self.assertEqual(matrix.loc["Ghost", "Garganacl"], 0.5)             # Purifying Salt
        self.assertEqual(defense_summary(matrix).loc["Fighting", "immune"], 2)  # Sinistcha, Gholdengo

    def test_roles(self):
        roles = role_checklist(self.members, doubles=True).set_index("role")
        self.assertIn("Rillaboom", roles.loc["Fake Out", "covered by"])
        self.assertIn("Sinistcha", roles.loc["Redirection", "covered by"])
        self.assertIn("Incineroar", roles.loc["Intimidate / Attack drops", "covered by"])
        singles = role_checklist(self.members, doubles=False)
        self.assertNotIn("Fake Out", set(singles["role"]))

    def test_speed_and_meta_views(self):
        speeds = speed_table(self.members, self.dex, self.usage)
        mine = speeds[speeds["pokemon"] == "Garchomp-Mega-Z (yours)"]["speed"].iloc[0]
        self.assertEqual(mine, 223)
        # popular Pokémon faster than your fastest are shown too (here: Choice Scarf users)
        faster = speeds[speeds["speed"] > mine]
        self.assertTrue(len(faster) and faster["pokemon"].str.contains("Scarf").all())
        cover = coverage_vs_meta(self.members, self.dex, self.usage, n=5)
        self.assertEqual(len(cover), 5)

    def test_threats(self):
        threats = threat_report(self.members, self.usage, self.dex)
        sneasler = threats.set_index("pokemon").loc["Sneasler"]
        self.assertIn("Close Combat", sneasler["hardest hits"])       # damage-based, names the move
        self.assertGreater(sneasler["2HKOs"], 0)
        self.assertGreater(len(threats), 5)

if __name__ == "__main__":
    unittest.main()
