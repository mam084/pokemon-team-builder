"""Recommender, presets, roles, matchups vs the meta, the evaluation harness and two-Mega teams."""

import unittest

from src.analysis import build_members, mega_variants
from src.dex import load_dex, to_id
from src.evaluate import evaluate, load_tournament_teams, split_by_date
from src.paste import parse_paste
from src.matchup import (best_bring, build_archetypes, counter_picks, meta_matchups, opponent_members,
                         pair_matrix, pair_score, team_score)
from src.presets import presets_for
from src.recommend import recommend
from src.roles import meta_roles, set_roles
from src.team import PokemonSet
from src.usage import load_usage

from tests.test_core import FIXTURES, GARGANACL_TEAM, sample_usage


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

if __name__ == "__main__":
    unittest.main()
