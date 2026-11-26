"""Team tab: the six-slot set editor and the team strip shown above the tabs."""

from __future__ import annotations


import streamlit as st

from src.dex import STAT_LABELS, STATS, Dex, to_id
from src.presets import presets_for
from src.roles import role_text, set_roles, species_roles

from src.usage import UsageData
from ui.common import NONE, SLOTS, nature_label, ranked_options, sprite, type_badges
from ui.state import (apply_preset, apply_spread, current_team, fill_slot, k, on_slot_tab_change, on_species_change, read_slot,
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
    def reason(row) -> str:
        parts = row.get("parts") or {}
        return parts.get("fit") or parts.get("plan") or parts.get("cover") or row["why"].split(";")[0]
    return [(row["pokemon"], reason(row)) for _, row in recs.head(QUICK).iterrows()]


def empty_slot(slot: int, dex: Dex, usage: UsageData | None, picks: list[tuple[str, str]]) -> None:
    team = current_team()
    if not team:  # the ways to start come first; single Pokémon to add come after
        c = st.columns(2)
        c[0].button("Load the example team", width="stretch", type="primary",
                    on_click=load_example, args=(dex,), key=k(slot, "example"))
        with c[1].popover("Paste a team", width="stretch"):
            text = st.text_area("Showdown paste", height=180, key=k(slot, "paste"),
                                placeholder="Paste a Showdown team here…", label_visibility="collapsed")
            st.button("Import", width="stretch", disabled=not text.strip(), key=k(slot, "paste_go"),
                      on_click=import_paste, args=(dex, k(slot, "paste")))
        if slot == 0:  # the builder, the app's main job, right on the empty screen
            from src.formats import FORMATS
            from ui.recommendations_tab import team_builder_section, weights_for
            mode = st.session_state.get("rec_mode", "neutral")
            fmt = FORMATS[st.session_state["format"]]
            team_builder_section(team, dex, usage, fmt, mode, weights_for(mode))
        else:
            st.caption("Or build a whole team around one Pokémon on the Recommendations tab.")
    if picks:
        st.markdown("<div class='box-title'>" + ("Or start from a popular Pokémon" if not team else
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


SPREADS = {  # 66 points each; "atk" is whichever attacking stat the moves use
    "Fast attacker": {"atk": 32, "spe": 32, "hp": 2},
    "Bulky attacker": {"hp": 32, "atk": 32, "spd": 2},
    "Physically bulky": {"hp": 32, "def": 32, "spd": 2},
    "Specially bulky": {"hp": 32, "spd": 32, "def": 2},
    "Clear": {},
}


def attack_stat(pset, form, dex: Dex) -> str:
    """'atk' or 'spa': the stat most of the set's attacks use (base stats break a tie)."""
    phys = spec = 0
    for m in pset.moves:
        mv = dex.moves.get(to_id(m))
        if mv and (mv.get("offensiveStat") or mv.get("usesTargetAttack")):
            continue  # Body Press, Foul Play: not the user's attacking stat
        if mv and mv["category"] == "Physical":
            phys += 1
        elif mv and mv["category"] == "Special":
            spec += 1
    if phys != spec:
        return "atk" if phys > spec else "spa"
    return "atk" if form.base_stats["atk"] >= form.base_stats["spa"] else "spa"



def load_spread(slot: int, atk: str) -> None:
    """Callback: a quick spread fills the Stat Points at once; the pills then reset."""
    key = k(slot, "spread")
    name = st.session_state.get(key)
    if name in SPREADS:
        apply_spread(slot, {(atk if stat == "atk" else stat): v for stat, v in SPREADS[name].items()})
    st.session_state[key] = None


def meta_check(pset, dex: Dex, usage: UsageData | None, doubles: bool) -> tuple[list[str], list[str]]:
    """This set against the 30 most used Pokémon (their popular sets): who hits it hardest
    (50%+ a hit) and who it handles (hits them for 50%+ while taking under 50%)."""
    if usage is None:
        return [], []
    from src.analysis import build_members
    from src.matchup import best_attack, opponent_members
    mine = build_members([pset], dex)
    if not mine:
        return [], []
    me = mine[0]
    threats, handles = [], []
    for name, pct in usage.ranked(30):
        opp = opponent_members([name], usage, dex)
        if not opp or opp[0].form.name == me.form.name:
            continue
        o = opp[0]
        dealt, dealt_move = best_attack(o, me, doubles)
        taken, taken_move = best_attack(me, o, doubles)
        if dealt >= 50:
            threats.append((dealt, f"{o.label} ({dealt_move} ~{min(dealt, 999):.0f}%)"))
        elif taken >= 50:
            handles.append((pct, f"{o.label} ({taken_move} ~{taken:.0f}%)"))
    threats.sort(reverse=True)
    handles.sort(reverse=True)
    return [t for _, t in threats[:3]], [h for _, h in handles[:3]]


TUNE_POOL = 30  # benchmarks come from the most used Pokémon's popular sets


@st.cache_data(show_spinner=False, ttl=3600)
def _benchmarks(fmt_key: str, set_json: str) -> tuple[list, list]:
    """(speed options, attack options) for the tuner: the top Pokémon's Speed, and each one's
    strongest move against this set."""
    import json
    from src.analysis import build_members
    from src.formats import FORMATS
    from src.matchup import best_attack, opponent_members
    from src.dex import load_dex
    from src.team import PokemonSet
    from src.usage import load_usage
    fmt = FORMATS[fmt_key]
    dex = load_dex(fmt.regulation)
    usage = load_usage(fmt_key)
    pset = PokemonSet(**json.loads(set_json))
    me = build_members([pset], dex)
    speeds, attacks = [], []
    for name, _ in usage.ranked(TUNE_POOL):
        opp = opponent_members([name], usage, dex)
        if not opp or opp[0].pset is None:
            continue
        o = opp[0]
        speeds.append((o.label, o.stats["spe"]))
        if me:
            pct, move = best_attack(o, me[0], fmt.is_doubles)
            if move:
                attacks.append((o.label, move, round(pct)))
    speeds.sort(key=lambda x: -x[1])
    attacks.sort(key=lambda x: -x[2])
    return speeds, attacks


def tuner_section(slot: int, pset, dex: Dex, usage: UsageData | None, fmt_key: str, doubles: bool) -> None:
    """Pick a Speed to beat and hits to survive; get the fewest points that do it."""
    import json
    from dataclasses import asdict
    from src.spread import Benchmark, tune
    if usage is None:
        return
    with st.expander("Spread tuner: outspeed and survive specific threats"):
        speeds, attacks = _benchmarks(fmt_key, json.dumps(asdict(pset), sort_keys=True))
        sp_opts = [None] + [f"{n} ({v})" for n, v in speeds]
        target = st.selectbox("Outspeed", sp_opts, key=k(slot, "tune_spe"),
                              format_func=lambda x: "Don't care" if x is None else x,
                              help="The most used Pokémon, with the Speed of their most popular set.")
        atk_opts = {f"{n}: {m} ({p}% now)": (n, m) for n, m, p in attacks}
        hits = st.multiselect("Survive", list(atk_opts), key=k(slot, "tune_hits"), max_selections=3,
                              placeholder="Pick up to 3 attacks",
                              help="Each one's strongest move against this set, as it is now. Checked at the "
                                   "highest damage roll, no crit or boosts.")
        rest = st.segmented_control("Leftover points", ["Attack", "Bulk"], default="Attack",
                                    key=k(slot, "tune_rest"))
        if target is None and not hits:
            st.caption(f"Keeps the {pset.nature or 'current'} nature; pick a benchmark to see a spread.")
            return
        bench = []
        for h in hits:
            name, move = atk_opts[h]
            opp = usage.popular_set(name, dex)
            if opp is not None:
                bench.append(Benchmark(opp, move))
        speed_target = dict(speeds).get(target.rsplit(" (", 1)[0]) if target else None
        result = tune(pset, dex, speed_target, bench, doubles, "bulk" if rest == "Bulk" else "attack")
        if result.sps is None:
            st.warning(f"Not possible: {result.problem}.")
            return
        spread = " / ".join(f"{v} {STAT_LABELS[s]}" for s, v in result.sps.items() if v)
        st.markdown(f"**{spread}**  \n" + "  \n".join(f"- {n}" for n in result.notes))
        st.button("Use this spread", key=k(slot, "tune_apply"), type="primary",
                  on_click=apply_spread, args=(slot, result.sps))


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
    item_now = ss.get(k(slot, "item"), NONE)
    others = [read_slot(j) for j in range(SLOTS) if j != slot]
    if item_now != NONE and any(p and p.item == item_now for p in others):
        c[0].caption(f":orange[Another Pokémon already holds {item_now} (one of each item).]")
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
        chosen = [ss.get(k(slot, f"move{i}")) for i in range(4)]
        dupes = sorted({m for m in chosen if m != NONE and chosen.count(m) > 1})
        if dupes:
            st.caption(f":orange[{', '.join(dupes)} is picked twice.]")
        elif NONE in chosen:
            st.caption(f"{chosen.count(NONE)} move slot{'s' if chosen.count(NONE) > 1 else ''} empty.")

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
        atk = attack_stat(pset, form, dex)
        st.pills("Quick spread", list(SPREADS), key=k(slot, "spread"), label_visibility="collapsed",
                 on_change=load_spread, args=(slot, atk),
                 help=f"Fill the points in one tap (attackers use {STAT_LABELS[atk]}, from the moves).")
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

    from src.formats import DEFAULT_FORMAT
    tuner_section(slot, pset, dex, usage, ss.get("format", DEFAULT_FORMAT), doubles)
    threats, handles = meta_check(pset, dex, usage, doubles)
    if threats or handles:
        with st.container(border=True, key=f"meta_box{slot}"):
            st.markdown("<div class='box-title'>Against the top 30 <span class='box-sub'>popular sets, "
                        "damage calcs</span></div>", unsafe_allow_html=True)
            st.markdown(f"**Watch out for:** {', '.join(threats) or 'nothing hits it for half its HP'}  \n"
                        f"**Good into:** {', '.join(handles) or 'none it clearly beats'}")
            st.caption("Watch out for: their best hit on it, as % of its HP. "
                       "Good into: it hits them for half or more and takes less than half back.")
    bottom = st.columns([3, 1], vertical_alignment="bottom")
    nick = ss.get(k(slot, "nick"), "")
    with bottom[0].popover(f"Nickname: {nick}" if nick else "Add a nickname"):
        st.text_input("Nickname", key=k(slot, "nick"), max_chars=12)
    bottom[1].button("Remove", key=k(slot, "rm"), on_click=write_slot, args=(slot, None), width="stretch")


def default_name(team) -> str:
    return " + ".join(p.species for p in team[:2]) + (" + …" if len(team) > 2 else "")


def save_mine(token: str, fmt_id: str, fallback: str) -> None:
    from ui.team_store import NAME_MAX, store
    name = ((st.session_state.get("my_team_name") or "").strip() or fallback)[:NAME_MAX]
    if name and token:
        store().put(name, token, fmt_id)
        st.session_state["my_team_pick"] = name
        st.session_state["my_team_name"] = ""
        st.toast(f"Saved \u201c{name}\u201d on this device.")


def load_mine(dex_for) -> None:
    from src.formats import FORMATS
    from ui.state import load_team
    from src.share import decode_team
    from ui.team_store import store
    name = st.session_state.get("my_team_pick")
    entry = store().teams().get(name)
    if not entry:
        return
    if entry["f"] in FORMATS:
        st.session_state["format"] = entry["f"]
    team, warnings = decode_team(entry["team"], dex_for(st.session_state.get("format")))
    if team:
        load_team(team)
        st.session_state["url_notice"] = f"Loaded \u201c{name}\u201d."
    st.session_state["import_warnings"] = warnings


def delete_mine() -> None:
    from ui.team_store import store
    name = st.session_state.get("my_team_pick")
    if name:
        store().delete(name)
        st.session_state.pop("my_team_pick", None)


def my_teams_section(team, fmt_id: str) -> None:
    """Named teams kept in this browser (ui/team_store.py)."""
    from src.dex import load_dex
    from src.formats import FORMATS
    from src.share import encode_team
    from ui.team_store import MAX_TEAMS, NAME_MAX, store
    s = store()
    saved = s.teams()
    with st.expander(f"My teams ({len(saved)})" if saved else "My teams"):
        if not s.ready:
            st.caption("Reading the teams saved in this browser…")
            return
        if saved:
            def label(n):
                e = saved[n]
                other = f" · {FORMATS[e['f']].label}" if e["f"] != fmt_id and e["f"] in FORMATS else ""
                return f"{n}{other}"
            if st.session_state.get("my_team_pick") not in saved:
                st.session_state["my_team_pick"] = next(iter(saved))
            st.selectbox("Saved team", list(saved), key="my_team_pick", format_func=label)
            b = st.container(key="button_row_myteams").columns(2)
            b[0].button("Load", key="my_team_load", width="stretch", type="primary",
                        on_click=load_mine, args=(lambda f: load_dex(FORMATS[f].regulation),),
                        help="Replaces the team you're editing.")
            b[1].button("Delete", key="my_team_delete", width="stretch", on_click=delete_mine)
        if team:
            st.text_input("Save the current team as", key="my_team_name", max_chars=NAME_MAX,
                          placeholder=default_name(team))
            st.button("Save team", key="my_team_save", width="stretch",
                      on_click=save_mine, args=(encode_team(team), fmt_id, default_name(team)),
                      help="Leave the name blank to use the one shown. Saving under an existing name replaces it.")
        st.caption(f"Kept in this browser on this device (up to {MAX_TEAMS}); nothing is sent anywhere. "
                   "To move a team to another device, open the share link there.")


def team_tab(dex: Dex, usage: UsageData | None) -> None:
    # The selected slot must survive reruns: a key keeps it when a warning box appears
    # above the tabs, and the remembered index re-selects it when its label changes
    # (Streamlit treats tabs with new labels as new tabs).
    from src.formats import DEFAULT_FORMAT
    my_teams_section(current_team(), st.session_state.get("format", DEFAULT_FORMAT))
    labels = slot_labels()
    picks = quick_picks(dex, usage) if any(lb.startswith("Slot ") for lb in labels) else []
    index = min(st.session_state.get("slot_tab_index", 0), len(labels) - 1)
    for i, tab in enumerate(st.tabs(labels, key="slot_tabs", default=labels[index],
                                    on_change=on_slot_tab_change)):
        with tab:
            slot_editor(i, dex, usage, picks)
