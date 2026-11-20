"""
start_here.py - the first thing a new visitor sees: what the app does that others don't, and three steps.

Shown while the team is empty, until the visitor hides it (remembered in their browser, ui/team_store.py).
Also: the feedback link at the bottom of every page.
"""

from __future__ import annotations

import streamlit as st

from ui.team_store import store

HIDDEN = "start_here_hidden"
FEEDBACK_URL = "https://github.com/mam084/pokemon-team-builder/issues/new?template=feedback.yml"

PITCH = ("A team builder for Pokémon Champions VGC that learns from real results: win chances from "
         "tournament matches, plays measured against players who didn't make them, and game plans from the "
         "team you're facing.")
STEPS = [
    ("Make a team", "Load the example, paste yours, or build three teams around one Pokémon (below)."),
    ("See how it does", "**Matchups**: your win chance against each meta team, the biggest threats, and swaps "
                        "that fix them. **Compare versions** shows what a change did."),
    ("Plan a game", "**Battle plan**: pick or paste the six you're facing for what to bring, lead and click on "
                    "turn 1. **Playbook**: what wins against Trick Room, Tailwind, weather and setup."),
]


def hide() -> None:
    store().set_pref(HIDDEN, True)


def start_here(team, dex) -> None:
    """The Start here card, while the team is empty and the visitor hasn't hidden it."""
    if team:
        return
    s = store()
    if not s.ready or s.pref(HIDDEN, False):
        return
    from ui.sidebar import load_example
    with st.container(border=True, key="start_here"):
        st.markdown(f"**Start here.** {PITCH}")
        st.markdown("\n".join(f"{i}. **{title}.** {text}" for i, (title, text) in enumerate(STEPS, 1)))
        b = st.container(key="button_row_start").columns(2)
        b[0].button("Load the example team", key="start_example", type="primary", width="stretch",
                    on_click=load_example, args=(dex,))
        b[1].button("Hide this", key="start_hide", width="stretch", on_click=hide,
                    help="It stays hidden in this browser.")


def feedback_url() -> str:
    """The GitHub issue form; a no-account form (e.g. Google Forms) can replace it in the app's secrets."""
    try:
        return st.secrets.get("feedback_url", FEEDBACK_URL)
    except Exception:   # no secrets file
        return FEEDBACK_URL


def footer() -> None:
    st.divider()
    st.caption(f"Something confusing, wrong or missing? [Send feedback]({feedback_url()}). "
               "Usage data: Smogon and Pokémon Showdown replays; tournament teams: Limitless.")


__all__ = ["start_here", "footer", "feedback_url", "HIDDEN", "PITCH"]
