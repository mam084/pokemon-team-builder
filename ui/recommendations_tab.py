"""Recommendations tab: ranked suggestions as cards, each with an Add to team button."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.builder import build_teams
from src.dex import to_id
from src.matchup import verdict
from src.recommend import DEFAULT_WEIGHTS, EXPLORE_WEIGHTS, MODES, recommend
from src.roles import meta_roles, role_text, set_roles
from ui.common import SLOTS, sprite, type_badges
from ui.matchups_tab import archetypes_for
from ui.state import add_to_team, load_team
from ui.theme import how_it_works

HELP = {
    "synergy": "Average over your whole team of how much more often it appears next to each member "
               "than chance (Smogon teammate lift). Already adjusted for popularity. 0.33 = no relationship.",
    "defense": "Resists the types your team is weak to (and doesn't share its weaknesses).",
    "offense": "Hits popular Pokémon your team can't hit super effectively.",
    "roles": "Commonly brings a role you're missing (Fake Out, speed control…).",
    "meta": "Overall usage - proven Pokémon tend to be good.",
    "plan": "Plays into your team's weather, Trick Room, Tailwind or terrain (with diminishing returns), "
            "or sets one up that your team already benefits from.",
}
MODE_HELP = {
    "popular": "Data-tuned on real tournament teams. Leans on proven meta Pokémon.",
    "neutral": "Popularity counts for nothing and every Pokémon with ladder data is considered. "
               "Leans on synergy, type fit and your team's game plan (weather, Trick Room...).",
    "hidden": "Like Neutral, and the most-used Pokémon are marked down, to surface less common picks.",
}


def mode_picker() -> str:
    """Shared by recommendations, the team builder and swap suggestions."""
    if st.session_state.get("rec_mode") not in MODES:
        st.session_state["rec_mode"] = "neutral"
    mode = st.radio("Recommendation style", list(MODES), format_func=MODES.get, key="rec_mode",
                    horizontal=True)
    st.caption(MODE_HELP[mode])
    return mode


def weights_for(mode: str) -> dict:
    defaults = DEFAULT_WEIGHTS if mode == "popular" else EXPLORE_WEIGHTS
    title = ("Adjust weights (defaults tuned on real tournament teams)" if mode == "popular"
             else "Adjust weights (exploration defaults)")
    with st.expander(title):
        cols = st.columns(3)
        weights = {
            key: cols[i % 3].slider(SIGNALS[key], 0.0, 1.0, float(defaults[key]), 0.05, help=HELP[key],
                                    key=f"w_{mode}_{key}", disabled=(key == "meta" and mode != "popular"))
            for i, key in enumerate(DEFAULT_WEIGHTS)
        }
    return weights


def team_builder_section(team, dex, usage, fmt, mode, weights) -> None:
    with st.expander("Build a whole team around one Pokémon", expanded=not team):
        if usage is None:
            st.info("Needs usage stats for this format.")
            return
        sheet = usage.team_sheet_usage(dex)
        names = list(sheet)
        default = team[0].species if team and team[0].species in names else names[0]
        core_name = st.selectbox("Build around", names, index=names.index(default), key="build_core",
                                 format_func=lambda n: f"{n}  ·  {sheet[n]:.1f}%")
        mine = next((p for p in team if to_id(p.species) == to_id(core_name)), None)
        use_mine = st.checkbox(f"Use my {core_name} set", value=mine is not None, disabled=mine is None,
                               key="build_use_mine")
        st.caption("Three different teams. Each is filled one Pokémon at a time with the top "
                   "recommendation (in the style picked above), then rated against the meta teams on the "
                   "Matchups tab. Loading a team replaces your current one.")
        if st.button(f"Build teams around {core_name}", type="primary", width="stretch"):
            core = mine if (use_mine and mine) else core_name
            with st.spinner("Building teams…"):
                st.session_state["built_teams"] = build_teams(
                    core, dex, usage, doubles=fmt.is_doubles, mode=mode, weights=weights,
                    archetypes=archetypes_for(fmt.id))
            st.session_state["built_for"] = (core_name, mode)
        built = st.session_state.get("built_teams") or []
        if built:
            core_label, built_mode = st.session_state.get("built_for", ("", ""))
            st.markdown(f"**Teams around {core_label}** ({MODES.get(built_mode, built_mode)} style)")
        for n, t in enumerate(built):
            with st.container(border=True):
                score = t.meta_score or 0.0
                theme = f" · {t.theme} team" if t.theme else ""
                st.markdown(f"**Team {n + 1}**{theme} · vs meta {score:+.2f} ({verdict(score)})")
                cards = []
                for p in t.sets:
                    form = p.battle_form(dex)
                    cards.append(f"<b>{p.species}</b> @ {p.item or 'no item'}<br>{type_badges(form.types)}"
                                 f"<br><span style='font-size:.8rem;opacity:.7'>"
                                 f"{role_text(set_roles(p, dex, fmt.is_doubles), 2)}</span>")
                st.markdown("<div style='display:flex;flex-wrap:wrap;gap:10px 18px'>" +
                            "".join(f"<div style='min-width:130px'>{c}</div>" for c in cards) + "</div>",
                            unsafe_allow_html=True)
                with st.expander("Why each Pokémon"):
                    for r in t.reasons:
                        st.markdown(f"- {r}")
                st.button("Load this team", key=f"load_built_{n}", width="stretch",
                          on_click=load_team, args=(t.sets,))

def recommendations_tab(team, members, dex, usage, fmt) -> None:
    mode = mode_picker()
    weights = weights_for(mode)
    team_builder_section(team, dex, usage, fmt, mode, weights)

    st.subheader("Next Pokémon for your team")
    if len(team) >= SLOTS:
        st.info("Your team is full - remove a member (Team tab) to add one of these, or see "
                "**Suggested swaps** on the Matchups tab.")
    how_it_works("Every candidate is scored on six signals (0–1 each) and ranked by the weighted blend: synergy, "
                 "defense, offense, roles, meta and game plan (hover the weight sliders for each). **Synergy** is "
                 "judged against your whole team: the average of how much more often the candidate appears next "
                 "to each of your Pokémon than chance predicts.", "How picks are scored")
    if mode == "popular":
        accuracy_note(fmt)
    recs = recommend(members, dex, usage, doubles=fmt.is_doubles,
                     weights=weights, top_n=15, mode=mode)
    if recs.empty:
        st.info("No candidates.")
        return
    if recs.attrs.get("glue"):
        weak = ", ".join(t.title() for t in recs.attrs.get("weak_types", []))
        st.info(f"Your **{recs.attrs['glue']}** core is in place, so picks now favor covering its weak spots "
                f"({weak}) over adding more of the same.")
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
                st.caption(drivers(row, recs.attrs.get("weights", weights)))
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
            recs.drop(columns=["form", "starts", "extra_mega"], errors="ignore"), hide_index=True, width="stretch",
            column_config={
                "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%.0f"),
                **{c: st.column_config.NumberColumn(c, format="%.2f", width="small")
                   for c in ["synergy", "defense", "offense", "roles", "meta", "plan"]},
                "why": st.column_config.TextColumn(width="large"),
            },
        )


SIGNALS = {"synergy": "Synergy", "defense": "Defense", "offense": "Offense", "roles": "Roles",
           "meta": "Popularity", "plan": "Game plan"}


def drivers(row, weights: dict) -> str:
    """Which signals the score came from, as shares: 'Ranked on: Synergy 48%, Defense 30%...'"""
    parts = {k: weights.get(k, 0) * float(row[k]) for k in SIGNALS}
    total = sum(parts.values())
    if total <= 0:
        return ""
    top = [(k, v / total) for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v / total >= 0.08]
    return "Ranked on: " + ", ".join(f"{SIGNALS[k]} {share:.0%}" for k, share in top)


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
