"""Plans, the team builder, swaps, the teammate model, sheet sets, the Playbook and the health check."""

import json
import unittest
from unittest import mock
from pathlib import Path

from src.analysis import (build_members, role_checklist)
from src.dex import load_dex, to_id
from src.legality import check_team
from src.paste import export_paste, parse_paste
from src.matchup import (build_archetypes, team_score)
from src.builder import build_teams
from src.plan import plan_score, profile_from, team_plans
from src.recommend import recommend
from src.swaps import SwapEngine, suggest_swaps
from src.roles import set_roles
from src.team import PokemonSet
from src.usage import UsageData, load_usage

from tests.test_core import GARGANACL_TEAM


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

    def test_lenses(self):
        """Proven is left untested for off-meta teams instead of marked down; On paper always grades."""
        from src.team_rating import lenses, load_reference
        ref = load_reference("regmc")
        if not ref or "fit_sorted" not in ref or self.usage.teammates is None:
            self.skipTest("team rating reference not built")
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        seen = lenses(team, self.dex, self.usage, 0.5, ref)
        self.assertIn(seen["proven"][0], {"Strong", "Solid", "Shaky", "Weak", "Untested"})
        self.assertIn(seen["paper"][0], {"Strong", "Solid", "Shaky", "Weak"})
        from src.recommend import HIDDEN_MAX
        sheet = self.usage.team_sheet_usage(self.dex)
        rare = [n for n, pct in sheet.items() if pct < HIDDEN_MAX and self.usage.popular_set(n, self.dex)]
        off = [self.usage.popular_set(n, self.dex) for n in rare[:6]]
        if len(off) == 6:
            self.assertEqual(lenses(off, self.dex, self.usage, 0.5, ref)["proven"][0], "Untested")
        self.assertIsNone(lenses(team[:4], self.dex, self.usage, 0.5, ref))  # a full team only

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

    def test_swap_engine_matches_one_team_at_a_time(self):
        """The engine scores all meta teams at once; it must give exactly (to the bit) what scoring one meta
        team at a time with scores_from_parts and match_model.predict_match gives."""
        from src.match_model import load_model, predict_match, team_side
        import numpy as np
        from src.matchup import scores_from_parts, side_support
        model = load_model("regmc")
        if not model:
            self.skipTest("learned model not built")
        engine = SwapEngine(build_archetypes(self.usage, self.dex, keep=4), self.usage, self.dex)
        engine.attach_model(model)
        team, _ = parse_paste(GARGANACL_TEAM, self.dex)
        newcomers = [p for name, _ in self.usage.ranked(15) if (p := self.usage.popular_set(name, self.dex))]
        teams = [team] + [team[:i] + [p] + team[i + 1:] for i in range(len(team)) for p in newcomers]
        for t in teams:
            versions = engine.versions(t)
            total = weights = 0.0
            for i, f in enumerate(engine.fields):
                best = None
                for members in versions:
                    rows = [engine.rows(m) for m in members]
                    parts = {k: np.vstack([r[i][k] for r in rows]) for k in rows[0][i]}
                    matrix = scores_from_parts(parts, side_support(members), f.support, f.trick_room)
                    score = matrix.max(axis=0).mean() - (-matrix).max(axis=1).mean()
                    best = score if best is None else max(best, score)
                total += best * f.weight
                weights += f.weight
            meta = total / weights
            self.assertEqual(engine.overall(t), meta)
            total = weights = 0.0
            for i, f in enumerate(engine.fields):
                best = max(predict_match(model, team_side(members, t, self.dex, self.usage, engine, meta=meta),
                                         engine.sides[i],
                                         {k: np.vstack([engine.rows(m)[i][k] for m in members])
                                          for k in engine.rows(members[0])[i]})
                           for members in versions)
                total += best * f.weight
                weights += f.weight
            from src.match_model import cap_chance
            self.assertEqual(engine.win_chance(t), cap_chance(model, total / weights))

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
        self.assertEqual(set(alts["pick"]), {"Best upgrade", "Players' pick"})

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


class TestBuilderHonesty(unittest.TestCase):
    """Builder reasons only claim what the added set carries; the core report's pieces."""

    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.usage = load_usage("gen9championsvgc2026regmc")

    def test_reasons_match_sets(self):
        # every role in "adds ..." and every "its Tailwind helps" is on the set the builder added
        from src.builder import build_teams
        from src.analysis import ROLES, provides_role
        from src.plan import LABELS, SETTERS
        key = {r.label: r.key for r in ROLES}
        plan = {v: k for k, v in LABELS.items()}
        checked = 0
        for core in ("Feraligatr", "Garganacl", "Sneasler"):
            for mode in ("popular", "neutral"):
                for t in build_teams(core, self.dex, self.usage, mode=mode):
                    for pset, why in zip(t.sets[1:], t.reasons):
                        moves = {to_id(m) for m in pset.moves}
                        form = pset.battle_form(self.dex)
                        abil = {to_id(pset.ability)} | ({to_id(a) for a in form.abilities} if form.is_mega else set())
                        spread = any(self.dex.moves[m].get("spread") and self.dex.moves[m]["category"] != "Status"
                                     for m in moves if m in self.dex.moves)
                        for part in why.split(": ", 1)[1].split("; "):
                            if part.startswith("adds "):
                                for label in part[5:].split(", "):
                                    checked += 1
                                    self.assertTrue(provides_role(key[label], moves, abil, spread), (pset, label))
                            if part.startswith("its ") and " helps your" in part:
                                a, mv = SETTERS[plan[part[4:part.index(" helps")]]]
                                checked += 1
                                self.assertTrue(moves & mv or abil & a, (pset, part))
                    if t.theme:
                        self.assertIn(f"its {t.theme} helps", t.reasons[0])
        self.assertGreater(checked, 20)

    def test_honest_reason(self):
        from src.builder import honest_reason, uncarried
        from src.team import PokemonSet
        why = "its Tailwind helps your Feraligatr-Mega; players pair it with Feraligatr (3.4x); adds Speed control, Recovery / support healing"
        self.assertEqual(honest_reason(why, ["Tailwind", "Speed control"]),
                         "players pair it with Feraligatr (3.4x); adds Recovery / support healing")
        pset = PokemonSet(species="Corviknight", moves=["Brave Bird", "Roost", "Bulk Up", "Power Trip"])
        self.assertEqual(uncarried(pset, [("Tailwind", frozenset({"tailwind"})),
                                          ("Recovery / support healing", frozenset({"roost"}))]), ["Tailwind"])

    def test_core_report(self):
        from src.core_report import answered, core_matchups, replay_index, tournament_core
        from src.evaluate import load_tournament_teams
        rec = {"uploadtime": 1795046468, "format": "gen9championsvgc2026regmcbo3", "forfeit": False,
               "players": {"p1": {"name": "a", "rating": 1500}, "p2": {"name": "b", "rating": 1300}},
               "winner": "p1", "mega": {"p1": "Feraligatr-Mega", "p2": None},
               "preview": {"p1": ["Feraligatr", "Sneasler", "Incineroar", "Talonflame", "Sinistcha", "Kingambit"],
                           "p2": ["Garchomp", "Rillaboom", "Whimsicott", "Pelipper", "Archaludon", "Farigiraf"]},
               "brought": {"p1": ["Feraligatr", "Sneasler", "Incineroar", "Talonflame"],
                           "p2": ["Garchomp", "Rillaboom", "Whimsicott", "Pelipper"]},
               "sheets": {"p1": [{"species": "Feraligatr", "item": "Feraligite", "moves": ["Liquidation", "Protect"]}]}}
        idx = replay_index([rec] * 6, self.dex)["pokemon"]["feraligatr"]
        self.assertEqual((idx["previews"], idx["brought"], idx["won"], idx["mega"], idx["sheets"]), (6, 6, 6, 6, 6))
        self.assertAlmostEqual(idx["mega_expected"], 6 / (1 + 10 ** (-200 / 400)), places=1)
        self.assertEqual(idx["moves"]["liquidation"], 1.0)
        self.assertEqual(idx["teams"][0]["rating"], 1500)
        self.assertEqual(len(idx["teams"]), 1)            # the same team is listed once
        teams = load_tournament_teams("regmc", self.dex)
        tour = tournament_core("feraligatr", teams, self.dex, "Feraligite")
        self.assertEqual(len(tour["roots"]), tour["teams"])
        self.assertTrue(all("feraligatr" in r for r in tour["roots"]))
        core = self.usage.popular_set("Feraligatr", self.dex)
        calcs = core_matchups(core, self.usage, self.dex)
        self.assertTrue(calcs["beats"] and calcs["threats"])
        self.assertFalse({n for n, _ in calcs["beats"]} & {n for n, _ in calcs["threats"]})
        yes, no = answered([core], [n for n, _ in calcs["threats"]], self.usage, self.dex)
        self.assertEqual(yes, [])                         # alone, it answers none of its own threats


class TestSheetSetsAndSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dex = load_dex("regmc")
        cls.usage = load_usage("gen9championsvgc2026regmc")

    def test_sheet_sets(self):
        from src.sheet_sets import apply, sheet_sets_from
        from src.team import PokemonSet
        dex = self.dex
        mk = lambda moves, nat: PokemonSet(species="Feraligatr", item="Feraligite", nature=nat, moves=moves)  # noqa: E731
        teams = [{"date": "2026-11-01", "player": f"p{i}", "tournament": "t",
                  "sets": [mk(["Liquidation", "Protect", "Body Slam", "Aqua Jet"], "Adamant")]} for i in range(12)]
        teams.append({"date": "2026-11-01", "player": "p0", "tournament": "t",   # same player again: once
                      "sets": [mk(["Liquidation", "Protect", "Body Slam", "Aqua Jet"], "Adamant")]})
        sets = sheet_sets_from(teams, [], dex, end="2026-11-10", days=30)
        e = sets[("feraligatr", True)]
        self.assertEqual(e["n"], 12)
        self.assertEqual(e["mode"], sorted(["liquidation", "protect", "bodyslam", "aquajet"]))
        lad = self.usage.popular_set("Feraligatr", dex)
        out = apply(lad, dex, sets)
        self.assertEqual({to_id(m) for m in out.moves}, {"liquidation", "protect", "bodyslam", "aquajet"})
        self.assertEqual((out.nature, out.item), ("Adamant", lad.item))
        self.assertEqual(apply(lad, dex, {}).moves, lad.moves)               # no sheets: ladder set
        scarf = PokemonSet(species="Feraligatr", item="Choice Scarf", moves=["Liquidation", "Crunch", "Ice Punch", "Aqua Jet"])
        sets2 = {("feraligatr", False): {**e, "mode": ["liquidation", "protect", "crunch", "icepunch"]}}
        self.assertNotIn("Protect", apply(scarf, dex, sets2).moves)           # no status move on a Choice item

    def test_after_setup(self):
        from src.builder import core_set
        from src.setup import after_setup, setup_move
        from src.team import PokemonSet
        fera = core_set("Feraligatr", self.dex, self.usage)
        r = after_setup(fera, self.usage, self.dex)
        self.assertEqual(r["boosts"], {"atk": 1, "spe": 1})
        self.assertGreaterEqual(r["ohko"][1], r["ohko"][0])
        self.assertGreater(r["speed"][1], r["speed"][0])
        self.assertEqual(setup_move(PokemonSet(species="Volcarona", moves=["Quiver Dance", "Fiery Dance"]))[1],
                         {"spa": 1, "spd": 1, "spe": 1})
        self.assertIsNone(after_setup(PokemonSet(species="Incineroar", item="Sitrus Berry", ability="Intimidate",
                                                 moves=["Fake Out", "Flare Blitz"]), self.usage, self.dex))


class TestPlaybook(unittest.TestCase):
    def test_turn1_choices_and_edges(self):
        import src.playbook as P
        dex = load_dex("regmc")
        setters = {"Trick Room": {"Farigiraf"}}

        def game(i, fake_out: bool, won: bool):
            mine = [["Incineroar", "Fake Out", "Farigiraf"]] if fake_out else [["Incineroar", "Protect", "Incineroar"]]
            mine.append(["Garchomp", "Earthquake", None] if fake_out else ["Garchomp", "Protect", "Garchomp"])
            return {"uploadtime": 1795000000 + i, "forfeit": False, "winner": "p1" if won else "p2",
                    "players": {"p1": {"name": f"a{i}", "rating": 1500}, "p2": {"name": f"b{i}", "rating": 1500}},
                    "leads": {"p1": ["Incineroar", "Garchomp"], "p2": ["Farigiraf", "Kingambit"]},
                    "brought": {"p1": ["Incineroar", "Garchomp"], "p2": ["Farigiraf", "Kingambit"]},
                    "turn1": {"p1": mine, "p2": [["Farigiraf", "Trick Room", "Farigiraf"]]}, "moves": {}}
        recs = [game(i, i % 2 == 0, i % 2 == 0 or i % 5 == 0) for i in range(400)]
        old = P.MIN_GAMES
        P.MIN_GAMES = 50
        try:
            book = P.replay_playbook(recs, dex, setters, common={"Incineroar": {"fakeout"}})["styles"]["Trick Room"]
            # without knowing Incineroar has Fake Out, there's no one to compare a Fake Out with
            bare = P.replay_playbook(recs, dex, setters)["styles"]["Trick Room"]
        finally:
            P.MIN_GAMES = old
        by = {c["choice"]: c for c in book["choices"]}
        self.assertGreater(by["Fake Out on the setter"]["edge"], 0)        # Fake Out games all won
        self.assertLess(by["Both Protected"]["edge"], 0)
        self.assertEqual(by["Fake Out on the setter"]["n"], 200)
        self.assertEqual(by["Fake Out on the setter"]["against"], "had it, didn't")
        self.assertEqual(by["Fake Out on the setter"]["compared"], 200)   # the Protect games: had it, didn't use it
        self.assertEqual(by["Both Protected"]["against"], "everyone else")
        self.assertNotIn("Fake Out on the setter", {c["choice"] for c in bare["choices"]})
        self.assertEqual(book["games"], 400)                               # only p1 faces a setter lead

    def test_fake_out_into_psychic_terrain(self):
        from src.playbook import FAILED_FAKE_OUT, _labels
        dex = load_dex("regmc")
        setters = {"Psychic Terrain": {"Indeedee-F"}}
        lead = ["Indeedee-F", "Kingambit"]
        fo = lambda tgt: [["Incineroar", "Fake Out", tgt]]  # noqa: E731
        # grounded target, Psychic Terrain up: it fails, whichever Pokemon it was aimed at
        self.assertEqual(_labels("Psychic Terrain", fo("Kingambit"), "Indeedee-F", ["Incineroar", "Garchomp"], [], {},
                                 setters, dex, their_leads=lead), {FAILED_FAKE_OUT})
        self.assertEqual(_labels("Psychic Terrain", fo("Indeedee-F"), "Indeedee-F", ["Incineroar", "Garchomp"], [], {},
                                 setters, dex, their_leads=lead), {FAILED_FAKE_OUT})
        # a Flying target, or your own terrain setter in the lead: a real Fake Out
        self.assertEqual(_labels("Psychic Terrain", fo("Talonflame"), "Indeedee-F", ["Incineroar", "Garchomp"], [], {},
                                 setters, dex, their_leads=["Indeedee-F", "Talonflame"]), {"Fake Out on its partner"})
        self.assertEqual(_labels("Psychic Terrain", fo("Kingambit"), "Indeedee-F", ["Incineroar", "Rillaboom"], [], {},
                                 setters, dex, their_leads=lead), {"Fake Out on its partner"})

    def test_team_tools(self):
        from src.analysis import build_members
        from src.playbook import team_tools
        from src.team import PokemonSet
        team = [PokemonSet(species="Incineroar", ability="Intimidate", item="Sitrus Berry",
                           moves=["Fake Out", "Taunt", "Flare Blitz", "Parting Shot"]),
                PokemonSet(species="Pelipper", ability="Drizzle", item="Focus Sash", moves=["Tailwind", "Hurricane"])]
        tools = team_tools(build_members(team, load_dex("regmc")))
        self.assertEqual(tools["Fake Out"], ["Incineroar"])
        self.assertEqual(tools["Taunt"], ["Incineroar"])
        self.assertEqual(tools["Tailwind"], ["Pelipper"])
        self.assertEqual(tools["Weather"], ["Pelipper"])
        self.assertEqual(tools["Intimidate"], ["Incineroar"])


class TestNeutralGems(unittest.TestCase):
    def test_one_neutral_team_is_a_hidden_gems_build(self):
        import src.builder as B
        dex, usage = load_dex("regmc"), load_usage("gen9championsvgc2026regmc")
        built = B.build_teams("Garganacl", dex, usage, mode="neutral")
        self.assertEqual(len(built), 3)
        keys = [frozenset(to_id(p.species) for p in t.sets) for t in built]
        self.assertEqual(len(set(keys)), 3)
        gems = [frozenset(to_id(p.species) for p in t.sets) for t in B.build_teams("Garganacl", dex, usage, mode="hidden")]
        self.assertTrue(set(keys) & set(gems))
        old = B.NEUTRAL_GEMS
        B.NEUTRAL_GEMS = 0
        try:
            plain = [frozenset(to_id(p.species) for p in t.sets) for t in B.build_teams("Garganacl", dex, usage, mode="neutral")]
        finally:
            B.NEUTRAL_GEMS = old
        self.assertEqual(len(set(keys) & set(plain)), 2)               # the first two stay Neutral builds



class TestCardSplit(unittest.TestCase):
    def test_strongest_two_lines_shown_watch_always(self):
        from ui.recommendations_tab import card_split
        parts = {"fit": "players pair it with Charizard (3x)", "cover": "resists Water", "hits": "hits Sneasler super effectively",
                 "adds": "adds Speed control", "plan": "plays into your Tailwind"}
        row = {"parts": parts, "synergy": 0.9, "defense": 0.2, "offense": 1.0, "roles": 0.1, "plan": 0.6}
        w = {"synergy": 0.4, "defense": 0.25, "offense": 0.05, "roles": 0.05, "meta": 0.0, "plan": 0.25}
        shown, rest = card_split(row, w)
        self.assertIn("**Fits:**", shown)                 # 0.36: the strongest
        self.assertIn("**Plan:**", shown)                 # 0.15: second
        self.assertIn("**Covers:**", rest)
        self.assertEqual(rest.count("\n") + 1, 3)
        row["parts"] = {**parts, "clash": "next to Kingambit"}
        shown, _ = card_split(row, w)
        self.assertIn("**Watch:**", shown)                # a warning never folds away


class TestHealthCheck(unittest.TestCase):
    def test_checks_read_the_evaluations(self):
        import importlib.util
        from datetime import datetime, timezone
        spec = importlib.util.spec_from_file_location("health_check", Path(__file__).parent.parent / "scripts" / "health_check.py")
        hc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hc)
        names = {n for n, _, _ in hc.checks()}
        for want in ("Recommender beats popularity", "Win model beats damage calcs", "Team check ranks real teams",
                     "Bring model (bring) beats usual picks", "Replays are fresh"):
            self.assertIn(want, names)
        # a year from now nothing is fresh: the freshness checks must fail, not crash
        later = {n: ok for n, ok, _ in hc.checks(now=datetime(2027, 12, 1, tzinfo=timezone.utc))}
        self.assertFalse(later["Replays are fresh"])
        self.assertFalse(later["Usage stats are current"])

if __name__ == "__main__":
    unittest.main()
