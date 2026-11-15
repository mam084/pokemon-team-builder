"""Meta tab: usage leaderboard and per-Pokemon detail (roles, presets, moves, items...)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import Dex, to_id
from src.match_model import load_model
from src.replays import load_summary
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


@st.cache_data(show_spinner=False)
def _model(regulation: str) -> dict | None:
    return load_model(regulation)


def _effect_text(e: dict) -> str:
    lo, hi = 25 * e["lo90"], 25 * e["hi90"]
    if lo > 0 or hi < 0:
        return f"**{e['points']:+.1f}** win-chance points (90% range {lo:+.1f} to {hi:+.1f})"
    return (f"{e['points']:+.1f} win-chance points, not clearly different from zero "
            f"(90% range {lo:+.1f} to {hi:+.1f})")


def species_effect(name: str, dex: Dex, regulation: str) -> str:
    model = _model(regulation)
    species = dex.get_species(name)
    if model is None or species is None:
        return ""
    e = next((e for e in model["effects"] if e["feature"] == f"species: {dex.sheet_id(species)}"), None)
    if e is None:
        return ""
    return (f"**Real tournament results:** beyond what its calcs, Speed and support moves explain, teams with "
            f"{species.name.split('-Mega')[0]} did {_effect_text(e)}.")


RARE = 0.05  # a tool that differs between the two teams in under 5% of matches is too rare to judge


@st.cache_data(show_spinner=False, ttl=3600)
def _summary(format_id: str) -> dict | None:
    return load_summary(format_id)


def replay_line(name: str, dex: Dex, format_id: str) -> str:
    """'In 12,000 ladder replays: brought 64% of the time it's on team preview, ...'"""
    summary = _summary(format_id) if format_id else None
    species = dex.get_species(name)
    if not summary or species is None:
        return ""
    base = species.battle_only[0] if species.battle_only else (
        species.base_species if species.is_mega else species.name)
    row = summary["pokemon"].get(to_id(base))
    if row is None:
        return ""
    win = row.get("win % when brought")
    parts = [f"brought **{row['brought %']:.0%}** of the time it's on team preview",
             f"leads **{row['leads %']:.0%}**"]
    if win is not None:
        parts.append(f"wins **{win:.0%}** of games it's brought to")
    if row.get("mega %"):
        parts.append(f"Mega Evolves in {row['mega %']:.0%} of them")
    text = f"**In {summary['games']:,} Showdown replays** ({summary['from']} to {summary['to']}): " + ", ".join(parts) + "."
    if row.get("turn 1"):
        text += f"  \nTurn 1: {row['turn 1']}."
    return text


def what_wins_section(regulation: str, dex: Dex) -> None:
    model = _model(regulation)
    if model is None:
        return
    st.subheader("What wins games")
    skill = "skill (Elo)" in model["model"]["features"]
    st.caption(f"Learned from {model['matches']:,} real Limitless matches with both team lists. Each number is "
               "the change in win chance (percentage points, near a 50/50 match) for one more Pokémon with that "
               "tool than the opponent, with everything else held equal"
               + (", **including both players' skill ratings**, so a tool doesn't get credit just because strong "
                  "players use it. They're still patterns in real results, not proof of cause."
                  if skill else ". These are patterns in real results, not proof of cause: a tool can look good "
                  "because strong players use it."))
    effects = {e["feature"]: e for e in model["effects"]}
    tools = sorted((e for f, e in effects.items() if f.startswith("tool: ")), key=lambda e: -e["points"])
    def verdict(e):
        if e.get("differs_in", 1) < RARE:
            return "too rare to tell"
        return "yes" if e["lo90"] > 0 or e["hi90"] < 0 else "no"

    rows = [{"support tool": e["feature"][6:], "win chance (points)": e["points"],
             "90% range": f"{25 * e['lo90']:+.1f} to {25 * e['hi90']:+.1f}",
             "clear?": verdict(e)} for e in tools]
    rows.sort(key=lambda r: (r["clear?"] == "too rare to tell", -r["win chance (points)"]))
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"win chance (points)": st.column_config.NumberColumn(format="%+.1f")})
    species = [e for f, e in effects.items() if f.startswith("species: ") and (e["lo90"] > 0 or e["hi90"] < 0)]
    if not species and skill:
        st.caption("Per-Pokémon effects aren't in the model: once player skill is accounted for, they stopped "
                   "improving predictions. Pokémon that seemed to \"win more than their calcs\" were mostly being "
                   "used by stronger players.")
    if species:
        best = sorted(species, key=lambda e: -e["points"])[:6]
        worst = sorted(species, key=lambda e: e["points"])[:6]
        def name(sheet_id: str) -> str:
            sp = dex.get_species(sheet_id)
            return sp.name if sp else sheet_id

        def item(e) -> str:
            rare = "*" if e.get("differs_in", 1) < RARE else ""
            return f"{name(e['feature'][9:])}{rare} ({e['points']:+.1f})"

        fmt_list = lambda es: ", ".join(item(e) for e in es)  # noqa: E731
        st.markdown(f"**Pokémon that win more than their calcs say:** {fmt_list(e for e in best if e['points'] > 0)}  \n"
                    f"**...and less:** {fmt_list(e for e in worst if e['points'] < 0)}")
        st.caption("Shown only where the 90% range excludes zero. A Mega counts as its base Pokémon. "
                   "\\* on few teams (in under 5% of matches), so its number rests on a small sample.")


def meta_tab(dex: Dex, usage: UsageData | None, team_size: int, regulation: str = "", format_id: str = "") -> None:
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
            learned = species_effect(name, dex, regulation)
            if learned:
                st.caption(learned)
            replay = replay_line(name, dex, format_id)
            if replay:
                st.markdown(replay)
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
    what_wins_section(regulation, dex)
