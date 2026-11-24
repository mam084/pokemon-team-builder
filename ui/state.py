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


# Choices on one tab that must survive a visit to another (they have no widget default).
KEEP = {"rec_mode", "swap_mode", "swap_focus", "slot_tab_index", "poke_name", "opp_team", "opp_mega",
        "detail_pick"}


def keep_state() -> None:
    """Only the open tab is built, and Streamlit drops the values of widgets it didn't draw this
    run, including the team itself, which lives in the Team tab's widgets. Re-saving them at the
    start of each run makes them app state, so they survive. Call before any widget is drawn."""
    ss = st.session_state
    fields = ["species", "item", "ability", "nature", "nick"] + [f"move{i}" for i in range(4)] + \
             [f"sp_{stat}" for stat in STATS]
    for key in [k(slot, f) for slot in range(SLOTS) for f in fields] + sorted(KEEP):
        if key in ss:
            ss[key] = ss[key]


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


def drop_unknown_species(dex: Dex, fmt_label: str) -> None:
    """Take off any Pokémon this format's dex doesn't have (a pasted or linked team from another format, or
    a switch to a smaller regulation): nothing can be shown or calculated for them, and they used to break
    the page. Says so on the next notice, once per Pokémon."""
    ss = st.session_state
    for i in range(SLOTS):
        species = ss.get(k(i, "species"), NONE)
        if species != NONE and dex.get_species(species) is None:
            write_slot(i, None)
            note = f"Took {species} off the team: it isn't in {fmt_label}."
            warnings = ss.setdefault("import_warnings", [])
            warnings[:] = [w for w in warnings if not w.startswith(f"{species} isn't legal")] + [note]


def load_team(team: list[PokemonSet]) -> None:
    for i in range(SLOTS):
        write_slot(i, team[i] if i < len(team) else None)


def starting_set(species: str, dex: Dex, usage: UsageData | None, slot: int) -> PokemonSet:
    """Popular set when usage data exists (respecting Item Clause), else a blank set."""
    taken = {p.item for i, p in enumerate(read_slot(j) for j in range(SLOTS)) if p and i != slot and p.item}
    if usage is not None and st.session_state.get("autofill", True):
        pset = usage.popular_set(species, dex, taken_items=taken, team=[p for j in range(SLOTS) if j != slot and (p := read_slot(j)) is not None])
        if pset is not None:
            return pset
    return default_set(dex, species)


def slot_labels() -> list[str]:
    """Tab labels for the six slots: the species, or 'Slot N' when empty (always unique)."""
    labels: list[str] = []
    for i in range(SLOTS):
        sp = st.session_state.get(k(i, "species"), NONE)
        label = sp if sp != NONE else f"Slot {i + 1}"
        labels.append(label if label not in labels else f"{label} ({i + 1})")
    return labels


def on_slot_tab_change() -> None:
    labels = slot_labels()
    chosen = st.session_state.get("slot_tabs")
    if chosen in labels:
        st.session_state["slot_tab_index"] = labels.index(chosen)


def on_species_change(slot: int, dex: Dex, usage: UsageData | None) -> None:
    species = st.session_state[k(slot, "species")]
    write_slot(slot, None if species == NONE else starting_set(species, dex, usage, slot))
    # the slot's tab is renamed; keep it selected instead of jumping back to slot 1
    st.session_state["slot_tab_index"] = slot


def open_slot(slot: int) -> None:
    """Callback for a team card: show that slot's editor on the Team tab."""
    ss = st.session_state
    ss["slot_tab_index"] = slot
    ss["slot_tabs"] = slot_labels()[slot]
    ss["main_tabs"] = "Team"


def apply_spread(slot: int, sps: dict[str, int]) -> None:
    for stat in STATS:
        st.session_state[k(slot, f"sp_{stat}")] = int(sps.get(stat, 0))


def fill_slot(slot: int, species: str, dex: Dex, usage: UsageData | None) -> None:
    """Put a Pokémon (its popular set) in this slot and keep the slot selected."""
    write_slot(slot, starting_set(species, dex, usage, slot))
    st.session_state["slot_tab_index"] = slot


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
