"""Constants, chart palettes and small rendering helpers shared by every tab."""

from __future__ import annotations

import re

import functools
import json
from pathlib import Path

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


@functools.lru_cache(maxsize=8)
def _sprites_available(regulation: str) -> frozenset:
    """Mega / battle formes with their own Showdown sprite (scripts/check_sprites.py)."""
    path = Path(__file__).resolve().parent.parent / "data" / "dex" / f"{regulation}_sprites.json"
    try:
        return frozenset(json.loads(path.read_text())["available"])
    except (OSError, ValueError, KeyError):
        return frozenset()


def sprite(species, dex: Dex) -> str:
    """The forme's own sprite when Showdown has one (most older Megas), else the base Pokemon's."""
    if (species.is_mega or species.battle_only) and species.sprite in _sprites_available(dex.regulation):
        return species.sprite_url
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


def anchor_id(title: str) -> str:
    """'Against the top 30' -> 'sec-against-the-top-30' (for jump links)."""
    return "sec-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def section(title: str) -> None:
    """A section header that jump_row links can reach."""
    st.subheader(title, anchor=anchor_id(title))


def jump_row(titles: list[str]) -> None:
    """A row of links to sections further down the page: long tabs on a phone."""
    links = "".join(f"<a href='#{anchor_id(t)}'>{t}</a>" for t in titles)
    st.markdown(f"<div class='jump-row'>Jump to: {links}</div>", unsafe_allow_html=True)


NEW_REGULATION_DAYS = 14


def no_usage(fmt, message: str) -> None:
    """The "needs usage stats" note. In a regulation's first days it says when the data comes: usage is
    built from the ladder's replays (src/replay_usage.py), fetched twice a day, so it's at most hours away."""
    from datetime import date
    note = ""
    try:
        young = fmt.current and fmt.start and (date.today() - date.fromisoformat(fmt.start)).days <= NEW_REGULATION_DAYS
    except ValueError:
        young = False
    if young:
        m = re.search(r"Reg [A-Z]-[A-Z]+", fmt.label)
        note = (f" {m.group(0) if m else 'This regulation'} has just started: its usage comes from the ladder's "
                "replays, which are fetched twice a day, so this fills in within hours.")
    st.info(message + note)
