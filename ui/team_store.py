"""
team_store.py - "My teams": named teams a visitor keeps.

Where they're kept sits behind one small interface (TeamStore), so the app never touches storage directly.
Today there's one backend, BrowserStore: the visitor's own browser (localStorage), so there's no sign-up and
nothing is stored on a server; the list is per browser and device, and the share link moves a team between
devices. Accounts can come later as a second backend (a database keyed by the signed-in user) without
changing the Team tab.

BrowserStore keeps the list in session state for the session. A tiny built-in Streamlit component
(st.components.v2, no extra package) reads the browser's copy once when the page opens and writes the
list back after each change. Entries hold the team as its share-link token (src/share.py), so loading one
goes through the same checks as a pasted team.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Protocol

import streamlit as st

MAX_TEAMS = 50
NAME_MAX = 40
STORAGE_KEY = "ptb_my_teams_v1"     # localStorage key; bump the version if the entry format changes


class TeamStore(Protocol):
    ready: bool                              # False until the saved list has been read

    def teams(self) -> dict[str, dict]: ...  # name -> {"team": token, "f": format id, "saved": "YYYY-MM-DD"}

    def put(self, name: str, token: str, fmt_id: str) -> None: ...

    def delete(self, name: str) -> None: ...


# --------------------------------------------------------------------------
# Browser storage
# --------------------------------------------------------------------------
_JS = """
export default function(component) {
    const { data, setStateValue } = component;
    const KEY = "%s";
    // write the list Python sent, once per write id
    if (data && data.write_id && data.write_id !== window.__ptbTeamsWriteId) {
        window.__ptbTeamsWriteId = data.write_id;
        try { localStorage.setItem(KEY, data.write); } catch (e) {}
    }
    // read the browser's copy once per page load
    if (!window.__ptbTeamsRead) {
        window.__ptbTeamsRead = true;
        let stored = "";
        try { stored = localStorage.getItem(KEY) || ""; } catch (e) {}
        setStateValue("stored", stored || "{}");
    }
}
""" % STORAGE_KEY

_LIST, _WRITE = "my_teams", "my_teams_write"


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("ptb_team_store", js=_JS)


def _clean(raw) -> dict[str, dict]:
    """The browser's copy, keeping only well-formed entries (it's user-side data)."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for name, e in list(data.items())[:MAX_TEAMS]:
        if isinstance(name, str) and isinstance(e, dict) and isinstance(e.get("team"), str) \
                and isinstance(e.get("f"), str):
            out[name[:NAME_MAX]] = {"team": e["team"], "f": e["f"], "saved": str(e.get("saved", ""))[:10]}
    return out


class BrowserStore:
    def __init__(self) -> None:
        self._ss = st.session_state

    @property
    def ready(self) -> bool:
        return self._ss.get(_LIST) is not None

    def teams(self) -> dict[str, dict]:
        return dict(self._ss.get(_LIST) or {})

    def _write(self, teams: dict[str, dict]) -> None:
        self._ss[_LIST] = teams
        n = (self._ss.get(_WRITE) or {}).get("write_id", 0) + 1
        self._ss[_WRITE] = {"write_id": n, "write": json.dumps(teams)}

    def put(self, name: str, token: str, fmt_id: str) -> None:
        teams = self.teams()
        teams.pop(name, None)                      # re-saving moves it to the top
        teams = {name: {"team": token, "f": fmt_id, "saved": date.today().isoformat()}, **teams}
        self._write(dict(list(teams.items())[:MAX_TEAMS]))

    def delete(self, name: str) -> None:
        teams = self.teams()
        if teams.pop(name, None) is not None:
            self._write(teams)

    def sync(self) -> None:
        """Mount the component (every run, hidden): it reads the browser's copy on page load and writes
        the list after each change."""
        with st.container(key="ptb_store_box"):
            result = _component()(key="ptb_store", data=self._ss.get(_WRITE) or {},
                                  on_stored_change=lambda: None)
        if self._ss.get(_LIST) is None and result is not None and getattr(result, "stored", None) is not None:
            self._ss[_LIST] = _clean(result.stored)


def store() -> TeamStore:
    return BrowserStore()


__all__ = ["TeamStore", "BrowserStore", "store", "MAX_TEAMS", "NAME_MAX"]
