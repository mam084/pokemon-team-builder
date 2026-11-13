"""Constants, chart palettes and small rendering helpers shared by every tab."""

from __future__ import annotations

import streamlit as st

from src.dex import STAT_LABELS, Dex, to_id

NONE = "—"
SLOTS = 6

# Palette (dataviz reference instance): diverging blue <-> red with a gray
# midpoint for matchups, series blue for "your team", muted gray for context.
MUTED = "#898781"
PALETTES = {
    # Dataviz reference palette, stepped separately for each surface: on light the
    # strongest effect is the darkest cell, on dark it is the brightest.
    "light": {"blue": "#2a78d6", "context": "#c3c2b7", "mid": "#f0efec",
              "resist": ("#104281", "#256abf", "#86b6ef"), "weak": ("#f2a3a2", "#b8282a")},
    "dark": {"blue": "#3987e5", "context": "#52514e", "mid": "#383835",
             # brightest steps that still hold white cell labels at >= 4:1
             "resist": ("#2a78d6", "#1c5cab", "#104281"), "weak": ("#7a2223", "#d03b3b")},
}


def palette() -> dict:
    """Chart colors for the theme the viewer is using (Settings menu: Light / Dark / System)."""
    theme = getattr(getattr(st, "context", None), "theme", None)
    mode = getattr(theme, "type", None) or "light"
    return PALETTES["dark" if mode == "dark" else "light"]


def matchup_scale() -> list:
    """log2(multiplier) clipped to [-2, 2], immunity drawn at -2.5."""
    p = palette()
    strong, mid_r, mild_r = p["resist"]
    mild_w, strong_w = p["weak"]
    return [[0.0, strong], [0.11, mid_r], [0.33, mild_r], [0.56, p["mid"]], [0.78, mild_w], [1.0, strong_w]]


TYPE_COLORS = {
    "Normal": "#9fa19f", "Fire": "#e62829", "Water": "#2980ef", "Electric": "#fac000",
    "Grass": "#3fa129", "Ice": "#3dcef3", "Fighting": "#ff8000", "Poison": "#9141cb",
    "Ground": "#915121", "Flying": "#81b9ef", "Psychic": "#ef4179", "Bug": "#91a119",
    "Rock": "#afa981", "Ghost": "#704170", "Dragon": "#5060e1", "Dark": "#624d4e",
    "Steel": "#60a1b8", "Fairy": "#ef70ef",
}


def sprite(species, dex: Dex) -> str:
    """Sprite of the team-sheet Pokemon (newer Mega formes lack sprites on Showdown)."""
    if species.is_mega or species.battle_only:
        base = dex.get_species(species.battle_only[0] if species.battle_only else species.base_species)
        species = base or species
    return species.sprite_url


def type_badges(types) -> str:
    return " ".join(
        f"<span style='background:{TYPE_COLORS.get(t, MUTED)};color:white;padding:1px 8px;"
        f"border-radius:10px;font-size:0.75rem;font-weight:600'>{t}</span>"
        for t in types
    )


def nature_label(name: str, dex: Dex) -> str:
    n = dex.get_nature(name)
    if not n or not n["plus"]:
        return f"{name} (neutral)"
    return f"{name} (+{STAT_LABELS[n['plus']]} −{STAT_LABELS[n['minus']]})"


def fmt_mult(x: float) -> str:
    return {0: "0", 0.25: "¼", 0.5: "½", 1: "", 2: "2×", 4: "4×"}.get(x, f"{x:g}×")


def ranked_options(all_names: list[str], popular: dict) -> list[str]:
    """Popular choices first (in usage order), then everything else alphabetically."""
    lookup = {to_id(n): n for n in all_names}
    first = [lookup[to_id(p)] for p in popular if to_id(p) in lookup]
    rest = [n for n in all_names if n not in set(first)]
    return first + rest
