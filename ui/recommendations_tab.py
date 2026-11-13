"""Recommendations tab: ranked suggestions as cards, each with an Add to team button."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.recommend import DEFAULT_WEIGHTS, recommend
from src.roles import meta_roles, role_text
from ui.common import SLOTS, sprite, type_badges
from ui.state import add_to_team

def recommendations_tab(team, members, dex, usage, fmt) -> None:
    if len(team) >= SLOTS:
        st.info("Your team is full - remove a member (Team tab) to add one of these.")
    st.caption("Every legal Pokémon is scored on five signals (0–1 each) and ranked by the weighted blend. "
               "**Synergy** is judged against your whole team: the average of how much more often the "
               "candidate appears next to each of your Pokémon than chance predicts.")
    accuracy_note(fmt)
    with st.expander("Adjust weights"):
        cols = st.columns(5)
        help_text = {
            "synergy": "Average over your whole team of how much more often it appears next to each member "
                       "than chance (Smogon teammate lift). 0.33 = no relationship.",
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
    full = len(team) >= SLOTS
    top = recs.head(10)
    for i, row in top.iterrows():
        if i % 2 == 0:  # a new row per pair keeps 1, 2, 3... in order when columns stack on a phone
            cols = st.columns(2)
        with cols[i % 2]:
            with st.container(border=True):
                form = dex.get_species(row["form"])
                head = st.columns([1, 4])
                if form is not None:
                    head[0].image(sprite(form, dex), width=56)
                head[1].markdown(
                    f"**{i + 1}. {row['pokemon']}** · score {row['score']:.0f}<br>"
                    f"{type_badges(row['types'].split('/'))}",
                    unsafe_allow_html=True,
                )
                if usage:
                    st.caption(f"Usually plays: {row['usually plays']}")
                st.markdown(row["why"][0].upper() + row["why"][1:])
                if row["note"]:
                    st.caption(f"Note: {row['note']}")
                st.button(
                    "Team is full" if full else f"Add {row['pokemon']} to team",
                    key=f"rec_add_{row['pokemon']}", width="stretch", disabled=full,
                    on_click=add_to_team, args=(row["pokemon"], dex, usage),
                    help="Adds its most popular set to the first empty slot",
                )
    with st.expander("Score breakdown (all signals)"):
        st.dataframe(
            recs.drop(columns=["form"]), hide_index=True, width="stretch",
            column_config={
                "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%.0f"),
                **{c: st.column_config.NumberColumn(c, format="%.2f", width="small")
                   for c in ["synergy", "defense", "offense", "roles", "meta"]},
                "why": st.column_config.TextColumn(width="large"),
            },
        )


EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"


def accuracy_note(fmt) -> None:
    """Show how the recommender scored against real tournament teams, if an evaluation exists."""
    path = EVAL_DIR / f"{fmt.regulation}.json"
    if not fmt.is_doubles or not path.exists():
        return
    report = json.loads(path.read_text())
    tuned = report["results"].get("tuned weights", {})
    with st.expander(f"How accurate is this? Top-10 hit rate {tuned.get('hit@10', 0):.0%} on real tournament teams"):
        st.caption(
            f"Tested on {report['test_teams']:,} teams from {report['test_tournaments']} Limitless tournaments "
            f"({report['test_dates'][0]} to {report['test_dates'][1]}): hide one member of a real team, give the "
            "other five to the recommender, and see where the hidden Pokémon ranks among about "
            f"{report['candidate_pool']} candidates. Weights were tuned on {report['train_teams']:,} older teams "
            "only, so these numbers are a forward-in-time test."
        )
        rows = [{"model": name, "top 1": m["hit@1"], "top 5": m["hit@5"], "top 10": m["hit@10"], "MRR": m["mrr"]}
                for name, m in report["results"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="percent" if c != "MRR" else "%.3f")
                                    for c in ["top 1", "top 5", "top 10", "MRR"]})
