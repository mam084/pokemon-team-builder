"""
app.py - Pokemon Champions Team Builder

Build a full Champions team (items, abilities, natures, Stat Points, moves),
check it against the regulation's rules, and analyze it against the live meta:
type matchups, role coverage, speed tiers, threats, and explainable
recommendations for what to add next.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import (build_members, coverage_vs_meta, defense_matrix, defense_summary,
                          offense_by_type, role_checklist, speed_table, threat_report)
from src.dex import STAT_LABELS, STATS, Dex, load_dex, to_id
from src.formats import DEFAULT_FORMAT, FORMATS
from src.legality import check_team
from src.matchup import (best_bring, build_archetypes, counter_picks, meta_matchups, opponent_members,
                         pair_matrix, pair_score, team_score, verdict)
from src.presets import presets_for
from src.roles import meta_roles, role_text, set_roles, species_roles
from src.paste import export_paste, parse_paste
from src.recommend import DEFAULT_WEIGHTS, recommend
from src.stats import format_sps
from src.team import PokemonSet, default_set
from src.usage import UsageData, load_usage

st.set_page_config(page_title="Champions Team Builder", page_icon="🏆", layout="wide")

NONE = "—"
SLOTS = 6

# Palette (dataviz reference instance): diverging blue <-> red with a gray
# midpoint for matchups, series blue for "your team", muted gray for context.
BLUE, RED, GRAY_MID, MUTED, INK = "#2a78d6", "#e34948", "#f0efec", "#898781", "#52514e"
MATCHUP_SCALE = [  # value = log2(multiplier), clipped to [-2, 2]; immunity drawn at -2.5
    [0.0, "#104281"], [0.11, "#256abf"], [0.33, "#86b6ef"], [0.56, GRAY_MID],
    [0.78, "#f2a3a2"], [1.0, "#b8282a"],
]
TYPE_COLORS = {
    "Normal": "#9fa19f", "Fire": "#e62829", "Water": "#2980ef", "Electric": "#fac000",
    "Grass": "#3fa129", "Ice": "#3dcef3", "Fighting": "#ff8000", "Poison": "#9141cb",
    "Ground": "#915121", "Flying": "#81b9ef", "Psychic": "#ef4179", "Bug": "#91a119",
    "Rock": "#afa981", "Ghost": "#704170", "Dragon": "#5060e1", "Dark": "#624d4e",
    "Steel": "#60a1b8", "Fairy": "#ef70ef",
}

SAMPLE_TEAM = """Garganacl @ Leftovers
Ability: Purifying Salt
EVs: 32 HP / 2 Def / 32 SpD
Careful Nature
- Salt Cure
- Body Press
- Iron Defense
- Wide Guard

Garchomp @ Garchompite Z
Ability: Rough Skin
EVs: 2 HP / 32 SpA / 32 Spe
Timid Nature
- Draco Meteor
- Earth Power
- Flamethrower
- Protect

Rillaboom @ Miracle Seed
Ability: Grassy Surge
EVs: 32 HP / 32 Atk / 2 SpD
Adamant Nature
- Fake Out
- Grassy Glide
- Wood Hammer
- U-turn

Sinistcha @ Mental Herb
Ability: Hospitality
EVs: 32 HP / 32 Def / 2 SpD
Bold Nature
- Matcha Gotcha
- Rage Powder
- Strength Sap
- Protect

Incineroar @ Sitrus Berry
Ability: Intimidate
EVs: 32 HP / 2 Atk / 32 SpD
Careful Nature
- Fake Out
- Flare Blitz
- Parting Shot
- Throat Chop

Gholdengo @ Life Orb
Ability: Good as Gold
EVs: 2 HP / 32 SpA / 32 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Nasty Plot
- Protect
"""


# ==========================================================================
# State: the team lives in session_state["team"] as a list of dicts (or None
# for an empty slot). Widgets use keys "s{slot}_{field}"; `write_slot` pushes a
# set into those keys and `read_slot` pulls the widgets back into a set.
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


# ==========================================================================
# Small view helpers
# ==========================================================================
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


def ranked_options(all_names: list[str], popular: dict, dex_lookup) -> list[str]:
    """Popular choices first (in usage order), then everything else alphabetically."""
    lookup = {to_id(n): n for n in all_names}
    first = [lookup[to_id(p)] for p in popular if to_id(p) in lookup]
    rest = [n for n in all_names if n not in set(first)]
    return first + rest


# ==========================================================================
# Sidebar
# ==========================================================================
def sidebar() -> tuple[str, Dex, UsageData | None]:
    with st.sidebar:
        st.header("🏆 Champions Team Builder")
        fmt_id = st.selectbox(
            "Format", list(FORMATS), index=list(FORMATS).index(DEFAULT_FORMAT),
            format_func=lambda f: FORMATS[f].label,
        )
        fmt = FORMATS[fmt_id]
        dex = load_dex(fmt.regulation)
        usage = load_usage(fmt_id)
        st.caption(f"{fmt.active} · bring 6, pick {fmt.pick} · Level 50 · 66 Stat Points")
        if usage:
            info = usage.info
            st.caption(f"Usage: Smogon {info['month']}, {info['battles']:,} battles rated {info['cutoff']}+")
        else:
            st.caption("No usage stats for this format yet - recommendations use type and role fit only.")
        st.toggle("Auto-fill popular sets", value=True, key="autofill",
                  help="When you pick a Pokémon, fill in its most-used item, ability, spread and moves.")

        st.divider()
        st.subheader("Import / export")
        paste = st.text_area("Showdown paste", height=150, placeholder="Paste a team here…",
                             label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("Import", width="stretch", disabled=not paste.strip()):
            team, warnings = parse_paste(paste, dex)
            load_team(team)
            st.session_state["import_warnings"] = warnings
            st.rerun()
        if c2.button("Example team", width="stretch",
                     help="A Garganacl team for VGC Reg M-C"):
            team, _ = parse_paste(SAMPLE_TEAM, dex)
            load_team(team)
            st.rerun()
        for w in st.session_state.pop("import_warnings", []):
            st.warning(w)

        team = current_team()
        if team:
            text = export_paste(team)
            with st.expander("Export paste"):
                st.code(text, language=None)
            st.download_button("Download .txt", text, file_name="champions-team.txt", width="stretch")
        if st.button("Clear team", width="stretch", type="secondary"):
            load_team([])
            st.rerun()
        st.caption(f"Legality data: Pokémon Showdown ({dex.format_name}), exported {dex.generated_at}.")
    return fmt_id, dex, usage


# ==========================================================================
# Team tab
# ==========================================================================
def slot_editor(slot: int, dex: Dex, usage: UsageData | None) -> None:
    ss = st.session_state
    species_names = [s.name for s in dex.selectable_species()]
    sheet_usage = usage.team_sheet_usage(dex) if usage else {}
    species_opts = [NONE] + ranked_options(species_names, sheet_usage, None)
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
        top[0].markdown("<div style='font-size:3rem;text-align:center;opacity:.3'>＋</div>", unsafe_allow_html=True)
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
    items = [NONE] + ranked_options(dex.legal_items(base.name), item_pct, None)
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
    move_opts = [NONE] + ranked_options(dex.learnable_moves(base.name), move_pct, None)

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
    cols = st.columns(SLOTS)
    for i in range(SLOTS):
        with cols[i]:
            if i < len(team):
                form = team[i].battle_form(dex)
                st.image(sprite(form, dex), width=72)
                st.markdown(f"**{team[i].nickname or team[i].species}**<br>{type_badges(form.types)}",
                            unsafe_allow_html=True)
                st.caption(role_text(set_roles(team[i], dex, st.session_state.get("doubles", True)), 2))
            else:
                st.markdown("<div style='height:72px;opacity:.25;font-size:2.5rem'>○</div>", unsafe_allow_html=True)


def team_tab(dex: Dex, usage: UsageData | None) -> None:
    labels = []
    for i in range(SLOTS):
        sp = st.session_state.get(k(i, "species"), NONE)
        labels.append(f"{i + 1}. {sp}" if sp != NONE else f"{i + 1}. empty")
    for i, tab in enumerate(st.tabs(labels)):
        with tab:
            slot_editor(i, dex, usage)


# ==========================================================================
# Analysis tab
# ==========================================================================
def matchup_heatmap(matrix: pd.DataFrame) -> go.Figure:
    import numpy as np
    z = np.where(matrix.values == 0, -2.5, np.log2(matrix.values.clip(min=0.25)))
    text = matrix.map(fmt_mult).values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(matrix.columns), y=list(matrix.index), text=text, texttemplate="%{text}",
        zmin=-2.5, zmax=2, colorscale=MATCHUP_SCALE, showscale=False, xgap=2, ygap=2,
        customdata=matrix.values,
        hovertemplate="%{y} → %{x}: %{customdata}× damage<extra></extra>",
    ))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    return fig


def speed_chart(df: pd.DataFrame, trick_room: bool) -> go.Figure:
    df = df.sort_values("speed", ascending=trick_room).reset_index(drop=True)
    colors = [BLUE if w == "Your team" else "#c3c2b7" for w in df["who"]]
    fig = go.Figure(go.Bar(
        x=df["speed"], y=df["pokemon"], orientation="h", marker_color=colors,
        text=df["speed"], textposition="outside", cliponaxis=False,
        customdata=df[["who", "note"]], hovertemplate="%{y}: %{x} Speed<br>%{customdata[0]} %{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(height=max(320, 24 * len(df)), margin=dict(l=10, r=40, t=10, b=10),
                      yaxis=dict(autorange="reversed"), xaxis_title="Speed at level 50", bargap=0.25)
    return fig


def analysis_tab(team, members, dex, usage, fmt) -> None:
    if not members:
        st.info("Add Pokémon on the **Team** tab to see the analysis.")
        return

    st.subheader("Defensive matchups")
    st.caption("Damage each attacking type deals to each member, with Mega forms and type-changing abilities "
               "(Levitate, Purifying Salt, Thick Fat…) applied. Red = weak, blue = resists.")
    matrix = defense_matrix(members)
    left, right = st.columns([3, 2])
    left.plotly_chart(matchup_heatmap(matrix), width="stretch")
    summary = defense_summary(matrix)
    flagged = summary[summary["verdict"] != ""]
    with right:
        if flagged.empty:
            st.success("No shared weaknesses - every type is answered by at least one resist.")
        else:
            st.markdown("**Types to watch**")
            st.dataframe(flagged, width="stretch")
        st.markdown("**Role checklist**")
        st.dataframe(role_checklist(members, fmt.is_doubles), hide_index=True, width="stretch",
                     column_config={"why it matters": st.column_config.TextColumn(width="medium")})

    st.subheader("Speed tiers")
    tr = st.toggle("Trick Room order (slowest first)", value=False)
    st.caption("Your team's real Speed stats next to the meta's most common spreads."
               + ("" if usage else " Add usage data to see meta benchmarks."))
    st.plotly_chart(speed_chart(speed_table(members, dex, usage, n=20), tr), width="stretch")

    st.subheader("Offensive coverage")
    c1, c2 = st.columns([2, 3])
    with c1:
        off = offense_by_type(members)
        st.caption("Best effectiveness your damaging moves get against each type.")
        st.dataframe(off.assign(best=off["best"].map(lambda x: fmt_mult(x) or "1×")),
                     width="stretch", height=420)
    with c2:
        if usage:
            st.caption("…and against the 30 most-used Pokémon, in their common battle form.")
            cov = coverage_vs_meta(members, dex, usage, n=30)
            cov["best hit"] = cov["best hit"].map(lambda x: fmt_mult(x) or "1×")
            st.dataframe(cov, hide_index=True, width="stretch", height=420)
        else:
            st.info("Coverage against the meta needs usage stats for this format.")

    st.subheader("Stats")
    rows = [{"Pokémon": m.label, **{STAT_LABELS[s]: m.stats[s] for s in STATS}} for m in members]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ==========================================================================
# Recommendations / Threats / Meta tabs
# ==========================================================================
def recommendations_tab(team, members, dex, usage, fmt) -> None:
    if len(team) >= SLOTS:
        st.info("Your team is full - remove a member to get suggestions for that slot.")
    st.caption("Every legal Pokémon is scored on five signals (0–1 each) and ranked by the weighted blend. "
               "The **why** column shows what drove each pick.")
    with st.expander("Adjust weights"):
        cols = st.columns(5)
        help_text = {
            "synergy": "Appears with your current members more often than chance (Smogon teammate lift).",
            "defense": "Resists the types your team is weak to.",
            "offense": "Hits popular Pokémon your team can't hit super effectively.",
            "roles": "Commonly brings a role you're missing (Fake Out, speed control…).",
            "meta": "Overall usage - proven Pokémon tend to be good.",
        }
        weights = {key: cols[i].slider(key.title(), 0.0, 1.0, DEFAULT_WEIGHTS[key], 0.05, help=help_text[key])
                   for i, key in enumerate(DEFAULT_WEIGHTS)}
    recs = recommend(members, dex, usage, doubles=fmt.is_doubles,
                     weights=weights, top_n=15)
    if recs.empty:
        st.info("No candidates.")
        return
    if usage:
        recs.insert(2, "usually plays", [role_text(meta_roles(n, usage, dex, fmt.is_doubles), 2)
                                          for n in recs["pokemon"]])
    st.dataframe(
        recs.drop(columns=["form"]), hide_index=True, width="stretch",
        column_config={
            "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%.0f"),
            **{c: st.column_config.NumberColumn(c, format="%.2f", width="small")
               for c in ["synergy", "defense", "offense", "roles", "meta"]},
            "why": st.column_config.TextColumn(width="large"),
        },
    )
    if len(team) < SLOTS:
        st.markdown("**Add a suggestion**")
        cols = st.columns(5)
        for i, name in enumerate(recs["pokemon"].head(5)):
            cols[i].button(f"＋ {name}", key=f"rec_add_{name}", width="stretch",
                           on_click=add_to_team, args=(name, dex, usage))


@st.cache_resource(show_spinner=False)
def archetypes_for(fmt_id: str):
    fmt = FORMATS[fmt_id]
    usage = load_usage(fmt_id)
    if usage is None:
        return []
    return build_archetypes(usage, load_dex(fmt.regulation), team_size=6)


def pair_heatmap(matrix: pd.DataFrame) -> go.Figure:
    z = matrix.clip(-3, 3).values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(matrix.columns), y=list(matrix.index), text=matrix.round(1).values,
        texttemplate="%{text:+.1f}", zmin=-3, zmax=3, xgap=2, ygap=2, showscale=False,
        colorscale=[[0, "#b8282a"], [0.33, "#f2a3a2"], [0.5, GRAY_MID], [0.67, "#86b6ef"], [1, "#104281"]],
        hovertemplate="%{y} vs %{x}: %{z:+.1f}<extra></extra>",
    ))
    fig.update_layout(height=80 + 46 * len(matrix.index), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    return fig


def matchups_tab(fmt_id, team, members, dex, usage, fmt) -> None:
    if usage is None:
        st.info("Matchups need usage stats for this format.")
        return
    archetypes = archetypes_for(fmt_id)
    st.caption(
        "Common meta teams are rebuilt from Smogon teammate data: start from a popular Pokémon and keep adding "
        "whoever is most often paired with the whole team so far. Each opponent uses its most popular set. "
        "A pair scores **+1 per type-effectiveness step you hit harder than you get hit, ±0.5 for Speed** "
        "(reversed under Trick Room). Team score = how well you answer them minus how well they answer you, "
        "so 0 is even."
    )
    if not members:
        st.info("Add Pokémon on the **Team** tab to see how you match up. The meta teams are listed below.")
    else:
        table = meta_matchups(members, archetypes, usage, dex, bring=fmt.pick)
        weights = table["popularity"]
        overall = float((table["score"] * weights).sum() / weights.sum()) if len(table) else 0.0
        c = st.columns(4)
        c[0].metric("Overall vs meta", f"{overall:+.2f} · {verdict(overall)}",
                    help="Usage-weighted average of the team scores below")
        c[1].metric("Favorable", int((table["score"] >= 0.25).sum()))
        c[2].metric("Even", int(((table["score"] > -0.25) & (table["score"] < 0.25)).sum()))
        c[3].metric("Unfavorable", int((table["score"] <= -0.25).sum()))
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "popularity": st.column_config.NumberColumn("avg usage %", format="%.1f"),
                "score": st.column_config.NumberColumn("score", format="%+.2f"),
                "with bring": st.column_config.NumberColumn(f"score with bring {fmt.pick}", format="%+.2f"),
            },
        )

    st.subheader("Matchup detail")
    names = [a.name for a in archetypes]
    if not names:
        st.info("Not enough usage data to build meta teams.")
        return
    pick = st.selectbox("Meta team", names)
    arch = archetypes[names.index(pick)]
    theirs = opponent_members(arch.members, usage, dex)
    cols = st.columns(len(theirs))
    for i, opp in enumerate(theirs):
        with cols[i]:
            st.image(sprite(opp.form, dex), width=64)
            st.markdown(f"**{opp.label}**<br>{type_badges(opp.form.types)}", unsafe_allow_html=True)
            st.caption(role_text(meta_roles(arch.members[i], usage, dex, fmt.is_doubles), 2))
    if arch.trick_room:
        st.caption("This team sets Trick Room, so slower Pokémon get the Speed bonus.")

    if members:
        matrix = pair_matrix(members, theirs, arch.trick_room)
        score = team_score(matrix)
        picks, picked = best_bring(matrix, fmt.pick)
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Your team vs {pick}: {score:+.2f} ({verdict(score)})**")
            st.plotly_chart(pair_heatmap(matrix), width="stretch")
            st.caption("Blue = your Pokémon (row) wins that pairing, red = theirs (column) does.")
        with right:
            st.markdown(f"**Suggested bring {fmt.pick}:** {', '.join(picks)} ({picked:+.2f})")
            answers = []
            for opp in theirs:
                col = matrix[opp.label]
                best = col.idxmax()
                answers.append({"their Pokémon": opp.label, "your best answer": best if col.max() >= 0.5 else "—",
                                "pairing": round(float(col.max()), 1)})
            st.dataframe(pd.DataFrame(answers), hide_index=True, width="stretch",
                         column_config={"pairing": st.column_config.NumberColumn(format="%+.1f")})

    st.markdown(f"**Counter picks for {pick}** — meta Pokémon (popular sets) with the best average pairing "
                "against this team" + (", not counting your current team." if team else "."))
    counters = counter_picks(theirs, usage, dex, exclude={p.species for p in team},
                             trick_room=arch.trick_room)
    if not counters.empty:
        counters.insert(1, "usually plays", [role_text(meta_roles(n, usage, dex, fmt.is_doubles), 2)
                                             for n in counters["pokemon"]])
        st.dataframe(counters, hide_index=True, width="stretch",
                     column_config={"avg matchup": st.column_config.NumberColumn(format="%+.2f")})

    st.subheader("Counters to the meta's top Pokémon")
    st.caption("For each of the 12 most-used Pokémon: who on your team wins the pairing, and which meta "
               "Pokémon beat it most convincingly.")
    rows = []
    for name, pct in usage.ranked(12):
        opp = opponent_members([name], usage, dex)
        if not opp:
            continue
        mine = sorted(((pair_score(m, opp[0]), m.label) for m in members), reverse=True)
        yours = ", ".join(f"{lbl} ({sc:+.1f})" for sc, lbl in mine if sc >= 1) or "—"
        meta_c = counter_picks(opp, usage, dex, pool=50, top_n=3)
        rows.append({
            "Pokémon": name, "usage %": pct,
            "usually plays": role_text(meta_roles(name, usage, dex, fmt.is_doubles), 2),
            "your answers": yours,
            "meta counters": ", ".join(meta_c["pokemon"]) if not meta_c.empty else "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def threats_tab(members, dex, usage) -> None:
    if usage is None:
        st.info("Threat analysis needs usage stats for this format.")
        return
    if not members:
        st.info("Add Pokémon on the **Team** tab first.")
        return
    st.caption("Popular Pokémon ranked by **usage × (members they hit super effectively + 1) ÷ (answers + 1)**. "
               "An *answer* takes neutral or less from everything the threat commonly attacks with "
               "and hits it super effectively back.")
    threats = threat_report(members, dex, usage, n=40)
    top = threats.head(3)
    cols = st.columns(3)
    for i, row in top.iterrows():
        with cols[i]:
            with st.container(border=True):
                form = dex.get_species(row["pokemon"])
                if form:
                    st.image(sprite(form, dex), width=72)
                st.markdown(f"**{row['pokemon']}** · {row['usage %']:.1f}% usage")
                st.caption(f"Attacks with {row['attacks with']}. Hits {row['hits SE']} of your team "
                           f"super effectively; answers: {row['answers']}.")
    st.dataframe(threats, hide_index=True, width="stretch",
                 column_config={"threat score": st.column_config.ProgressColumn(
                     "threat score", min_value=0, max_value=float(threats["threat score"].max() or 1),
                     format="%.1f")})


def bar_section(title: str, data: dict, dex: Dex, kind: str, n: int = 8) -> None:
    if not data:
        return
    names = []
    for key in list(data)[:n]:
        entry = {"items": dex.items, "moves": dex.moves, "abilities": dex.abilities}.get(kind, {}).get(to_id(key))
        names.append(entry["name"] if entry else key)
    values = list(data.values())[:n]
    fig = go.Figure(go.Bar(x=values, y=names, orientation="h", marker_color=BLUE,
                           text=[f"{v:.0f}%" for v in values], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=60 + 26 * len(values),
                      margin=dict(l=10, r=40, t=30, b=10), yaxis=dict(autorange="reversed"),
                      xaxis=dict(visible=False, range=[0, max(values) * 1.25]), bargap=0.3)
    st.plotly_chart(fig, width="stretch")


def meta_tab(dex: Dex, usage: UsageData | None, team_size: int) -> None:
    if usage is None:
        st.info("No usage stats for this format yet. Run `python scripts/fetch_usage.py` "
                "or wait for the monthly data refresh.")
        return
    info = usage.info
    st.caption(f"Smogon ladder stats for {info['month']}: {info['battles']:,} battles, players rated {info['cutoff']}+.")
    left, right = st.columns([2, 3])
    with left:
        board = pd.DataFrame(usage.ranked(60), columns=["Pokémon", "usage %"])
        board.index += 1
        st.dataframe(board, width="stretch", height=640,
                     column_config={"usage %": st.column_config.ProgressColumn(
                         "usage %", min_value=0, max_value=float(board["usage %"].max()), format="%.1f%%")})
    with right:
        name = st.selectbox("Pokémon", [n for n, _ in usage.ranked()])
        species = dex.get_species(name)
        head = st.columns([1, 4])
        if species:
            head[0].image(sprite(species, dex), width=80)
            head[1].markdown(f"### {name}\n{type_badges(species.types)} · {usage.usage(name):.1f}% usage",
                             unsafe_allow_html=True)
            st.markdown("**Usually plays:** " + role_text(meta_roles(name, usage, dex, st.session_state.get("doubles", True)), 6, True))
            if team_size < SLOTS:
                head[1].button(f"＋ Add {name} with its popular set", on_click=add_to_team,
                               args=(name, dex, usage))
        presets = [p for p in presets_for(name, usage, dex) if p.source == name] or presets_for(name, usage, dex)
        if presets:
            st.markdown("**Presets** (assembled from the most common items, moves and spreads)")
            pcols = st.columns(min(3, len(presets)))
            for i, preset in enumerate(presets[:3]):
                with pcols[i]:
                    with st.container(border=True):
                        st.markdown(f"**{preset.name}** · ~{preset.weight:.0f}% of sets")
                        st.caption(f"{preset.pset.ability} · {format_sps(preset.pset.sps) or 'no Stat Points'}")
                        st.markdown("\n".join(f"- {m}" for m in preset.pset.moves))
                        with st.expander("Showdown paste"):
                            st.code(export_paste([preset.pset]), language=None, wrap_lines=True)
                        if team_size < SLOTS:
                            st.button("＋ Add to team", key=f"meta_preset_{name}_{i}", width="stretch",
                                      on_click=add_set_to_team, args=(preset.pset,))
        c1, c2 = st.columns(2)
        with c1:
            bar_section("Moves", usage.section(name, "moves"), dex, "moves", 10)
            bar_section("Abilities", usage.section(name, "abilities"), dex, "abilities", 4)
        with c2:
            bar_section("Items", usage.section(name, "items"), dex, "items", 8)
            bar_section("Teammates", usage.section(name, "teammates"), dex, "teammates", 8)
        spreads = usage.section(name, "spreads")
        if spreads:
            st.markdown("**Common spreads** (nature: HP/Atk/Def/SpA/SpD/Spe Stat Points)")
            st.dataframe(pd.DataFrame(list(spreads.items())[:6], columns=["spread", "% of sets"]),
                         hide_index=True, width="stretch")
        counters = usage.section(name, "counters")
        if counters:
            st.markdown("**Checks & counters** (how often each KOs or forces it out)")
            st.dataframe(pd.DataFrame(list(counters.items()), columns=["Pokémon", "% KO / switch"]),
                         hide_index=True, width="stretch")


# ==========================================================================
# Main
# ==========================================================================
def main() -> None:
    fmt_id, dex, usage = sidebar()
    fmt = FORMATS[fmt_id]
    st.session_state["doubles"] = fmt.is_doubles
    team = current_team()
    members = build_members(team, dex)

    st.title("Pokémon Champions Team Builder")
    team_strip(team, dex)

    issues = check_team(team, dex) if team else []
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if team:
        if errors:
            label = f"❌ {len(errors)} legality problem(s)"
        elif len(team) == SLOTS:
            label = "✅ Legal for " + fmt.label
        else:
            label = f"🛠️ {len(team)}/6 - no rule violations so far"
        with st.expander(label + (f" · {len(warnings)} note(s)" if warnings else ""), expanded=bool(errors)):
            for i in errors:
                st.error(i.message)
            for i in warnings:
                st.warning(i.message)

    tabs = st.tabs(["🧩 Team", "🛡️ Analysis", "⚔️ Matchups", "✨ Recommendations", "⚠️ Threats", "📊 Meta"])
    with tabs[0]:
        team_tab(dex, usage)
    with tabs[1]:
        analysis_tab(team, members, dex, usage, fmt)
    with tabs[2]:
        matchups_tab(fmt_id, team, members, dex, usage, fmt)
    with tabs[3]:
        recommendations_tab(team, members, dex, usage, fmt)
    with tabs[4]:
        threats_tab(members, dex, usage)
    with tabs[5]:
        meta_tab(dex, usage, len(team))


main()
