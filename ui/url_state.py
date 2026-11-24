"""
The team lives in the page URL (see src/share.py), so refreshing or
bookmarking the page keeps it and the link can be shared. Compare's saved
version rides along as v (and its label as vl) while it differs from the team.

restore_from_url() runs once per browser session, before any widget renders;
sync_url() runs at the end of every rerun and rewrites the address bar to
match the current team (without reloading the page).
"""

from __future__ import annotations

import re
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
    dex = load_dex(FORMATS[ss["format"]].regulation)
    saved = params.get("v")
    if saved:   # Compare's saved version rides along in the link
        from ui.compare import SAVED
        from ui.matchups_tab import team_key
        old, _ = decode_team(saved, dex)
        if old:
            ss[SAVED] = {"key": team_key(old), "label": clean_label(params.get("vl"))}
    token = params.get("team")
    if not token:
        return
    team, warnings = decode_team(token, dex)
    if team:
        from src.usage_counts import count
        count("team from a link")
        load_team(team)
        ss["url_notice"] = f"Loaded a team of {len(team)} from the link."
    ss["import_warnings"] = ss.get("import_warnings", []) + warnings


LABEL_MAX = 60


def clean_label(label: str | None) -> str:
    """A label from someone else's link is shown in markdown: keep it plain text (no links, markup)."""
    label = re.sub(r"\S*(://|www\.)\S*", "", label or "")          # markdown would autolink these
    label = re.sub(r"[\[\]()<>*_`#~|\\]", "", label).strip()[:LABEL_MAX]
    return label or "saved version"


def team_params(team: list[PokemonSet], fmt_id: str) -> dict:
    """The link's parameters: format, team, and Compare's saved version (v, vl) when there is one."""
    token = encode_team(team)
    if not token:
        return {}
    params = {"f": fmt_id, "team": token}
    from ui.compare import SAVED
    saved = st.session_state.get(SAVED)
    if saved:
        from ui.matchups_tab import _unkey
        old = encode_team(_unkey(saved["key"]))
        if old and old != token:
            params.update({"v": old, "vl": saved["label"][:LABEL_MAX]})
    return params


def sync_url(team: list[PokemonSet], fmt_id: str) -> None:
    wanted = team_params(team, fmt_id)
    if dict(st.query_params) != wanted:
        st.query_params.from_dict(wanted)


def share_link(team: list[PokemonSet], fmt_id: str) -> str:
    base = (getattr(st.context, "url", "") or "").split("?")[0]
    params = team_params(team, fmt_id)
    return f"{base}?{urlencode(params)}" if params else base
