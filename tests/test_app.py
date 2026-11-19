"""
UI smoke tests: drive the Streamlit app headlessly through the flows that
edit the team, since those are the easiest to break (widget state can only be
changed from callbacks once a widget has rendered).
"""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def click(at: AppTest, key: str | None = None, label: str | None = None) -> AppTest:
    buttons = list(at.button) + list(at.sidebar.button)
    button = next(b for b in buttons if (key and b.key == key) or (label and b.label == label))
    return button.click().run()


TABS = ["Team", "Analysis", "Matchups", "Damage calc", "Recommendations", "Pokémon", "Meta"]


def open_tab(at: AppTest, name: str) -> AppTest:
    """Only the open tab is built, so open it as a user would."""
    at.session_state["main_tabs"] = name
    return at.run()


class TestApp(unittest.TestCase):
    def assertClean(self, at: AppTest):
        self.assertFalse(at.exception, [e.value for e in at.exception])

    def test_example_team_renders_every_tab(self):
        at = click(fresh(), label="Example team")
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Aerodactyl")
        self.assertFalse(at.error, [e.value for e in at.error])  # the example team is legal
        team = [at.session_state[f"s{i}_species"] for i in range(6)]
        for name in TABS[1:] + ["Team"]:
            at = open_tab(at, name)
            self.assertClean(at)
            self.assertFalse(at.error, (name, [e.value for e in at.error]))
        # only the open tab is built, and the team (held in the Team tab's widgets) must survive
        self.assertEqual([at.session_state[f"s{i}_species"] for i in range(6)], team)
        self.assertEqual(at.session_state["s1_move0"], "Hyper Voice")

    def test_pokemon_tab_build_around_and_real_team(self):
        at = open_tab(fresh(), "Pokémon")
        at.selectbox(key="poke_name").set_value("Feraligatr-Mega")
        at = at.run()
        self.assertClean(at)
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("Usually paired with", md)
        self.assertIn("After one Dragon Dance", md)
        at = at.button(key="poke_build").click().run()      # empty team: the builder on the Team screen
        self.assertClean(at)
        self.assertEqual(at.session_state["main_tabs"], "Team")
        self.assertEqual(at.session_state["build_core"], "Feraligatr")
        at = open_tab(at, "Pokémon")
        at = at.button(key="poke_proven_load").click().run()
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Feraligatr")
        self.assertNotEqual(at.session_state["s5_species"], "—")

    def test_add_from_recommendations_and_remove(self):
        at = open_tab(fresh(), "Recommendations")
        add = next(b for b in at.button if b.key and b.key.startswith("rec_add_"))
        at = add.click().run()
        self.assertClean(at)
        self.assertNotEqual(at.session_state["s0_species"], "—")
        at = click(open_tab(at, "Team"), key="s0_rm")
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "—")

    def test_species_change_and_preset(self):
        at = click(fresh(), label="Example team")
        species = next(s for s in at.selectbox if s.key == "s0_species")
        at = species.set_value("Pelipper").run()
        self.assertClean(at)
        preset = next(s for s in at.selectbox if s.key == "s0_preset")
        at = preset.set_value(1).run()  # picking a common set loads it at once, then the menu resets
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Pelipper")
        self.assertIsNone(at.session_state["s0_preset"])

    def test_quick_picks_fill_the_slot(self):
        at = click(fresh(), key="s0_example")  # the in-page example button (the sidebar is hidden on a phone)
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Aerodactyl")
        at = click(at, key="s5_rm")
        at = click(at, key="s5_quick0")  # a top pick for the team, straight into that slot
        self.assertClean(at)
        self.assertNotEqual(at.session_state["s5_species"], "—")
        self.assertEqual(at.session_state["slot_tab_index"], 5)

    def test_singles_format(self):
        at = click(fresh(), label="Example team")
        at = at.sidebar.selectbox[0].set_value("gen9championsbssregmc").run()
        self.assertClean(at)

    def test_cards_open_slots_and_spread_pills(self):
        at = click(fresh(), key="s0_example")
        at = click(at, key="tp_edit3")  # tapping a team card opens that Pokémon's editor
        self.assertClean(at)
        self.assertEqual(at.session_state["slot_tabs"], at.session_state["s3_species"])
        self.assertEqual(at.session_state["slot_tab_index"], 3)
        at = next(p for p in at.button_group if p.key == "s0_spread").set_value("Fast attacker").run()
        self.assertClean(at)
        sps = {s: at.session_state[f"s0_sp_{s}"] for s in ["hp", "atk", "def", "spa", "spd", "spe"]}
        self.assertEqual(sum(sps.values()), 66)
        self.assertEqual(sps["spe"], 32)
        self.assertIsNone(at.session_state["s0_spread"])


if __name__ == "__main__":
    unittest.main()
