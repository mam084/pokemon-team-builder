"""Matchups tab: team vs rebuilt meta teams, pairing heatmaps, counters and threats."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import load_dex
from src.formats import FORMATS
from src.matchup import (best_attack, best_bring, build_archetypes, counter_picks, meta_matchups,
                         opponent_members, pair_matrix, team_score, threat_report, verdict)
from src.recommend import MODES
from src.roles import meta_roles, role_text
from src.swaps import SwapEngine, mode_pool, suggest_swaps
from src.usage import load_usage
from ui.common import matchup_scale, sprite, type_badges
from ui.state import write_slot

@st.cache_resource(show_spinner=False)
def archetypes_for(fmt_id: str):
    fmt = FORMATS[fmt_id]
    usage = load_usage(fmt_id)
    if usage is None:
        return []
    return build_archetypes(usage, load_dex(fmt.regulation), team_size=6)


def pair_scale() -> list:
    """Diverging red (their side wins) -> neutral -> blue (yours wins)."""
    scale = matchup_scale()
    weak_strong, weak_soft, mid = scale[5][1], scale[4][1], scale[3][1]
    light_r, strong = scale[2][1], scale[0][1]
    return [[0, weak_strong], [0.33, weak_soft], [0.5, mid], [0.67, light_r], [1, strong]]


def pair_heatmap(matrix: pd.DataFrame) -> go.Figure:
    z = matrix.clip(-3, 3).values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(matrix.columns), y=list(matrix.index), text=matrix.round(1).values,
        texttemplate="%{text:+.1f}", zmin=-3, zmax=3, xgap=2, ygap=2, showscale=False,
        colorscale=pair_scale(),
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
    doubles = fmt.is_doubles
    st.caption(
        "Common meta teams are rebuilt from Smogon teammate data: start from a popular Pokémon and keep adding "
        "whoever is most often paired with the whole team so far. Each opponent uses its most popular set. "
        "Every pairing is decided by **real damage calcs both ways**: a pair scores +1 when your Pokémon needs "
        "half as many hits to KO theirs as they need to KO yours, ±0.5 for Speed (reversed under Trick Room). "
        "Weather teams are scored in their weather. Team score = how well you answer them minus how well they "
        "answer you, so 0 is even."
    )
    if not members:
        st.info("Add Pokémon on the **Team** tab to see how you match up. The meta teams are listed below.")
    else:
        table = meta_matchups(members, archetypes, usage, dex, bring=fmt.pick, doubles=doubles)
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
            st.caption(f"{opp.pset.item or 'No item'} · " + role_text(meta_roles(arch.members[i], usage, dex, doubles), 2))
    notes = []
    if arch.trick_room:
        notes.append("This team sets Trick Room, so slower Pokémon get the Speed bonus.")
    if arch.weather:
        notes.append(f"Calcs are done in {arch.weather}, which this team sets.")
    if notes:
        st.caption(" ".join(notes))

    if members:
        matrix = pair_matrix(members, theirs, arch.trick_room, doubles, arch.weather)
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
                mine = next(m for m in members if m.label == best)
                pct, move = best_attack(mine, opp, doubles, arch.weather)
                answers.append({
                    "their Pokémon": opp.label,
                    "your best answer": best if col.max() >= 0.5 else "—",
                    "key calc": f"{move} {pct:.0f}%" if col.max() >= 0.5 and move else "—",
                })
            st.dataframe(pd.DataFrame(answers), hide_index=True, width="stretch")

    st.markdown(f"**Counter picks for {pick}**: meta Pokémon (popular sets) with the best average pairing "
                "against this team" + (", not counting your current team." if team else "."))
    counters = counter_picks(theirs, usage, dex, exclude={p.species for p in team},
                             trick_room=arch.trick_room, doubles=doubles, weather=arch.weather)
    if not counters.empty:
        counters.insert(1, "usually plays", [role_text(meta_roles(n, usage, dex, doubles), 2)
                                             for n in counters["pokemon"]])
        st.dataframe(counters, hide_index=True, width="stretch",
                     column_config={"avg matchup": st.column_config.NumberColumn(format="%+.2f")})

    threats = threats_section(members, dex, usage, doubles)
    swaps_section(team, dex, usage, fmt, threats)


def threats_section(members, dex, usage, doubles: bool) -> pd.DataFrame:
    st.subheader("Biggest threats to your team")
    if not members:
        st.info("Add Pokémon on the **Team** tab to see which popular Pokémon threaten you.")
        return pd.DataFrame()
    st.caption("The 30 most-used Pokémon (popular sets), ranked by **usage × (your Pokémon it 2HKOs + 1) ÷ "
               "(answers + 1)**. An *answer* 2HKOs it back while taking under 50%. **Meta counters** are the "
               "Pokémon with the best pairing against it, if you want to add one.")
    threats = threat_report(members, usage, dex, n=30, doubles=doubles)
    if threats.empty:
        return threats
    threats["meta counters"] = [
        ", ".join(counter_picks(opponent_members([name], usage, dex), usage, dex, pool=50, top_n=3,
                                doubles=doubles)["pokemon"])
        if i < 10 else "—"
        for i, name in enumerate(threats["pokemon"])
    ]
    cols = st.columns(3)
    for i, row in threats.head(3).iterrows():
        with cols[i]:
            with st.container(border=True):
                form = dex.get_species(row["pokemon"])
                if form:
                    st.image(sprite(form, dex), width=64)
                st.markdown(f"**{row['pokemon']}** · {row['usage %']:.1f}% usage")
                st.caption(f"2HKOs {row['2HKOs']} of your team. Hardest hits: {row['hardest hits']}. "
                           f"Your answers: {row['answers']}.")
    st.dataframe(threats, hide_index=True, width="stretch",
                 column_config={"threat score": st.column_config.ProgressColumn(
                     "threat score", min_value=0, max_value=float(threats["threat score"].max() or 1),
                     format="%.1f")})
    return threats


@st.cache_resource(show_spinner=False)
def swap_engine_for(fmt_id: str) -> SwapEngine:
    fmt = FORMATS[fmt_id]
    return SwapEngine(archetypes_for(fmt_id), load_usage(fmt_id), load_dex(fmt.regulation), fmt.is_doubles)


def swaps_section(team, dex, usage, fmt, threats: pd.DataFrame) -> None:
    st.subheader("Suggested swaps")
    if len(team) < 2:
        st.info("Swaps need at least two Pokémon on your team.")
        return
    mode = st.session_state.get("rec_mode", "popular")
    st.caption(
        "Replace one member with a Pokémon that fixes a problem without hurting the overall matchup. "
        f"Candidates follow the **{MODES[mode]}** style set on the Recommendations tab. Each swap is "
        "scored with the same damage calcs as above, using the newcomer's popular set (keeping Item "
        "Clause and one Mega)."
    )
    threat_names = list(threats["pokemon"].head(10)) if not threats.empty else []
    others = [n for n, _ in usage.ranked(60) if n not in threat_names]
    options = ["Best overall vs the meta"] + threat_names + others
    focus = st.selectbox("Fix", options, key="swap_focus",
                         format_func=lambda o: o if o == options[0] else
                         (f"{o} (threat #{threat_names.index(o) + 1})" if o in threat_names else o))
    focus_name = None if focus == options[0] else focus
    with st.spinner("Trying swaps…"):
        swaps = suggest_swaps(team, dex, usage, swap_engine_for(fmt.id), focus=focus_name,
                              pool=mode_pool(usage, mode), top_n=8)
    if swaps.empty:
        st.success("No single swap improves this without hurting the overall matchup. Your team already "
                   "handles it about as well as one change can." if focus_name else
                   "No single swap improves the overall matchup.")
        return
    base = swaps.attrs.get("base_overall", 0.0)
    st.caption(f"Your team now: {base:+.2f} vs the meta ({verdict(base)}).")
    for i, row in swaps.iterrows():
        with st.container(border=True):
            cols = st.columns([5, 2])
            gain = f" · vs {focus_name} {row['vs threat']:+.1f}" if focus_name else ""
            cols[0].markdown(
                f"**{row['swap out']} → {row['swap in']}** · overall {row['overall']:+.2f} "
                f"({row['overall change']:+.2f}){gain}"
            )
            detail = row["set"] + (f"  \n{row['key calc']}" if row["key calc"] else "")
            cols[0].caption(detail)
            cols[1].button("Apply swap", key=f"swap_{i}_{row['swap in']}", width="stretch",
                           on_click=write_slot, args=(int(row["slot"]), row["_set"]))
