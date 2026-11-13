"""
The team lives in the page URL (see src/share.py), so refreshing or
bookmarking the page keeps it and the link can be shared.

restore_from_url() runs once per browser session, before any widget renders;
sync_url() runs at the end of every rerun and rewrites the address bar to
match the current team (without reloading the page).
"""

from __future__ import annotations

from urllib.parse import urlencode

import streamlit as st

from src.dex import load_dex
from src.formats import DEFAULT_FORMAT, FORMATS
from src.share import decode_team, encode_team
from src.team import PokemonSet
from ui.state import load_team

RESTORED = "_url_restored"


def restore_from_url() -> None:
    ss = st.session_state
    if ss.get(RESTORED):
        return
    ss[RESTORED] = True
    params = st.query_params
    fmt_id = params.get("f")
    ss["format"] = fmt_id if fmt_id in FORMATS else ss.get("format", DEFAULT_FORMAT)
    token = params.get("team")
    if not token:
        return
    team, warnings = decode_team(token, load_dex(FORMATS[ss["format"]].regulation))
    if team:
        load_team(team)
        ss["url_notice"] = f"Loaded a team of {len(team)} from the link."
    ss["import_warnings"] = ss.get("import_warnings", []) + warnings


def team_params(team: list[PokemonSet], fmt_id: str) -> dict:
    token = encode_team(team)
    return {"f": fmt_id, "team": token} if token else {}


def sync_url(team: list[PokemonSet], fmt_id: str) -> None:
    wanted = team_params(team, fmt_id)
    if dict(st.query_params) != wanted:
        st.query_params.from_dict(wanted)


def share_link(team: list[PokemonSet], fmt_id: str) -> str:
    base = (getattr(st.context, "url", "") or "").split("?")[0]
    params = team_params(team, fmt_id)
    return f"{base}?{urlencode(params)}" if params else base
