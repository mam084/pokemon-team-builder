"""
Core tests: type chart, Champions stat math, paste round-trips, legality,
usage parsing, analysis and the recommender.

The dex tests run against the real exported data in data/dex/, so they also
catch a broken or stale export. Usage tests use a small synthetic file in
tests/fixtures/ laid out exactly like Smogon's chaos JSON.

Run with:  python -m unittest discover -s tests -v
"""

import json
import unittest
from pathlib import Path

from src.analysis import (build_members, coverage_vs_meta, defense_matrix, defense_summary,
                          role_checklist, speed_table, threat_report)
from src.dex import load_dex, to_id
from src.legality import check_team, is_legal
from src.paste import export_paste, parse_paste
from src.matchup import (best_bring, build_archetypes, counter_picks, meta_matchups, opponent_members,
                         pair_matrix, pair_score, team_score)
from src.presets import presets_for
from src.recommend import recommend
from src.roles import meta_roles, set_roles
from src.stats import calc_stat, calc_stats, parse_spread, sp_problems
from src.team import PokemonSet
from src.type_chart import (ALL_TYPES, ability_defensive_multiplier, defensive_multiplier,
                            get_multiplier)
from src.usage import UsageData, load_usage, trim_chaos

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

    def test_two_megas_warns(self):
        team = [PokemonSet("Garchomp", item="Garchompite Z"), PokemonSet("Charizard", item="Charizardite Y")]
        warnings = [i.message for i in check_team(team, self.dex) if i.level == "warning"]
        self.assertTrue(any("only one Pokemon can Mega Evolve" in w for w in warnings))


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
        self.assertEqual(speeds.iloc[0]["pokemon"], "Garchomp-Mega-Z (yours)")   # 223 Speed
        cover = coverage_vs_meta(self.members, self.dex, self.usage, n=5)
        self.assertEqual(len(cover), 5)

    def test_threats(self):
        threats = threat_report(self.members, self.dex, self.usage)
        sneasler = threats.set_index("pokemon").loc["Sneasler"]
        # Mega Garchomp Z takes neutral from Fighting/Poison and Earth Power hits Poison super effectively
        self.assertIn("Garchomp-Mega-Z", sneasler["answers"])
        self.assertIn("Garganacl", sneasler["pressured"])
        self.assertGreater(len(threats), 5)


class TestRecommender(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.usage = sample_usage()

    def test_recommends_partners_and_excludes_team(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        team = team[:1]  # just Garganacl
        recs = recommend(build_members(team, self.dex), self.dex, self.usage, doubles=True)
        self.assertNotIn("Garganacl", set(recs["pokemon"]))
        # Sinistcha has 5x lift with Garganacl and resists its Water/Grass/Fighting/Ground weaknesses
        self.assertIn("Sinistcha", list(recs["pokemon"])[:3])
        self.assertTrue((recs["score"].diff().dropna() <= 0).all())

    def test_mega_candidates_are_team_sheet_aware(self):
        dex, usage = self.dex, load_usage("gen9championsvgc2026regmc")
        if usage is None:
            self.skipTest("no shipped usage data")
        team = [PokemonSet("Garchomp", item="Garchompite Z", moves=["Earth Power"])]
        recs = recommend(build_members(team, dex), dex, usage, top_n=40)
        self.assertFalse(any(name.startswith("Garchomp") for name in recs["pokemon"]))
        pset = usage.popular_set("Charizard-Mega-Y", dex)
        self.assertEqual((pset.species, pset.item), ("Charizard", "Charizardite Y"))

    def test_works_without_usage(self):
        recs = recommend([], self.dex, None, doubles=False, top_n=5)
        self.assertEqual(len(recs), 5)


class TestPresetsRolesMatchups(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.usage = sample_usage()
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        self.members = build_members(team, self.dex)

    def test_presets(self):
        presets = presets_for("Garchomp", self.usage, self.dex)
        items = [p.pset.item for p in presets]
        self.assertIn("Choice Scarf", items)
        scarf = presets[items.index("Choice Scarf")].pset
        self.assertFalse(any(self.dex.get_move(m)["category"] == "Status" for m in scarf.moves))
        self.assertEqual(scarf.nature, "Jolly")
        self.assertTrue(all(self.dex.can_learn("Garchomp", m) for p in presets for m in p.pset.moves))
        self.assertEqual(presets_for("Garganacl", None, self.dex), [])

    def test_meta_roles(self):
        labels = [t.label for t in meta_roles("Rillaboom", self.usage, self.dex)]
        self.assertIn("Fake Out support", labels)
        self.assertIn("Terrain setter", labels)
        self.assertIn("Trick Room setter", [t.label for t in meta_roles("Farigiraf", self.usage, self.dex)])
        singles = [t.label for t in meta_roles("Rillaboom", self.usage, self.dex, doubles=False)]
        self.assertNotIn("Fake Out support", singles)

    def test_set_roles(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        self.assertIn("Redirector", [t.label for t in set_roles(team[3], self.dex)])
        self.assertIn("Intimidate", [t.label for t in set_roles(team[4], self.dex)])

    def test_pair_scores(self):
        by_label = {m.label: m for m in self.members}
        gholdengo, incin = by_label["Gholdengo"], by_label["Incineroar"]
        # Incineroar hits Gholdengo super effectively and takes neutral back -> Incineroar wins
        self.assertGreater(pair_score(incin, gholdengo), 0)
        self.assertAlmostEqual(pair_score(incin, gholdengo, trick_room=False),
                               -pair_score(gholdengo, incin, trick_room=False))

    def test_mirror_is_even_and_bring(self):
        matrix = pair_matrix(self.members, self.members)
        self.assertAlmostEqual(team_score(matrix), 0.0)
        picks, _ = best_bring(matrix, 4)
        self.assertEqual(len(picks), 4)

    def test_archetypes(self):
        archetypes = build_archetypes(self.usage, self.dex, keep=5)
        self.assertTrue(archetypes)
        for arch in archetypes:
            roots = [to_id(self.dex.get_species(m).base_species) for m in arch.members]
            self.assertEqual(len(roots), len(set(roots)))            # Species Clause
            self.assertLessEqual(sum(self.dex.get_species(m).is_mega for m in arch.members), 1)
        table = meta_matchups(self.members, archetypes, self.usage, self.dex, bring=4)
        self.assertEqual(len(table), len(archetypes))
        self.assertTrue(all(len(b.split(", ")) == 4 for b in table["bring 4"]))

    def test_counter_picks_exclude_their_team(self):
        theirs = opponent_members(["Rillaboom", "Incineroar"], self.usage, self.dex)
        picks = counter_picks(theirs, self.usage, self.dex)
        self.assertFalse({"Rillaboom", "Incineroar"} & set(picks["pokemon"]))


if __name__ == "__main__":
    unittest.main()
