"""
Team state. The widgets *are* the team: each slot's fields live in
st.session_state under "s{slot}_{field}". `write_slot` pushes a set into those
keys - only from callbacks or before the widgets render, which is why every
button that edits the team uses on_click - and `read_slot` reads one back.
"""

from __future__ import annotations

import streamlit as st

from src.dex import STATS, Dex
from src.team import PokemonSet, default_set
from src.usage import UsageData
from ui.common import NONE, SLOTS

# ==========================================================================
def k(slot: int, field: str) -> str:
    return f"s{slot}_{field}"


def write_slot(slot: int, pset: PokemonSet | None) -> None:
    ss = st.session_state
    ss[k(slot, "species")] = pset.species if pset else NONE
    if pset is None:
        return
    ss[k(slot, "item")] = pset.item or NONE
    ss[k(slot, "ability")] = pset.ability
    ss[k(slot, "nature")] = pset.nature
    ss[k(slot, "nick")] = pset.nickname
    for i in range(4):
        ss[k(slot, f"move{i}")] = pset.moves[i] if i < len(pset.moves) else NONE
    for stat in STATS:
        ss[k(slot, f"sp_{stat}")] = int(pset.sps.get(stat, 0))


def read_slot(slot: int) -> PokemonSet | None:
    ss = st.session_state
    species = ss.get(k(slot, "species"), NONE)
    if species == NONE:
        return None
    item = ss.get(k(slot, "item"), NONE)
    return PokemonSet(
        species=species,
        item="" if item == NONE else item,
        ability=ss.get(k(slot, "ability"), ""),
        nature=ss.get(k(slot, "nature"), "Serious"),
        nickname=ss.get(k(slot, "nick"), ""),
        moves=[m for m in (ss.get(k(slot, f"move{i}"), NONE) for i in range(4)) if m != NONE],
        sps={s: int(ss.get(k(slot, f"sp_{s}"), 0)) for s in STATS},
    )


def current_team() -> list[PokemonSet]:
    return [p for p in (read_slot(i) for i in range(SLOTS)) if p is not None]


def load_team(team: list[PokemonSet]) -> None:
    for i in range(SLOTS):
        write_slot(i, team[i] if i < len(team) else None)


def starting_set(species: str, dex: Dex, usage: UsageData | None, slot: int) -> PokemonSet:
    """Popular set when usage data exists (respecting Item Clause), else a blank set."""
    taken = {p.item for i, p in enumerate(read_slot(j) for j in range(SLOTS)) if p and i != slot and p.item}
    if usage is not None and st.session_state.get("autofill", True):
        pset = usage.popular_set(species, dex, taken_items=taken)
        if pset is not None:
            return pset
    return default_set(dex, species)


def on_species_change(slot: int, dex: Dex, usage: UsageData | None) -> None:
    species = st.session_state[k(slot, "species")]
    write_slot(slot, None if species == NONE else starting_set(species, dex, usage, slot))


def apply_preset(slot: int, pset: PokemonSet) -> None:
    taken = {p.item for j, p in enumerate(read_slot(x) for x in range(SLOTS)) if p and j != slot}
    if pset.item and pset.item in taken:
        st.session_state["import_warnings"] = [
            f"{pset.item} is already on your team - Item Clause allows one of each item."]
    write_slot(slot, pset)


def add_set_to_team(pset: PokemonSet) -> None:
    for slot in range(SLOTS):
        if st.session_state.get(k(slot, "species"), NONE) == NONE:
            write_slot(slot, pset)
            return


def add_to_team(species: str, dex: Dex, usage: UsageData | None) -> bool:
    for slot in range(SLOTS):
        if st.session_state.get(k(slot, "species"), NONE) == NONE:
            write_slot(slot, starting_set(species, dex, usage, slot))
            return True
    return False
