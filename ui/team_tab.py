"""Team tab: the six-slot set editor and the team strip shown above the tabs."""

from __future__ import annotations

import html

import streamlit as st

from src.dex import STAT_LABELS, STATS, Dex, to_id
from src.presets import presets_for
from src.roles import role_text, set_roles, species_roles
from src.team import PokemonSet
from src.usage import UsageData
from ui.common import NONE, SLOTS, nature_label, ranked_options, sprite, type_badges
from ui.state import apply_preset, k, on_species_change, read_slot, write_slot

def slot_editor(slot: int, dex: Dex, usage: UsageData | None) -> None:
    ss = st.session_state
    species_names = [s.name for s in dex.selectable_species()]
    sheet_usage = usage.team_sheet_usage(dex) if usage else {}
    species_opts = [NONE] + ranked_options(species_names, sheet_usage)
    if ss.get(k(slot, "species"), NONE) not in species_opts:
        ss[k(slot, "species")] = NONE

    top = st.columns([1, 3, 3])
    current = ss.get(k(slot, "species"), NONE)
    top[1].selectbox(
        "Pokémon", species_opts, key=k(slot, "species"),
        on_change=on_species_change, args=(slot, dex, usage),
        format_func=lambda n: f"{n}  ·  {sheet_usage[n]:.1f}%" if n in sheet_usage else n,
    )
    if current == NONE:
        top[0].markdown("<div style='font-size:3rem;text-align:center;opacity:.3'>+</div>", unsafe_allow_html=True)
        st.caption("Pick a Pokémon - sorted by usage, with its usage share shown.")
        return

    pset = read_slot(slot)
    base = dex.get_species(pset.species)
    form = pset.battle_form(dex)
    top[0].image(sprite(form, dex), width=96)
    top[2].text_input("Nickname (optional)", key=k(slot, "nick"))

    # item / ability / nature
    c = st.columns(3)
    item_pct = usage.combined_section(base.name, "items", dex) if usage else {}
    items = [NONE] + ranked_options(dex.legal_items(base.name), item_pct)
    if ss.get(k(slot, "item"), NONE) not in items:
        ss[k(slot, "item")] = NONE
    c[0].selectbox("Item", items, key=k(slot, "item"),
                   format_func=lambda n: f"{n}  ·  {item_pct[to_id(n)]:.0f}%" if to_id(n) in item_pct else n)
    abilities = list(base.abilities)
    if ss.get(k(slot, "ability")) not in abilities:
        ss[k(slot, "ability")] = abilities[0]
    c[1].selectbox("Ability", abilities, key=k(slot, "ability"),
                   disabled=form.is_mega,
                   help=f"Mega form uses {form.abilities[0]}" if form.is_mega else None)
    natures = sorted(n["name"] for n in dex.natures.values())
    if ss.get(k(slot, "nature")) not in natures:
        ss[k(slot, "nature")] = "Serious"
    c[2].selectbox("Nature", natures, key=k(slot, "nature"), format_func=lambda n: nature_label(n, dex))

    if form.is_mega:
        st.markdown(f"**Mega Evolves into {form.name}** {type_badges(form.types)} · {form.abilities[0]}",
                    unsafe_allow_html=True)
    else:
        st.markdown(type_badges(form.types), unsafe_allow_html=True)
    doubles = ss.get("doubles", True)
    role_line = f"**This set:** {role_text(set_roles(pset, dex, doubles), 5)}"
    if usage and usage.variants(base.name, dex):
        role_line += f"  \n**Usually plays:** {role_text(species_roles(base.name, usage, dex, doubles), 5, True)}"
    st.caption(role_line)

    # presets
    presets = presets_for(base.name, usage, dex)
    if presets:
        if ss.get(k(slot, "preset"), 0) not in range(len(presets)):
            ss[k(slot, "preset")] = 0
        pc = st.columns([5, 1])
        choice = pc[0].selectbox(
            "Preset (common sets from ladder stats)", range(len(presets)), key=k(slot, "preset"),
            format_func=lambda i: f"{presets[i].name}  ·  ~{presets[i].weight:.0f}% of sets  —  "
                                  f"{', '.join(presets[i].pset.moves)}",
        )
        pc[1].markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        pc[1].button("Apply", key=k(slot, "apply_preset"), width="stretch",
                     on_click=apply_preset, args=(slot, presets[choice].pset))

    # moves
    move_pct = usage.combined_section(base.name, "moves", dex) if usage else {}
    move_opts = [NONE] + ranked_options(dex.learnable_moves(base.name), move_pct)

    def move_label(n: str) -> str:
        if n == NONE:
            return n
        mv = dex.get_move(n)
        bp = f" {mv['basePower']}" if mv["basePower"] else ""
        pct = f"  ·  {move_pct[to_id(n)]:.0f}%" if to_id(n) in move_pct else ""
        return f"{n}  ({mv['type']} {mv['category'][:4]}{bp}){pct}"

    mc = st.columns(4)
    for i in range(4):
        if ss.get(k(slot, f"move{i}"), NONE) not in move_opts:
            ss[k(slot, f"move{i}")] = NONE
        mc[i].selectbox(f"Move {i + 1}", move_opts, key=k(slot, f"move{i}"), format_func=move_label)

    # stat points + final stats
    spent = sum(int(ss.get(k(slot, f"sp_{s}"), 0)) for s in STATS)
    remaining = dex.rules["statPointTotal"] - spent
    st.markdown(
        f"**Stat Points** — {spent}/{dex.rules['statPointTotal']} used"
        + (f" · :red[{-remaining} over]" if remaining < 0 else f" · {remaining} left")
    )
    if form.is_mega:
        st.caption(f"Stats below are {form.name}'s, after Mega Evolving.")
    sc = st.columns(6)
    nature = dex.get_nature(ss.get(k(slot, "nature")))
    stats = pset.stats(dex)
    for i, stat in enumerate(STATS):
        arrow = ""
        if nature and nature["plus"] == stat:
            arrow = " ▲"
        elif nature and nature["minus"] == stat:
            arrow = " ▼"
        sc[i].number_input(f"{STAT_LABELS[stat]}{arrow}", min_value=0, max_value=dex.rules["statPointMax"],
                           step=1, key=k(slot, f"sp_{stat}"))
        sc[i].metric(f"{STAT_LABELS[stat]} stat", stats[stat], help=f"Base {form.base_stats[stat]}",
                     label_visibility="collapsed")

    st.button("Remove", key=k(slot, "rm"), on_click=write_slot, args=(slot, None))


def team_strip(team: list[PokemonSet], dex: Dex) -> None:
    """One wrapping row of team cards: six across on desktop, two or three per line on a phone."""
    if not team:
        st.caption("No Pokémon yet. Pick some on the Team tab, add a suggestion from Recommendations, "
                   "or load the example team from the sidebar.")
        return
    doubles = st.session_state.get("doubles", True)
    cards = []
    for pset in team:
        form = pset.battle_form(dex)
        roles = role_text(set_roles(pset, dex, doubles), 2)
        if form.is_mega:
            held = f"@ {html.escape(pset.item)} &rarr; <b>{form.name}</b>"
        else:
            held = f"@ {html.escape(pset.item)}" if pset.item else "<i>no item</i>"
        cards.append(
            "<div style='flex:1 1 140px;max-width:220px;min-width:120px'>"
            f"<img src='{sprite(form, dex)}' width='56' height='56' style='image-rendering:pixelated' alt=''>"
            f"<div style='font-weight:600'>{html.escape(pset.nickname or pset.species)}</div>"
            f"<div style='font-size:0.8rem;margin-bottom:2px'>{held}</div>"
            f"<div>{type_badges(form.types)}</div>"
            f"<div style='font-size:0.8rem;opacity:0.7;margin-top:2px'>{roles}</div></div>"
        )
    st.markdown(f"<div style='display:flex;flex-wrap:wrap;gap:12px 16px'>{''.join(cards)}</div>",
                unsafe_allow_html=True)


def team_tab(dex: Dex, usage: UsageData | None) -> None:
    labels = []
    for i in range(SLOTS):
        sp = st.session_state.get(k(i, "species"), NONE)
        labels.append(f"{i + 1}. {sp}" if sp != NONE else f"{i + 1}. empty")
    for i, tab in enumerate(st.tabs(labels)):
        with tab:
            slot_editor(i, dex, usage)
