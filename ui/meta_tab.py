"""Meta tab: usage leaderboard and per-Pokemon detail (roles, presets, moves, items...)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import Dex, to_id
from src.paste import export_paste
from src.presets import presets_for
from src.roles import meta_roles, role_text
from src.stats import format_sps
from src.usage import UsageData
from ui.common import SLOTS, palette, sprite, type_badges
from ui.state import add_set_to_team, add_to_team

def bar_section(title: str, data: dict, dex: Dex, kind: str, n: int = 8) -> None:
    if not data:
        return
    names = []
    for key in list(data)[:n]:
        entry = {"items": dex.items, "moves": dex.moves, "abilities": dex.abilities}.get(kind, {}).get(to_id(key))
        names.append(entry["name"] if entry else key)
    values = list(data.values())[:n]
    fig = go.Figure(go.Bar(x=values, y=names, orientation="h", marker_color=palette()["blue"],
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
                head[1].button(f"Add {name} with its popular set", on_click=add_to_team,
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
                            st.button("Add to team", key=f"meta_preset_{name}_{i}", width="stretch",
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
