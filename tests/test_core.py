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
from unittest import mock
from pathlib import Path

from src.analysis import (build_members, mega_variants, coverage_vs_meta, defense_matrix, defense_summary,
                          role_checklist, speed_table)
from src.dex import load_dex, to_id
from src.evaluate import evaluate, load_tournament_teams, split_by_date
from src.legality import check_team, is_legal
from src.paste import export_paste, parse_paste
from src.matchup import (best_bring, build_archetypes, counter_picks, meta_matchups, opponent_members,
                         pair_matrix, pair_score, team_score, threat_report)
from src.presets import presets_for
from src.builder import build_teams
from src.plan import plan_score, profile_from, team_plans
from src.recommend import recommend
from src.swaps import SwapEngine, suggest_swaps
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

    def test_mega_sol_is_not_a_sun_setter(self):
        # Mega Sol only powers Mega Meganium's own moves as if in sun; it never sets sun for the team
        from src.roles import RULES
        from src.matchup import SETTERS
        sun_rule = next(r for r in RULES if r.label == "Sun setter")
        self.assertNotIn("megasol", sun_rule.abilities)
        self.assertNotIn("megasol", dict((l, a) for l, a, _ in SETTERS)["Sun"])

    def test_roles_never_blank_for_attackers(self):
        from src.roles import _never_blank
        moves = {"hydropump": 100.0, "icebeam": 100.0, "flashcannon": 100.0, "protect": 100.0}
        self.assertEqual([t.label for t in _never_blank([], moves, self.dex)], ["Special attacker"])

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


class TestEvaluation(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")
        self.usage = sample_usage()
        self.path = FIXTURES / "tournament_sample.json"

    def test_load_and_split(self):
        teams = load_tournament_teams("regmc", self.dex, self.path)
        self.assertEqual(len(teams), 10)
        self.assertEqual(teams[0]["sets"][2].item, "Garchompite Z")
        train, test = split_by_date(teams)
        self.assertTrue(train and test)
        self.assertLess(max(t["date"] for t in train), min(t["date"] for t in test))  # forward-in-time split

    def test_report(self):
        report = evaluate("regmc", self.dex, self.usage, path=self.path)
        self.assertEqual(report["queries"], report["test_teams"] * 6)
        for name in ("tuned weights", "hand-set weights", "popularity only", "random"):
            m = report["results"][name]
            self.assertTrue(0 <= m["hit@1"] <= m["hit@5"] <= m["hit@10"] <= 1, (name, m))
        self.assertAlmostEqual(sum(report["tuned_weights"].values()), 1.0, places=2)


class TestTwoMegas(unittest.TestCase):
    def setUp(self):
        self.dex = load_dex("regmc")

    def test_variants_evolve_one_at_a_time(self):
        team = [PokemonSet("Garchomp", item="Garchompite Z", moves=["Earth Power"]),
                PokemonSet("Charizard", item="Charizardite Y", moves=["Heat Wave"]),
                PokemonSet("Incineroar", item="Sitrus Berry", moves=["Fake Out"])]
        variants = mega_variants(team, self.dex)
        self.assertEqual([who for who, _ in variants], ["Garchomp-Mega-Z", "Charizard-Mega-Y"])
        for who, members in variants:
            self.assertEqual([m.form.name for m in members if m.form.is_mega], [who])
        base_zard = variants[0][1][1]
        self.assertEqual(base_zard.form.name, "Charizard")
        self.assertEqual(base_zard.ability_id, "blaze")          # its own ability, not Drought

    def test_one_mega_has_one_variant(self):
        team = [PokemonSet("Garchomp", item="Garchompite Z"), PokemonSet("Incineroar")]
        self.assertEqual(len(mega_variants(team, self.dex)), 1)

    def test_bring_picks_which_mega(self):
        usage = sample_usage()
        team = [PokemonSet("Garchomp", item="Garchompite Z", moves=["Earth Power", "Draco Meteor"]),
                PokemonSet("Charizard", item="Charizardite Y", moves=["Heat Wave", "Solar Beam"]),
                PokemonSet("Incineroar", moves=["Fake Out", "Flare Blitz"]),
                PokemonSet("Rillaboom", moves=["Wood Hammer"]), PokemonSet("Gholdengo", moves=["Make It Rain"])]
        archetypes = build_archetypes(usage, self.dex, keep=2)
        table = meta_matchups(mega_variants(team, self.dex), archetypes, usage, self.dex)
        self.assertTrue(set(table["mega evolve"]) <= {"Garchomp-Mega-Z", "Charizard-Mega-Y"})


class TestPlanBuilderSwaps(unittest.TestCase):
    """Uses the shipped Reg M-C usage data (skips if it's missing)."""

    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.usage = load_usage("gen9championsvgc2026regmc")
        if cls.usage is None:
            raise unittest.SkipTest("no shipped usage data")

    def test_snow_plan_detected_and_scored(self):
        froslass = PokemonSet("Froslass", item="Froslassite", moves=["Blizzard", "Protect"])
        members = build_members([froslass], self.dex)
        plans = team_plans(members, self.dex)
        self.assertEqual([p.key for p in plans], ["snow"])
        beartic = profile_from(self.dex.get_species("Beartic"), {"slushrush"}, {"iciclecrash"}, self.dex)
        incin = profile_from(self.dex.get_species("Incineroar"), {"intimidate"}, {"flareblitz"}, self.dex)
        self.assertGreater(plan_score(beartic, plans, members, self.dex)[0], 0.8)
        self.assertEqual(plan_score(incin, plans, members, self.dex)[0], 0.0)

    def test_weather_move_without_users_is_not_a_plan(self):
        garg = PokemonSet("Garganacl", ability="Purifying Salt", moves=["Salt Cure", "Protect"])
        sableye = PokemonSet("Sableye", ability="Prankster", moves=["Rain Dance", "Encore", "Reflect"])
        self.assertEqual(team_plans(build_members([garg, sableye], self.dex), self.dex), [])
        # ...until someone uses the rain
        swampert = PokemonSet("Swampert", ability="Swift Swim", moves=["Liquidation", "Protect"])
        plans = team_plans(build_members([garg, sableye, swampert], self.dex), self.dex)
        self.assertEqual([p.key for p in plans], ["rain"])
        # Trick Room and weather from an ability always count
        tr = PokemonSet("Sinistcha", ability="Hospitality", moves=["Trick Room", "Rage Powder"])
        ttar = PokemonSet("Tyranitar", ability="Sand Stream", moves=["Knock Off"])
        keys = {p.key for p in team_plans(build_members([tr, ttar], self.dex), self.dex)}
        self.assertEqual(keys, {"trickroom", "sand"})

    def test_regional_and_gendered_formes_are_separate(self):
        hisui = self.usage.popular_set("Arcanine-Hisui", self.dex)
        self.assertEqual(hisui.species, "Arcanine-Hisui")
        self.assertIn("Rock Head", self.dex.get_species("Arcanine-Hisui").abilities)
        self.assertEqual(self.usage.variants("Arcanine-Hisui", self.dex), ["Arcanine-Hisui"])
        names = {s.name for s in self.dex.selectable_species()}
        self.assertTrue({"Meowstic-M", "Meowstic-F", "Indeedee-M", "Indeedee-F"} <= names)
        self.assertEqual(self.dex.get_species("Meowstic").name, "Meowstic-M")  # Showdown spelling still works
        self.assertEqual(to_id("Meowstic-M"), to_id("Meowstic"))
        self.assertEqual(PokemonSet("Meowstic-M", item="Meowsticite").battle_form(self.dex).name, "Meowstic-M-Mega")
        self.assertEqual(PokemonSet("Meowstic-F", item="Meowsticite").battle_form(self.dex).name, "Meowstic-F-Mega")
        self.assertTrue(export_paste([PokemonSet("Meowstic-M")]).startswith("Meowstic\n"))

    def test_species_clause_by_dex_number(self):
        msgs = [i.message for i in check_team([PokemonSet("Arcanine", item="Leftovers"),
                                               PokemonSet("Arcanine-Hisui", item="Choice Band")], self.dex)]
        self.assertTrue(any("Species Clause" in m for m in msgs))
        team = [self.usage.popular_set("Arcanine-Hisui", self.dex)]
        recs = recommend(build_members(team, self.dex), self.dex, self.usage, top_n=None)
        self.assertNotIn("Arcanine", set(recs["pokemon"]))

    def test_roles_need_the_moves(self):
        sps = {"hp": 2, "atk": 0, "def": 0, "spa": 32, "spd": 0, "spe": 32}
        whimsicott = PokemonSet("Whimsicott", ability="Prankster", sps=sps,
                                moves=["Tailwind", "Moonblast", "Encore", "Protect"])
        self.assertNotIn("Special attacker", [t.label for t in set_roles(whimsicott, self.dex)])
        snarler = PokemonSet("Incineroar", ability="Blaze", moves=["Snarl", "Protect"])
        checklist = role_checklist(build_members([snarler], self.dex), True).set_index("role")
        self.assertEqual(checklist.loc["Intimidate / Attack drops", "covered by"], "—")

    def test_conditional_items_need_support(self):
        garg = self.usage.popular_set("Garganacl", self.dex)
        corv = self.usage.popular_set("Corviknight", self.dex, team=[garg])
        self.assertNotIn(corv.item, {"Psychic Seed", "Grassy Seed", "Electric Seed", "Misty Seed", "Room Service"})
        indeedee = PokemonSet("Indeedee", ability="Psychic Surge", moves=["Expanding Force"])
        from src.usage import item_has_support
        self.assertTrue(item_has_support("psychicseed", [("psychicsurge", set())], ("mirrorarmor", set())))
        self.assertFalse(item_has_support("psychicseed", [("purifyingsalt", set())], ("mirrorarmor", set())))
        self.assertIsNotNone(indeedee)

    def test_sand_setter_credited_for_rock_partner(self):
        from src.plan import enabler_score
        garg = build_members([PokemonSet("Garganacl", ability="Purifying Salt", moves=["Salt Cure"])], self.dex)
        ttar = profile_from(self.dex.get_species("Tyranitar"), {"sandstream"}, {"rockslide"}, self.dex)
        value, why, label = enabler_score(ttar, garg, team_plans(garg, self.dex), self.dex)
        self.assertEqual(label, "Sand")
        self.assertGreater(value, 0.4)

    def test_plan_has_diminishing_returns(self):
        ice = [PokemonSet("Froslass", item="Froslassite", moves=["Blizzard"]),
               PokemonSet("Glaceon", moves=["Blizzard"]), PokemonSet("Beartic", ability="Slush Rush",
                                                                    moves=["Icicle Crash"])]
        few, many = build_members(ice[:1], self.dex), build_members(ice, self.dex)
        prof = profile_from(self.dex.get_species("Baxcalibur"), {"thermalexchange"}, {"iciclecrash"}, self.dex)
        self.assertLess(plan_score(prof, team_plans(many, self.dex), many, self.dex)[0],
                        plan_score(prof, team_plans(few, self.dex), few, self.dex)[0])

    def test_core_then_cover(self):
        core = [self.usage.popular_set(n, self.dex) for n in ("Froslass-Mega", "Glaceon", "Beartic")]
        recs = recommend(build_members(core, self.dex), self.dex, self.usage, top_n=8, mode="neutral")
        self.assertEqual(recs.attrs["glue"], "Snow")
        self.assertIn("fire", recs.attrs["weak_types"])
        self.assertTrue(any("covers your Snow core" in w for w in recs["why"]))

    def test_needed_setter(self):
        swimmer = build_members([PokemonSet("Basculegion", ability="Swift Swim", moves=["Wave Crash"])], self.dex)
        plans = team_plans(swimmer, self.dex)
        self.assertTrue(plans and plans[0].key == "rain" and plans[0].needed)
        pelipper = profile_from(self.dex.get_species("Pelipper"), {"drizzle"}, {"hurricane"}, self.dex)
        self.assertEqual(plan_score(pelipper, plans)[0], 1.0)

    def test_modes_change_the_picks(self):
        members = build_members([self.usage.popular_set("Froslass-Mega", self.dex)], self.dex)
        popular = recommend(members, self.dex, self.usage, top_n=10)
        neutral = recommend(members, self.dex, self.usage, top_n=10, mode="neutral")
        top_usage = {n for n, _ in self.usage.ranked(10)}
        self.assertGreater(len(top_usage & set(popular["pokemon"])), len(top_usage & set(neutral["pokemon"])))
        self.assertTrue(any("Snow" in why for why in neutral["why"]))

    def test_builder(self):
        teams = build_teams("Garganacl", self.dex, self.usage, alternatives=2)
        self.assertEqual(len(teams), 2)
        for t in teams:
            self.assertEqual(len(t.sets), 6)
            self.assertEqual(t.sets[0].species, "Garganacl")
            self.assertFalse([i for i in check_team(t.sets, self.dex) if i.level == "error"])
            self.assertLessEqual(sum(p.is_mega(self.dex) for p in t.sets), 2)

    def test_team_rating(self):
        from src.team_rating import combined, percentile
        ref = {"fit_mean": -2.0, "fit_sd": 0.5, "chance_mean": 0.5, "chance_sd": 0.02,
               "combined_sorted": [-2.0, -1.0, 0.0, 1.0, 2.0]}
        self.assertAlmostEqual(combined(-1.5, 0.52, ref), 2.0)
        self.assertEqual(percentile(0.5, ref), 60.0)
        self.assertEqual(percentile(-5, ref), 0.0)
        self.assertEqual(percentile(5, ref), 100.0)

    def test_trust_bounds(self):
        """Predictions past every real team are capped there and flagged; real ones are untouched."""
        import math
        from src import match_model as M
        pushes = [{"tool: Wide Guard": 0.08, "bulk (mean)": 0.1}, {"tool: Wide Guard": -0.08, "bulk (mean)": -0.2}]
        trust = M.trust_bounds(pushes, [0.45, 0.58])
        self.assertLessEqual(trust["features"]["tool: Wide Guard"][0], -0.08)
        self.assertGreaterEqual(trust["features"]["tool: Wide Guard"][1], 0.08)
        self.assertGreaterEqual(trust["total"][1], 0.18)
        self.assertEqual(M.cap_chance({"trust": trust}, 0.66), trust["chance"][1])
        self.assertEqual(M.cap_chance({"trust": trust}, 0.50), 0.50)
        self.assertEqual(M.cap_chance(None, 0.66), 0.66)

        # a one-feature model: each Wide Guard user is worth 0.08 log-odds
        feats = M.SKILL + M.FEATURES
        model = {"model": {"features": feats, "species": [], "coef": [0.08 if f == "tool: Wide Guard" else 0.0
                                                                       for f in feats]}}
        side = lambda n: {"members": [], "meta": 0.0, "popularity": 0.0, "species": [],
                          "profile": {"tool: Wide Guard": float(n)}}
        parts = {}  # no members, and the damage-calc features are patched out below
        with mock.patch.object(M, "matchup_features", return_value={}):
            self.assertAlmostEqual(M.predict_match(model, side(4), side(0), parts), 1 / (1 + math.exp(-0.32)))
            guarded = dict(model, trust=trust)
            cap = trust["features"]["tool: Wide Guard"][1]
            self.assertAlmostEqual(M.predict_match(guarded, side(4), side(0), parts), 1 / (1 + math.exp(-cap)))
            self.assertEqual(M.beyond(guarded, side(4), side(0), parts), {"tool: Wide Guard"})
            # a real-sized difference is untouched
            self.assertAlmostEqual(M.predict_match(guarded, side(1), side(0), parts), 1 / (1 + math.exp(-0.08)))
            self.assertEqual(M.beyond(guarded, side(1), side(0), parts), set())

    def test_swaps(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        engine = SwapEngine(build_archetypes(self.usage, self.dex, keep=4), self.usage, self.dex)
        base = engine.overall(build_members(team, self.dex))
        swaps = suggest_swaps(team, self.dex, self.usage, engine, focus="Incineroar")
        self.assertFalse(swaps.empty)
        for _, row in swaps.iterrows():
            self.assertGreater(row["vs threat"], 0)
            self.assertGreaterEqual(row["overall"], base - 0.05 - 1e-9)
            new_team = team[:row["slot"]] + [row["_set"]] + team[row["slot"] + 1:]
            self.assertFalse([i for i in check_team(new_team, self.dex) if i.level == "error"], row["swap in"])

    def test_team_grade(self):
        from src.team_rating import grade
        self.assertEqual([grade(p)[0] for p in (100, 75, 74.9, 50, 49, 25, 24, 0)],
                         ["Strong", "Strong", "Solid", "Solid", "Shaky", "Shaky", "Weak", "Weak"])

    def test_swaps_by_team_score(self):
        """With the team rating attached, best swaps rank by it and only ever raise it."""
        from src.match_model import load_model
        from src.synergy import load_model as load_teammates
        from src.team_rating import load_reference
        model, ref, tm = load_model("regmc"), load_reference("regmc"), load_teammates("regmc")
        if not (model and ref and tm):
            self.skipTest("learned models not built")
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        engine = SwapEngine(build_archetypes(self.usage, self.dex, keep=4), self.usage, self.dex)
        engine.attach_model(model)
        engine.attach_rating(ref, tm)
        swaps = suggest_swaps(team, self.dex, self.usage, engine, top_n=5)
        base = swaps.attrs["base_score"]
        self.assertIsNotNone(base)
        self.assertTrue((swaps["rating change"] > 0).all())
        self.assertTrue(swaps["rating change"].is_monotonic_decreasing)
        self.assertTrue(((swaps["score"] >= 0) & (swaps["score"] <= 100)).all())

    def test_swaps_same_role(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        engine = SwapEngine(build_archetypes(self.usage, self.dex, keep=4), self.usage, self.dex)
        swaps = suggest_swaps(team, self.dex, self.usage, engine, same_role=True)
        for _, row in swaps.iterrows():
            self.assertEqual(row["out job"], row["in job"], row["swap in"])

    def test_swaps_per_member(self):
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        engine = SwapEngine(build_archetypes(self.usage, self.dex, keep=4), self.usage, self.dex)
        alts = suggest_swaps(team, self.dex, self.usage, engine, per_member=2)
        self.assertEqual(set(alts["slot"]), set(range(len(team))))  # every member gets alternatives
        self.assertTrue((alts.groupby("slot").size() <= 2).all())
        self.assertEqual(set(alts["pick"]), {"Best upgrade", "Most similar"})

    def test_cosmetic_formes_use_base_data(self):
        for name in ["Vivillon-Pokeball", "Sinistcha-Masterpiece", "Alcremie-Mint-Cream"]:
            s = self.dex.get_species(name)
            self.assertTrue(self.dex.is_cosmetic(s), name)
            self.assertEqual(self.dex.sheet_id(s), to_id(s.base_species))
        for name in ["Rotom-Fan", "Meowstic-F", "Arcanine-Hisui", "Garchomp-Mega", "Squawkabilly-White"]:
            self.assertFalse(self.dex.is_cosmetic(self.dex.get_species(name)), name)  # real differences
        pset = self.usage.popular_set("Sinistcha-Masterpiece", self.dex)
        self.assertIsNotNone(pset)
        self.assertEqual(pset.species, "Sinistcha-Masterpiece")

    def test_trim_keeps_rare_pokemon_with_real_appearances(self):
        from src.usage import trim_chaos
        raw = {"info": {}, "data": {
            "Rotom-Fan": {"usage": 0.00005, "Raw count": 400, "Abilities": {"levitate": 400}},
            "Watchog": {"usage": 0.00005, "Raw count": 12, "Abilities": {"analytic": 12}}}}
        kept = trim_chaos(raw, "f", "2026-10", 1630)["pokemon"]
        self.assertIn("Rotom-Fan", kept)
        self.assertNotIn("Watchog", kept)

    def test_hidden_pool_skips_popular_species(self):
        from src.recommend import recommend
        from src.swaps import HIDDEN_MAX, mode_pool
        sheet = self.usage.team_sheet_usage(self.dex)
        pool = mode_pool(self.usage, "hidden", self.dex)
        self.assertTrue(pool)
        # nothing on 3%+ of teams, Megas counted with their base species (Salamence-Mega)
        self.assertTrue(all(sheet.get(self.usage.sheet_name(n, self.dex), 0) < HIDDEN_MAX for n in pool))
        common = [n for n, v in sheet.items() if v >= HIDDEN_MAX]
        self.assertIn("Dragonite", common)  # ~6% of teams: not a gem
        self.assertIn("Swampert", common)  # ~4.4%: under the old 5% line, over the 3% one
        self.assertNotIn("Dragonite", pool)
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        recs = recommend(build_members(team[:3], self.dex), self.dex, self.usage, mode="hidden", top_n=50)
        self.assertFalse(set(recs["pokemon"]) & set(common))

    def test_game_plan(self):
        from src.gameplan import game_plan
        from src.matchup import best_variant, opponent_members
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        arch = build_archetypes(self.usage, self.dex, keep=1)[0]
        theirs = opponent_members(arch.members, self.usage, self.dex)
        members = build_members(team, self.dex)
        _, matrix, picks, _ = best_variant(members, theirs, arch.trick_room, True, arch.weather, 4)
        plan = game_plan(members, theirs, matrix, picks, self.dex, True, arch.trick_room, arch.weather)
        self.assertEqual(len(plan.lead), 2)
        self.assertEqual(sorted(plan.lead + plan.back), sorted(picks))
        self.assertEqual(len(plan.their_leads), 2)
        self.assertEqual(len(plan.speed), len(picks) + len(theirs))

    def test_mega_choice_follows_the_bring(self):
        from dataclasses import replace
        from src.analysis import mega_variants
        from src.matchup import best_variant, opponent_members
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        team = [p if p.species != "Rillaboom" else replace(p, species="Charizard", item="Charizardite Y",
                                                             ability="Blaze") for p in team]
        variants = mega_variants(team, self.dex)
        self.assertEqual(len(variants), 2)
        arch = build_archetypes(self.usage, self.dex, keep=1)[0]
        theirs = opponent_members(arch.members, self.usage, self.dex)

        def no_chomp(members, matrix):  # a bring that leaves Garchomp at home
            return [m.label for m in members if not m.label.startswith("Garchomp")][:4]

        who, matrix, picks, _ = best_variant(variants, theirs, arch.trick_room, True, arch.weather, 4, no_chomp)
        self.assertFalse(any(p.startswith("Garchomp") for p in picks))
        self.assertNotEqual(who, "Garchomp-Mega-Z")  # never Mega Evolve a Pokémon left at home
        if who:
            self.assertIn(who, picks)

        def neither(members, matrix):
            return [m.label for m in members if not m.form.is_mega and not m.label.startswith(("Garchomp",
                                                                                                "Charizard"))][:4]

        who, _, picks, _ = best_variant(variants, theirs, arch.trick_room, True, arch.weather, 4, neither)
        self.assertIsNone(who)

    def test_calcs_use_the_mega_forme(self):
        from dataclasses import replace
        from src.analysis import mega_variants
        from src.matchup import best_attack, opponent_members
        golurk = replace(self.usage.popular_set("Golurk-Mega", self.dex), species="Golurk", item="Golurkite")
        lucario = replace(self.usage.popular_set("Lucario-Mega-Z", self.dex), species="Lucario",
                          item="Lucarionite Z")
        inc = opponent_members(["Incineroar"], self.usage, self.dex)[0]
        hits, taken = {}, {}
        for _, members in mega_variants([golurk, lucario], self.dex):
            for m in members:
                hits[m.label], taken[m.label] = best_attack(m, inc)[0], best_attack(inc, m)[0]
        # the same set as a Mega and in base forme: the calc cache must not mix them up
        self.assertGreater(hits["Lucario-Mega-Z"], hits["Lucario"] * 1.2)
        self.assertLess(taken["Lucario-Mega-Z"], taken["Lucario"] * 0.7)  # Aura Guard halves Flare Blitz
        self.assertLess(taken["Golurk-Mega"], taken["Golurk"] * 0.9)  # (Iron Fist base Golurk hits as hard)
        self.assertAlmostEqual(hits["Lucario-Mega-Z"], 75, delta=3)  # Aura Sphere into Sitrus Incineroar

    def test_bring_model_keeps_the_mega(self):
        from src.analysis import mega_variants
        from src.bring_model import load_model, pick
        from src.matchup import opponent_members, pair_matrix
        model = load_model("regmc")
        if not model:
            self.skipTest("no bring model")
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        arch = build_archetypes(self.usage, self.dex, keep=1)[0]
        theirs = opponent_members(arch.members, self.usage, self.dex)
        _, members = mega_variants(team, self.dex)[0]
        matrix = pair_matrix(members, theirs)
        for m in members:  # whoever must come is in the four, and the leads come from the four
            bring, lead, _ = pick(model, members, theirs, matrix, self.dex, keep=m.label)
            self.assertIn(m.label, bring)
            self.assertEqual(len(bring), 4)
            self.assertTrue(set(lead) <= set(bring))

    def test_win_chance_fit(self):
        import numpy as np
        from src.validate import fit_logistic, win_chance
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 4000)
        y = (rng.random(4000) < 1 / (1 + np.exp(-0.8 * x))).astype(float)
        self.assertAlmostEqual(fit_logistic(x, y), 0.8, delta=0.12)
        self.assertAlmostEqual(win_chance(0.0, 0.8), 0.5)

    def test_cooccurrence(self):
        from src.cooccurrence import Cooccurrence
        a = [PokemonSet("Incineroar"), PokemonSet("Rillaboom"), PokemonSet("Garchomp")]
        b = [PokemonSet("Incineroar"), PokemonSet("Rillaboom"), PokemonSet("Gholdengo")]
        c = [PokemonSet("Garchomp"), PokemonSet("Gholdengo"), PokemonSet("Sinistcha")]
        co = Cooccurrence([a, b, c] * 10, self.dex)
        together, _ = co.log_lift("Incineroar", "Rillaboom")
        apart, _ = co.log_lift("Incineroar", "Sinistcha")
        self.assertGreater(together, 0)
        self.assertLess(apart, 0)

    def test_screens_help_the_whole_bring(self):
        from src.matchup import pair_matrix
        attacker = PokemonSet("Garchomp", ability="Rough Skin", moves=["Earthquake", "Dragon Claw"])
        plain = PokemonSet("Meowstic-M", ability="Prankster", moves=["Psychic", "Fake Out"])
        screens = PokemonSet("Meowstic-M", ability="Prankster", moves=["Reflect", "Light Screen", "Psychic"])
        foe = [PokemonSet("Kingambit", ability="Supreme Overlord", moves=["Kowtow Cleave", "Iron Head"]),
               PokemonSet("Sneasler", ability="Unburden", moves=["Close Combat", "Dire Claw"])]
        foes = build_members(foe, self.dex)
        without = pair_matrix(build_members([attacker, plain], self.dex), foes)
        with_screens = pair_matrix(build_members([attacker, screens], self.dex), foes)
        # Garchomp's row improves when its teammate sets screens
        self.assertGreater(with_screens.loc["Garchomp"].sum(), without.loc["Garchomp"].sum() - 1e-9)
        self.assertGreaterEqual(team_score(with_screens), team_score(without))

    def test_match_model_is_antisymmetric(self):
        from src.match_model import load_model, matchup_features, predict_match, side_profile, team_side
        from src.matchup import pair_parts
        a_sets, _ = parse_paste(GARGANACL_TEAM, self.dex)
        b_sets = [self.usage.popular_set(n, self.dex) for n in ("Incineroar", "Sneasler", "Kingambit",
                                                                 "Rillaboom", "Sinistcha", "Garchomp")]
        a, b = build_members(a_sets, self.dex), build_members(b_sets, self.dex)
        fa, fb = matchup_features(pair_parts(a, b)), matchup_features(pair_parts(b, a))
        for k in fa:
            self.assertAlmostEqual(fa[k], -fb[k], places=9, msg=k)
        self.assertIn("tool: Fake Out", side_profile(a))
        model = load_model("regmc")
        if model is not None:
            sa = team_side(a, a_sets, self.dex, self.usage, None)
            sb = team_side(b, b_sets, self.dex, self.usage, None)
            self.assertAlmostEqual(predict_match(model, sa, sb) + predict_match(model, sb, sa), 1.0, places=9)

    def test_job(self):
        from src.roles import RoleTag, job, plan_roles
        tags = [RoleTag("Tailwind setter", 100), RoleTag("Disruptor", 100), RoleTag("Special attacker", 100)]
        self.assertEqual(job(tags), "Support")
        self.assertEqual(job([RoleTag("Setup sweeper", 100)]), "Attacker")
        self.assertEqual(plan_roles([RoleTag("Snow setter", 100), RoleTag("Screens", 100)]), {"Snow setter"})


if __name__ == "__main__":
    unittest.main()


class TestTeammateModel(unittest.TestCase):
    def test_learns_partners_and_explains_away(self):
        import numpy as np
        from src.synergy import TeammateModel, TeamRow
        # a and b always come together; c pairs with d; e/f are filler on every team
        rows = [TeamRow(("a", "b", "e", "f"), 1.0, 0, "t") for _ in range(200)]
        rows += [TeamRow(("c", "d", "e", "f"), 1.0, 0, "t") for _ in range(200)]
        m = TeammateModel(["a", "b", "c", "d", "e", "f"]).fit(rows, l2=1.0, epochs=40)
        self.assertGreater(m.pull("a", "b"), m.pull("a", "d"))
        p = m.pick_probs(["a", "e", "f"])
        self.assertEqual(m.vocab[int(np.argmax(p))], "b")
        self.assertAlmostEqual(float(p.sum()), 1.0, places=6)
        self.assertEqual(p[m.index["a"]], 0.0)  # never re-picks a member
        check = {r["root"]: r for r in m.fit_check(["a", "b", "e", "f"])}
        self.assertEqual(check["b"]["rank"], 1)

    def test_round_trip(self):
        from src.synergy import TeammateModel, TeamRow
        rows = [TeamRow(("a", "b", "c", "d"), 1.0, 0, "t")] * 50
        m = TeammateModel(["a", "b", "c", "d"]).fit(rows, epochs=5)
        m2 = TeammateModel.from_json(m.to_json({"formats": ["x"]}))
        self.assertEqual(m2.formats, ["x"])
        self.assertAlmostEqual(m2.pull("a", "b"), m.pull("a", "b"), places=3)

    def test_recommendations_explain_with_the_model(self):
        from src.formats import DEFAULT_FORMAT, FORMATS
        dex = load_dex(FORMATS[DEFAULT_FORMAT].regulation)
        usage = load_usage(DEFAULT_FORMAT)
        if usage is None or usage.teammates is None:
            self.skipTest("no teammate model")
        team, _ = parse_paste(GARGANACL_TEAM, dex)
        recs = recommend(build_members(team[:4], dex), dex, usage, top_n=10, mode="popular")
        self.assertTrue(any("fit" in p for p in recs["parts"]))
        self.assertTrue(recs["why"].str.contains("players pair it with").any())
        self.assertTrue(recs["synergy"].between(0, 1).all())


class TestNewPokemon(unittest.TestCase):
    def test_pokemon_the_model_never_saw_score_neutral(self):
        from src.formats import DEFAULT_FORMAT, FORMATS
        dex = load_dex(FORMATS[DEFAULT_FORMAT].regulation)
        usage = load_usage(DEFAULT_FORMAT)
        if usage is None or usage.teammates is None:
            self.skipTest("no teammate model")
        team, _ = parse_paste(GARGANACL_TEAM, dex)
        members = build_members(team[:3], dex)
        tm = usage.teammates
        saved = dict(tm.index)
        try:  # pretend Kingambit was just released: not in the model
            del tm.index["kingambit"]
            recs = recommend(members, dex, usage, top_n=300, mode="neutral")
        finally:
            tm.index.clear(); tm.index.update(saved)
        row = recs[recs["pokemon"] == "Kingambit"].iloc[0]
        self.assertEqual(row["synergy"], 0.5)  # no evidence: neutral, not buried at 0
        self.assertIn("too new or rare", row["why"])


class TestRecentUsage(unittest.TestCase):
    def test_recent_usage_rescales_and_keeps_sets(self):
        from src.formats import DEFAULT_FORMAT, FORMATS
        dex = load_dex(FORMATS[DEFAULT_FORMAT].regulation)
        monthly = load_usage(DEFAULT_FORMAT, recent=False)
        raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "usage" /
                          f"{DEFAULT_FORMAT}.json").read_text())
        u, plain = UsageData(raw), UsageData(json.loads(json.dumps(raw)))
        share = {"garchomp": 0.5, "incineroar": 0.1}
        u.apply_recent({"share": share, "teams": 1000, "first_day": "a", "last_day": "b", "min_rating": 1300}, dex)
        sheet = u.team_sheet_usage(dex)
        self.assertAlmostEqual(sheet["Garchomp"], 50.0, delta=0.1)  # Megas + base add up to the new share
        self.assertAlmostEqual(sheet["Incineroar"], 10.0, delta=0.1)
        self.assertEqual(u.ranked(1)[0][0].split("-")[0], "Garchomp")
        # sets and the pairing math still come from the monthly stats
        self.assertEqual(u.popular_set("Incineroar", dex).moves, monthly.popular_set("Incineroar", dex).moves)
        self.assertAlmostEqual(u.pair_lift("Incineroar", "Rillaboom")[0], plain.pair_lift("Incineroar", "Rillaboom")[0],
                               places=6)
        self.assertEqual(u.recent["teams"], 1000)


class TestSpreadTuner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.formats import DEFAULT_FORMAT, FORMATS
        cls.dex = load_dex(FORMATS[DEFAULT_FORMAT].regulation)
        cls.usage = load_usage(DEFAULT_FORMAT)

    def test_meets_benchmarks_with_fewest_points(self):
        from dataclasses import replace
        from src.damage import Battler, Field, calculate
        from src.spread import Benchmark, tune
        from src.stats import STATS
        me = replace(self.usage.popular_set("Lucario-Mega-Z", self.dex), species="Lucario", item="Lucarionite Z")
        inc = self.usage.popular_set("Incineroar", self.dex)
        r = tune(me, self.dex, outspeed=172, survive=[Benchmark(inc, "Flare Blitz")])
        self.assertIsNotNone(r.sps)
        self.assertEqual(sum(r.sps.values()), 66)
        self.assertTrue(all(0 <= r.sps[s] <= 32 for s in STATS))
        tuned = replace(me, sps=r.sps)
        self.assertGreater(tuned.stats(self.dex)["spe"], 172)
        hit = calculate(Battler.from_set(inc, self.dex), Battler.from_set(tuned, self.dex),
                        self.dex.get_move("Flare Blitz"), Field(doubles=True))
        self.assertLess(hit.max, hit.defender_hp)  # survives the highest roll
        bulk = tune(me, self.dex, survive=[Benchmark(inc, "Flare Blitz")], rest="bulk")
        self.assertGreaterEqual(bulk.sps["hp"], r.sps["hp"])  # leftovers to bulk, not Sp. Atk

    def test_impossible_benchmarks_say_so(self):
        from dataclasses import replace
        from src.spread import tune
        slow = self.usage.popular_set("Garganacl", self.dex)
        r = tune(slow, self.dex, outspeed=200)
        self.assertIsNone(r.sps)
        self.assertIn("even with 32 Speed points and a Speed-boosting nature", r.problem)  # no nature helps
        lucario = replace(self.usage.popular_set("Lucario-Mega-Z", self.dex), species="Lucario",
                          item="Lucarionite Z", nature="Modest")
        r = tune(lucario, self.dex, outspeed=215)  # Modest tops out at 203, Timid at 223
        self.assertIsNone(r.sps)
        self.assertIn("Timid or Jolly", r.problem)  # possible, but only with a Speed nature


class TestSimilarTeams(unittest.TestCase):
    def test_finds_teams_sharing_most_of_yours(self):
        from src.evaluate import load_tournament_teams
        from src.similar_teams import find_similar, ordinal
        dex = load_dex("regmc")
        teams = load_tournament_teams("regmc", dex)
        team, _ = parse_paste(GARGANACL_TEAM, dex)
        sims, need = find_similar(team, teams, dex)
        self.assertEqual(need, 4)
        self.assertTrue(sims)
        self.assertTrue(all(s.shared >= 4 for s in sims))
        self.assertEqual([s.shared for s in sims], sorted((s.shared for s in sims), reverse=True))
        self.assertEqual((ordinal(1), ordinal(2), ordinal(11), ordinal(23)), ("1st", "2nd", "11th", "23rd"))
