"""
app.py - Pokemon Champions Team Builder

Build a full Champions team (items, abilities, natures, Stat Points, moves),
check it against the regulation's rules, and analyze it against the live meta:
type matchups, roles, speed tiers, damage calcs, team-vs-meta matchups,
threats, and explainable recommendations for what to add next.

This file only lays out the page; each tab lives in ui/, and all the logic
lives in src/.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Champions Team Builder", layout="wide")

from src.analysis import build_members  # noqa: E402
from src.formats import FORMATS  # noqa: E402
from src.legality import check_team  # noqa: E402
from ui.analysis_tab import analysis_tab  # noqa: E402
from ui.common import SLOTS  # noqa: E402
from ui.damage_tab import damage_tab  # noqa: E402
from ui.matchups_tab import matchups_tab  # noqa: E402
from ui.meta_tab import meta_tab  # noqa: E402
from ui.recommendations_tab import recommendations_tab  # noqa: E402
from ui.sidebar import sidebar  # noqa: E402
from ui.state import current_team  # noqa: E402
from ui.team_tab import team_strip, team_tab  # noqa: E402
from ui.url_state import restore_from_url, sync_url  # noqa: E402


def legality_banner(team, dex, fmt) -> None:
    if not team:
        return
    issues = check_team(team, dex)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if errors:
        label = f"{len(errors)} legality problem(s)"
    elif len(team) == SLOTS:
        label = "Legal for " + fmt.label
    else:
        label = f"{len(team)}/6 Pokémon - no rule violations so far"
    with st.expander(label + (f" · {len(warnings)} note(s)" if warnings else ""), expanded=bool(errors)):
        for issue in errors:
            st.error(issue.message)
        for issue in warnings:
            st.warning(issue.message)


def main() -> None:
    restore_from_url()  # a team in the link loads before any widget renders
    fmt_id, dex, usage = sidebar()
    fmt = FORMATS[fmt_id]
    st.session_state["doubles"] = fmt.is_doubles
    team = current_team()
    members = build_members(team, dex)

    st.header("Pokémon Champions Team Builder")
    team_strip(team, dex)
    legality_banner(team, dex, fmt)

    tabs = st.tabs(["Team", "Analysis", "Matchups", "Damage calc", "Recommendations", "Meta"])
    with tabs[0]:
        team_tab(dex, usage)
    with tabs[1]:
        analysis_tab(team, members, dex, usage, fmt)
    with tabs[2]:
        matchups_tab(fmt_id, team, members, dex, usage, fmt)
    with tabs[3]:
        damage_tab(team, dex, usage, fmt)
    with tabs[4]:
        recommendations_tab(team, members, dex, usage, fmt)
    with tabs[5]:
        meta_tab(dex, usage, len(team))

    # Keep the address bar in step with the team (read again: tab buttons may have changed it).
    sync_url(current_team(), fmt_id)


main()
