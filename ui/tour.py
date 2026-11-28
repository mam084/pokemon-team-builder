"""
tour.py - a guided tour for new visitors: it walks through building a real team and every tab, step by
step, in the app itself. Each step opens its tab; "Do it for me" buttons do the step's action (build
three teams, load one) for anyone who'd rather watch first.

Started from the Start here card or the footer; the step lives in session state (`tour_step`), so it
survives tab changes. A banner above the tabs shows the current step.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

STEP = "tour_step"


@dataclass
class Step:
    title: str
    body: str
    tab: str                 # the tab this step opens ("builder": Team if the team is empty, else Recommendations)
    needs_team: bool = False


STEPS = [
    Step("Welcome",
         "This app builds and checks teams for Pokémon Champions VGC from real results: tournament teams, "
         "rated ladder games and a win model trained on them. In two minutes you'll build a team, see how it "
         "does against the meta, and plan a game. Use **Next** to move on, or **End** any time.",
         "Team"),
    Step("1 · Build around a Pokémon you like",
         "Open **Build a whole team around one Pokémon** (below your team). Pick who to build around and a **Style**: "
         "*Popular picks* leans on proven meta Pokémon, *Off-meta* picks any Pokémon for fit, *Hidden gems* "
         "finds rare picks that win more than expected. **Must include** keeps a partner you already want; **Leave out** skips ones you don't. "
         "Then press **Build teams**, or **Build for me** here.",
         "builder"),
    Step("2 · Pick one of the three teams",
         "Each team leads with its **Team score** (how it compares with real tournament teams) and a "
         "**Game plan**: who to lead with, who cleans up, who to swap in. **Why each Pokémon** explains every "
         "pick. Press **Load this team** on the one you like, or **Load Team 1** here.",
         "builder"),
    Step("3 · Make it yours",
         "Your team is on the **Team** tab. Tap a Pokémon to change its moves, item, ability or Stat Points; "
         "the meta's common sets are one tap away. **My teams** saves it in this browser, and the address "
         "bar is a share link.",
         "Team", needs_team=True),
    Step("4 · Why it rates the way it does",
         "**Analysis** starts with what the win model sees: what costs your team points against the meta and "
         "what would help, what it does well, and its toughest meta teams. Below: shared weaknesses, roles, "
         "Speed tiers and type coverage.",
         "Analysis", needs_team=True),
    Step("5 · How it does against the meta",
         "**Matchups** shows your win chance against each common meta team, the **Team check** (Proven and On "
         "paper), the biggest threats, and **swaps** that fix a problem without hurting the rest. **Compare "
         "versions** shows what a change did.",
         "Matchups", needs_team=True),
    Step("6 · Plan a game",
         "**Battle plan**: pick a meta team or paste the six you're facing, and it suggests which four to "
         "bring, who to lead with, and what to click on turn one.",
         "Battle plan", needs_team=True),
    Step("7 · Playbook and damage calcs",
         "**Playbook**: what worked for real players against Trick Room, Tailwind, weather and setup leads, "
         "next to what your team has. **Damage calc** checks any hit, with field effects and stat stages.",
         "Playbook", needs_team=True),
    Step("You're set",
         "**Recommendations** suggests the next Pokémon for any team, and the **Pokémon** tab shows how each "
         "one is played, with real tournament teams to start from. Something confusing? The feedback link "
         "is at the bottom of every page. Have fun!",
         "Recommendations"),
]


def _tab_for(step: Step, team_size: int) -> str:
    if step.tab == "builder":
        return "Team" if team_size == 0 else "Recommendations"
    return step.tab


def go(i: int, team_size: int) -> None:
    """Move to step i (a callback: it may set the open tab)."""
    if i < 0 or i >= len(STEPS):
        end()
        return
    st.session_state[STEP] = i
    st.session_state["main_tabs"] = _tab_for(STEPS[i], team_size)


def start(team_size: int = 0) -> None:
    go(0, team_size)


def end() -> None:
    st.session_state.pop(STEP, None)


def active() -> bool:
    return st.session_state.get(STEP) is not None


def build_for_me(fmt_id: str) -> None:
    """Step 1's action: build three Popular picks teams around the chosen Pokémon (or the most used one)."""
    from src.builder import build_teams
    from src.dex import load_dex
    from src.formats import FORMATS
    from src.usage import load_usage
    from ui.matchups_tab import archetypes_for
    from ui.recommendations_tab import weights_for
    ss = st.session_state
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    if usage is None:
        return
    names = list(usage.team_sheet_usage(dex))
    core = ss.get("build_core") if ss.get("build_core") in names else names[0]
    mode = ss.get("build_mode") if ss.get("build_mode") in ("popular", "hidden") else "popular"
    ss["build_core"], ss["build_mode"] = core, mode
    ss["built_teams"] = build_teams(core, dex, usage, doubles=fmt.is_doubles, mode=mode, weights=weights_for(mode),
                                    archetypes=archetypes_for(fmt_id), regulation=fmt.regulation,
                                    lock=ss.get("build_lock", []), ban=ss.get("build_ban", []))
    ss["built_for"] = (core, mode)
    ss[STEP] = 2


def load_first_for_me() -> None:
    """Step 2's action: load the top built team, then move on to editing it."""
    from ui.state import load_team
    built = st.session_state.get("built_teams") or []
    if built:
        load_team(built[0].sets)
        st.session_state[STEP] = 3
        st.session_state["main_tabs"] = "Team"


def tour_banner(team_size: int, fmt_id: str) -> None:
    """The current step, above the tabs, while the tour is on."""
    i = st.session_state.get(STEP)
    if i is None or not 0 <= i < len(STEPS):
        return
    step = STEPS[i]
    with st.container(border=True, key="tour"):
        st.progress((i + 1) / len(STEPS), text=f"Guided tour · step {i + 1} of {len(STEPS)}")
        st.markdown(f"**{step.title}**  \n{step.body}")
        if step.needs_team and team_size == 0:
            st.caption("This step needs a team: go back to step 2 to load one, or load the example team.")
        # a button row stays one row on a phone (ui/theme.py styles "button_row_" containers)
        cols = st.container(key="button_row_tour").columns(4 if i in (1, 2) else 3)
        cols[0].button("Back", key="tour_back", width="stretch", disabled=i == 0,
                       on_click=go, args=(i - 1, team_size))
        if i == 1:
            cols[1].button("Build for me", key="tour_do", width="stretch",
                           help="Builds three teams around the Pokémon picked in Build around (Popular picks).",
                           on_click=build_for_me, args=(fmt_id,))
        elif i == 2:
            cols[1].button("Load Team 1", key="tour_do", width="stretch",
                           disabled=not st.session_state.get("built_teams"), on_click=load_first_for_me)
        last = i == len(STEPS) - 1
        cols[-2].button("Finish" if last else "Next", key="tour_next", type="primary", width="stretch",
                        on_click=go, args=(i + 1, team_size))
        cols[-1].button("End", key="tour_end", width="stretch", on_click=end, help="End the tour")


__all__ = ["STEPS", "STEP", "start", "end", "go", "active", "tour_banner", "build_for_me", "load_first_for_me"]
