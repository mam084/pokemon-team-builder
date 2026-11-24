"""Shared pieces for the Pokémon tab (ui/pokemon_tab.py): usage bars, replay and learned-effect lines,
and what wins games. The old Meta tab's leaderboard now sits at the bottom of the Pokémon tab."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import Dex, to_id
from src.match_model import load_model
from src.replays import load_summary
from ui.common import palette

def bar_section(title: str, data: dict, dex: Dex, kind: str, n: int = 8) -> None:
    if not data:
        return
    data = {k: v for k, v in data.items() if v >= 1}  # no 0% bars
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
    with st.expander("What wins games (support tools, from real tournament results)"):
        _what_wins(model, dex)


def _what_wins(model, dex) -> None:
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
    rare = [r["support tool"] for r in rows if r["clear?"] == "too rare to tell"]
    rows = sorted((r for r in rows if r["clear?"] != "too rare to tell"), key=lambda r: -r["win chance (points)"])
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"win chance (points)": st.column_config.NumberColumn(format="%+.1f")})
    st.caption("**Clear?** *yes* means the 90% range is entirely above or below zero, so the effect is very "
               "likely real; *no* means it could still be zero. " + (f"Left out as too rare to tell (one team has "
               f"it and the other doesn't in under {RARE:.0%} of matches, so treat them as no effect): "
               f"{', '.join(rare)}." if rare else ""))
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


