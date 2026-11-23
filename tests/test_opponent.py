"""Battle plan from their team sheet (src/opponent.py, ui/battle_plan_tab.facing_archetype)."""

import unittest

from src.dex import load_dex
from src.opponent import FILLED_SPREAD, mega_first, sets_from_sheet, style_of
from src.usage import load_usage
from tests.test_app import click, fresh, open_tab

OTS = """Charizard @ Charizardite Y
Ability: Blaze
- Heat Wave
- Solar Beam
- Protect
- Weather Ball

Farigiraf @ Sitrus Berry
Ability: Armor Tail
- Trick Room
- Psychic
- Helping Hand
- Protect

Sneasler @ Focus Sash
Ability: Unburden
EVs: 2 HP / 32 Atk / 32 Spe
Jolly Nature
- Close Combat
- Dire Claw
- Fake Out
- Protect

Aerodactyl @ Aerodactylite
Ability: Unnerve
- Rock Slide
- Tailwind
- Protect
- Dual Wingbeat
"""


class TestSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.usage, cls.dex = load_usage("gen9championsvgc2026regmc"), load_dex("regmc")

    def test_keeps_their_sets_and_fills_the_spread(self):
        sets, filled, warnings = sets_from_sheet(OTS, self.dex, self.usage)
        self.assertEqual([p.species for p in sets], ["Charizard", "Farigiraf", "Sneasler", "Aerodactyl"])
        sneasler = sets[2]
        self.assertEqual(sneasler.item, "Focus Sash")              # theirs, not the usual White Herb
        self.assertEqual(sneasler.nature, "Jolly")
        self.assertNotIn("Sneasler", filled)                       # full set: nothing filled
        self.assertEqual(filled["Charizard"], [FILLED_SPREAD])
        common = self.usage.popular_set("Charizard", self.dex)
        self.assertEqual(sets[0].nature, common.nature)
        self.assertEqual(sets[0].moves, ["Heat Wave", "Solar Beam", "Protect", "Weather Ball"])  # moves kept
        self.assertEqual(warnings, [])

    def test_unknown_pokemon_dropped_with_warning(self):
        sets, _, warnings = sets_from_sheet("Notamon @ Leftovers\n- Tackle\n\n" + OTS, self.dex, self.usage)
        self.assertEqual(len(sets), 4)
        self.assertTrue(warnings)

    def test_one_mega_and_style_from_the_sets(self):
        sets, _, _ = sets_from_sheet(OTS, self.dex, self.usage)
        first = mega_first(sets, self.dex)
        self.assertEqual(first[0].species, "Charizard")
        tr, weather, tags = style_of(first, self.dex)
        self.assertTrue(tr)
        self.assertEqual(weather, "sun")                           # Mega Charizard Y's Drought
        aero = mega_first(sets, self.dex, "Aerodactyl")
        self.assertEqual(aero[0].species, "Aerodactyl")
        self.assertIsNone(style_of(aero, self.dex)[1])             # base Charizard (Blaze) sets no sun
        no_tr = [p for p in first if p.species != "Farigiraf"]
        self.assertFalse(style_of(no_tr, self.dex)[0])


class TestBattlePlanPaste(unittest.TestCase):
    def test_paste_their_sheet(self):
        at = open_tab(click(fresh(), label="Example team"), "Battle plan")
        at.segmented_control(key="opp_input").set_value("Paste their team sheet").run()
        at = at.text_area(key="opp_paste").input(OTS).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        at = at.selectbox(key="opp_mega").set_value("Charizard").run()
        self.assertFalse(at.exception)
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("Your team vs their team", md)
        self.assertIn("Focus Sash", md)                            # their item on the card
        caps = " ".join(c.value for c in at.caption)
        self.assertIn("taken from the most common set", caps)
        self.assertIn("Trick Room", caps)                          # their Farigiraf's Trick Room counts


if __name__ == "__main__":
    unittest.main()
