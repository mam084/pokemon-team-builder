"""Team tab: the six-slot set editor and the team strip shown above the tabs."""

from __future__ import annotations


import streamlit as st

from src.dex import STAT_LABELS, STATS, Dex, to_id
from src.presets import presets_for
from src.roles import role_text, set_roles, species_roles

from src.usage import UsageData
from ui.common import NONE, nature_label, ranked_options, sprite, type_badges
from ui.state import (apply_preset, current_team, fill_slot, k, on_slot_tab_change, on_species_change, read_slot,
                      slot_labels, write_slot)
from ui.sidebar import import_paste, load_example

QUICK = 4  # quick picks shown in an empty slot


def quick_picks(dex: Dex, usage: UsageData | None) -> list[tuple[str, str]]:
    """(Pokémon, one-line reason) to offer in an empty slot: the top recommendations for the
    team so far, in the style picked on the Recommendations tab; the most used ones for an
    empty team."""
    if usage is None:
        return []
    team = current_team()
    if not team:
        sheet = usage.team_sheet_usage(dex)
        return [(n, f"{sheet[n]:.0f}% of ladder teams") for n in list(sheet)[:QUICK]]
    from src.analysis import build_members
    from src.recommend import DEFAULT_WEIGHTS, EXPLORE_WEIGHTS, MODES, recommend
    ss = st.session_state
    mode = ss.get("rec_mode") if ss.get("rec_mode") in MODES else "neutral"
    defaults = DEFAULT_WEIGHTS if mode == "popular" else EXPLORE_WEIGHTS
    weights = {key: ss.get(f"w_{mode}_{key}", defaults[key]) for key in DEFAULT_WEIGHTS}
    recs = recommend(build_members(team, dex), dex, usage, doubles=ss.get("doubles", True),
                     weights=weights, top_n=QUICK, mode=mode)
    return [(row["pokemon"], row["why"].split(";")[0]) for _, row in recs.head(QUICK).iterrows()]


def empty_slot(slot: int, dex: Dex, usage: UsageData | None, picks: list[tuple[str, str]]) -> None:
    team = current_team()
    if picks:
        st.markdown("<div class='box-title'>" + ("Popular starting points" if not team else
                    "Top picks for your team") + "</div>", unsafe_allow_html=True)
        for n, (name, why) in enumerate(picks):
            if n % 2 == 0:  # a new row per pair keeps the order when columns stack on a phone
                cols = st.columns(2)
            with cols[n % 2].container(border=True):
                form = dex.get_species(name)
                img = f"<img class='card-sprite' src='{sprite(form, dex)}' alt=''>" if form is not None else ""
                st.markdown(f"<div class='card-head'>{img}<div><b>{name}</b><br>"
                            f"<span style='font-size:.8rem;opacity:.75'>{why[0].upper() + why[1:]}</span>"
                            f"</div></div>", unsafe_allow_html=True)
                st.button(f"Add {name}", key=k(slot, f"quick{n}"), width="stretch",
                          on_click=fill_slot, args=(slot, name, dex, usage))
        if team:
            st.caption("More picks, and why, on the Recommendations tab.")
    if not team:
        c = st.columns(2)
        c[0].button("Load the example team", width="stretch", type="primary",
                    on_click=load_example, args=(dex,), key=k(slot, "example"))
        with c[1].popover("Paste a team", width="stretch"):
            text = st.text_area("Showdown paste", height=180, key=k(slot, "paste"),
                                placeholder="Paste a Showdown team here…", label_visibility="collapsed")
            st.button("Import", width="stretch", disabled=not text.strip(), key=k(slot, "paste_go"),
                      on_click=import_paste, args=(dex, k(slot, "paste")))
        st.caption("Or build a whole team around one Pokémon on the Recommendations tab.")


def load_preset(slot: int, presets: list) -> None:
    """Callback: a preset picked from the menu loads at once; the menu then resets."""
    key = k(slot, "preset")
    choice = st.session_state.get(key)
    if choice is not None:
        apply_preset(slot, presets[choice].pset)
    st.session_state[key] = None

def slot_editor(slot: int, dex: Dex, usage: UsageData | None, picks: list[tuple[str, str]]) -> None:
    ss = st.session_state
    species_names = [s.name for s in dex.selectable_species()]
    sheet_usage = usage.team_sheet_usage(dex) if usage else {}
    species_opts = [NONE] + ranked_options(species_names, sheet_usage)
    if ss.get(k(slot, "species"), NONE) not in species_opts:
        ss[k(slot, "species")] = NONE

    current = ss.get(k(slot, "species"), NONE)
    top = st.columns([1, 6]) if current != NONE else [st.container(), st.container()]
    top[1].selectbox(
        "Pokémon", species_opts, key=k(slot, "species"),
        on_change=on_species_change, args=(slot, dex, usage),
        format_func=lambda n: f"{n}  ·  {sheet_usage[n]:.1f}%" if n in sheet_usage else n,
    )
    if current == NONE:
        st.caption("Sorted by usage, with each one's share of ladder teams.")
        empty_slot(slot, dex, usage, picks)
        return

    pset = read_slot(slot)
    base = dex.get_species(pset.species)
    form = pset.battle_form(dex)
    top[0].image(sprite(form, dex), width=80)

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
        if ss.get(k(slot, "preset")) not in range(len(presets)):
            ss[k(slot, "preset")] = None
        st.selectbox(
            "Load a common set (from ladder stats)", range(len(presets)), key=k(slot, "preset"),
            index=None, placeholder="Pick one to replace this set…",
            on_change=load_preset, args=(slot, presets),
            format_func=lambda i: f"{presets[i].name}  ·  ~{presets[i].weight:.0f}% of sets  —  "
                                  f"{', '.join(presets[i].pset.moves)}",
        )

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

    left, right = st.columns(2, gap="medium")
    with left.container(border=True, key=f"moves_box{slot}"):
        st.markdown("<div class='box-title'>Moves</div>", unsafe_allow_html=True)
        for i in range(4):
            if ss.get(k(slot, f"move{i}"), NONE) not in move_opts:
                ss[k(slot, f"move{i}")] = NONE
            st.selectbox(f"Move {i + 1}", move_opts, key=k(slot, f"move{i}"), format_func=move_label,
                         label_visibility="collapsed")

    # stat points + final stats, one row per stat
    spent = sum(int(ss.get(k(slot, f"sp_{s}"), 0)) for s in STATS)
    total = dex.rules["statPointTotal"]
    remaining = total - spent
    left_txt = f":red[{-remaining} over]" if remaining < 0 else f"{remaining} left"
    nature = dex.get_nature(ss.get(k(slot, "nature")))
    stats = pset.stats(dex)
    with right.container(border=True, key=f"stats_box{slot}"):
        st.markdown(f"<div class='box-title'>Stat points <span class='box-sub'>{spent}/{total} used</span></div>",
                    unsafe_allow_html=True)
        if remaining:
            st.caption(left_txt)
        head = st.columns([1.3, 3, 1.4], vertical_alignment="bottom")
        head[0].caption("Stat")
        head[1].caption("Points")
        head[2].caption("Final" + (" (Mega)" if form.is_mega else ""))
        for stat in STATS:
            arrow = ""
            if nature and nature["plus"] == stat:
                arrow = " <span class='nat-up'>▲</span>"
            elif nature and nature["minus"] == stat:
                arrow = " <span class='nat-down'>▼</span>"
            row = st.columns([1.3, 3, 1.4], vertical_alignment="center")
            row[0].markdown(f"<div class='stat-name'>{STAT_LABELS[stat]}{arrow}</div>", unsafe_allow_html=True)
            row[1].number_input(STAT_LABELS[stat], min_value=0, max_value=dex.rules["statPointMax"], step=1,
                                key=k(slot, f"sp_{stat}"), label_visibility="collapsed")
            row[2].markdown(f"<div class='stat-final' title='Base {form.base_stats[stat]}'>{stats[stat]}</div>",
                            unsafe_allow_html=True)

    bottom = st.columns([3, 1], vertical_alignment="bottom")
    nick = ss.get(k(slot, "nick"), "")
    with bottom[0].popover(f"Nickname: {nick}" if nick else "Add a nickname"):
        st.text_input("Nickname", key=k(slot, "nick"), max_chars=12)
    bottom[1].button("Remove", key=k(slot, "rm"), on_click=write_slot, args=(slot, None), width="stretch")


def team_tab(dex: Dex, usage: UsageData | None) -> None:
    # The selected slot must survive reruns: a key keeps it when a warning box appears
    # above the tabs, and the remembered index re-selects it when its label changes
    # (Streamlit treats tabs with new labels as new tabs).
    labels = slot_labels()
    picks = quick_picks(dex, usage) if any(lb.startswith("Slot ") for lb in labels) else []
    index = min(st.session_state.get("slot_tab_index", 0), len(labels) - 1)
    for i, tab in enumerate(st.tabs(labels, key="slot_tabs", default=labels[index],
                                    on_change=on_slot_tab_change)):
        with tab:
            slot_editor(i, dex, usage, picks)
