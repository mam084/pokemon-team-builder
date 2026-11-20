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
PREFS_KEY = "ptb_prefs_v1"          # small flags, e.g. the Start here card hidden


class TeamStore(Protocol):
    ready: bool                              # False until the saved list has been read

    def teams(self) -> dict[str, dict]: ...  # name -> {"team": token, "f": format id, "saved": "YYYY-MM-DD"}

    def put(self, name: str, token: str, fmt_id: str) -> None: ...

    def pref(self, name: str, default=None): ...             # small per-visitor flags

    def set_pref(self, name: str, value) -> None: ...

    def delete(self, name: str) -> None: ...


# --------------------------------------------------------------------------
# Browser storage
# --------------------------------------------------------------------------
_JS = """
export default function(component) {
    const { data, setStateValue } = component;
    const KEYS = %s;
    // write what Python sent, once per write id
    if (data && data.write_id && data.write_id !== window.__ptbWriteId) {
        window.__ptbWriteId = data.write_id;
        for (const [k, v] of Object.entries(data.writes || {})) {
            if (KEYS.includes(k)) { try { localStorage.setItem(k, v); } catch (e) {} }
        }
    }
    // read the browser's copy once per page load
    if (!window.__ptbRead) {
        window.__ptbRead = true;
        const out = {};
        for (const k of KEYS) { try { out[k] = localStorage.getItem(k) || ""; } catch (e) { out[k] = ""; } }
        setStateValue("stored", JSON.stringify(out));
    }
}
""" % json.dumps([STORAGE_KEY, PREFS_KEY])

_LIST, _WRITE, _PREFS = "my_teams", "my_teams_write", "my_prefs"


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


def _clean_prefs(raw) -> dict:
    """Flags only: short string keys with true/false values."""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}
    return {k[:40]: v for k, v in data.items() if isinstance(k, str) and isinstance(v, bool)} \
        if isinstance(data, dict) else {}


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
        self._send()

    def _send(self) -> None:
        """Queue both values, in full, for the component to write (two changes in one run can't clash)."""
        n = (self._ss.get(_WRITE) or {}).get("write_id", 0) + 1
        self._ss[_WRITE] = {"write_id": n, "writes": {STORAGE_KEY: json.dumps(self.teams()),
                                                      PREFS_KEY: json.dumps(self._ss.get(_PREFS) or {})}}

    def pref(self, name: str, default=None):
        return (self._ss.get(_PREFS) or {}).get(name, default)

    def set_pref(self, name: str, value) -> None:
        prefs = dict(self._ss.get(_PREFS) or {})
        prefs[name] = value
        self._ss[_PREFS] = prefs
        self._send()

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
            try:
                stored = json.loads(result.stored)
            except (TypeError, ValueError):
                stored = {}
            stored = stored if isinstance(stored, dict) else {}
            self._ss[_LIST] = _clean(stored.get(STORAGE_KEY))
            self._ss[_PREFS] = _clean_prefs(stored.get(PREFS_KEY))


def store() -> TeamStore:
    return BrowserStore()


__all__ = ["TeamStore", "BrowserStore", "store", "MAX_TEAMS", "NAME_MAX", "STORAGE_KEY", "PREFS_KEY"]
