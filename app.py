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

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Champions Team Builder", layout="wide")

from src.analysis import build_members  # noqa: E402
from src.formats import FORMATS  # noqa: E402
from src.legality import check_team  # noqa: E402
from ui.analysis_tab import analysis_tab  # noqa: E402
from ui.damage_tab import damage_tab  # noqa: E402
from ui.matchups_tab import battle_plan_tab, matchups_tab  # noqa: E402
from ui.playbook_tab import playbook_tab  # noqa: E402
from ui.pokemon_tab import pokemon_tab  # noqa: E402
from ui.recommendations_tab import recommendations_tab  # noqa: E402
from ui.sidebar import notices, sidebar  # noqa: E402
from ui.state import current_team, keep_state  # noqa: E402
from ui.team_tab import team_tab  # noqa: E402
from ui.theme import inject_css, status_html, team_stage, title_row  # noqa: E402
from ui.url_state import restore_from_url, sync_url  # noqa: E402


def legality(team, dex, fmt) -> None:
    """Status on the team stage; the details only when there is something to read."""
    issues = check_team(team, dex) if team else []
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    team_stage(dex, status_html(len(errors), len(warnings), len(team), fmt.label))
    if errors or warnings:
        label = "Rule problems to fix" if errors else "Notes on your team"
        with st.expander(label, expanded=bool(errors)):
            for issue in errors:
                st.error(issue.message)
            for issue in warnings:
                st.warning(issue.message)


DATA_DIRS = ["data/usage", "data/evaluation", "data/tournaments", "data/dex", "data/replays/summary"]


@st.cache_resource(show_spinner=False)
def _data_seen() -> dict:
    return {"stamp": None}


def reload_if_data_changed() -> None:
    """New data reaches the app by git push (daily replays and synergy model, monthly ladder
    stats); Community Cloud copies the files but the app keeps what it loaded in memory. When
    any data file changed since the last page load, drop every cache so the next load reads
    the new files - no reboot needed."""
    root = Path(__file__).resolve().parent
    stamp = tuple(sorted((str(p), p.stat().st_mtime) for d in DATA_DIRS if (root / d).exists()
                         for p in (root / d).glob("*.json")))
    seen = _data_seen()
    if seen["stamp"] is not None and stamp != seen["stamp"]:
        from src import matchup, recommend
        from src.dex import load_dex
        from src.usage import load_usage
        load_usage.cache_clear()
        load_dex.cache_clear()
        matchup._CALC_CACHE.clear()
        recommend._PROFILE_CACHE.clear()
        from ui.common import _sprites_available
        _sprites_available.cache_clear()
        st.cache_data.clear()
        st.cache_resource.clear()
        seen = _data_seen()
    seen["stamp"] = stamp


def main() -> None:
    reload_if_data_changed()
    keep_state()        # only the open tab is built: keep the team when another tab is open
    restore_from_url()  # a team in the link loads before any widget renders
    fmt_id, dex, usage = sidebar()
    fmt = FORMATS[fmt_id]
    st.session_state["doubles"] = fmt.is_doubles
    team = current_team()
    members = build_members(team, dex)

    inject_css()
    if usage is not None and usage.recent:
        r = usage.recent
        from src.replays import day_range
        title_row(fmt.label + f", meta from ladder replays {day_range(r['first_day'], r['last_day'])}")
    else:
        month = usage.info["month"] if usage else None
        title_row(fmt.label + (f", ladder data from {month}" if month else ""))
    legality(team, dex, fmt)
    notices()

    tabs = st.tabs(["Team", "Analysis", "Matchups", "Battle plan", "Playbook", "Damage calc", "Recommendations", "Pokémon"], key="main_tabs", on_change="rerun")
    # Only the open tab is built: each edit used to recompute every tab, swaps included (~4 s).
    pages = [lambda: team_tab(dex, usage),
             lambda: analysis_tab(team, members, dex, usage, fmt),
             lambda: matchups_tab(fmt_id, team, members, dex, usage, fmt),
             lambda: battle_plan_tab(fmt_id, team, members, dex, usage, fmt),
             lambda: playbook_tab(team, dex, usage, fmt),
             lambda: damage_tab(team, dex, usage, fmt),
             lambda: recommendations_tab(team, members, dex, usage, fmt),
             lambda: pokemon_tab(dex, usage, len(team), fmt)]
    for tab, page in zip(tabs, pages):
        if tab.open:
            with tab:
                page()

    # Keep the address bar in step with the team (read again: tab buttons may have changed it).
    sync_url(current_team(), fmt_id)


main()
