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


class TestApp(unittest.TestCase):
    def assertClean(self, at: AppTest):
        self.assertFalse(at.exception, [e.value for e in at.exception])

    def test_example_team_renders_every_tab(self):
        at = click(fresh(), label="Example team")
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Garganacl")
        self.assertFalse(at.error, [e.value for e in at.error])  # the example team is legal

    def test_add_from_recommendations_and_remove(self):
        at = fresh()
        add = next(b for b in at.button if b.key and b.key.startswith("rec_add_"))
        at = add.click().run()
        self.assertClean(at)
        self.assertNotEqual(at.session_state["s0_species"], "—")
        at = click(at, key="s0_rm")
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "—")

    def test_species_change_and_preset(self):
        at = click(fresh(), label="Example team")
        species = next(s for s in at.selectbox if s.key == "s0_species")
        at = species.set_value("Pelipper").run()
        self.assertClean(at)
        at = click(at, key="s0_apply_preset")
        self.assertClean(at)
        self.assertEqual(at.session_state["s0_species"], "Pelipper")

    def test_singles_format(self):
        at = click(fresh(), label="Example team")
        at = at.sidebar.selectbox[0].set_value("gen9championsbssregmc").run()
        self.assertClean(at)


if __name__ == "__main__":
    unittest.main()
