"""Shared pieces of "what players do with a Pokémon" (src/core_report.py): cached data for the Pokémon
tab's profile, and the builder's one-line threat check on each built team."""

from __future__ import annotations

import math

import streamlit as st

from src.dex import to_id

SHOWN = 5   # entries per line: enough to act on, short enough for a phone


@st.cache_data(show_spinner=False, ttl=3600)
def index(format_id: str) -> dict | None:
    from src.core_report import load_index
    return load_index(format_id)


@st.cache_data(show_spinner=False, max_entries=64)
def matchups(format_id: str, regulation: str, core_paste: str, doubles: bool) -> dict:
    from src.core_report import core_matchups
    from src.dex import load_dex
    from src.paste import parse_paste
    from src.usage import load_usage
    dex = load_dex(regulation)
    return core_matchups(parse_paste(core_paste, dex)[0][0], load_usage(format_id), dex, doubles=doubles)


@st.cache_data(show_spinner=False, max_entries=64)
def setup(format_id: str, regulation: str, core_paste: str, doubles: bool) -> dict | None:
    from src.dex import load_dex
    from src.paste import parse_paste
    from src.setup import after_setup
    from src.usage import load_usage
    dex = load_dex(regulation)
    return after_setup(parse_paste(core_paste, dex)[0][0], load_usage(format_id), dex, doubles=doubles)


def names(ids, dex) -> list[str]:
    by_id = {dex.sheet_id(s): s.name for s in dex.selectable_species() if not dex.is_cosmetic(s)}
    return [by_id.get(i, i) for i in ids]


def pct_list(d: dict, n: int = SHOWN) -> str:
    return ", ".join(f"{k} {v:.0%}" for k, v in list(d.items())[:n])


def vs_ratings(won: int, n: int, expected: float) -> str:
    """'won 48 of 107; ratings predicted 51 (in line with that)': the honest way to show a small sample."""
    if n < 10:
        return f"won {won} of {n} rated games (too few to judge)"
    sd = math.sqrt(n * 0.25)
    gap = won - expected
    verdict = ("in line with that" if abs(gap) < 1.5 * sd else
               "clearly more" if gap > 0 else "clearly fewer")
    return f"won **{won} of {n}** rated games; the players' ratings predicted {expected:.0f} ({verdict})"


def load_real(species: list[str], core_name: str, core_set, dex, usage) -> None:
    """Load a real team: this Pokémon's set first, then each teammate's builder set (Item Clause kept)."""
    from src.builder import _set_for
    from ui.state import load_team
    team = [core_set] if core_set else []
    core_root = dex.sheet_id(dex.get_species(core_name))
    for name in species:
        s = dex.get_species(name)
        if s is None or dex.sheet_id(s) == core_root:
            continue
        pset = _set_for(name, team, dex, usage)
        if pset is not None and to_id(pset.species) not in {to_id(p.species) for p in team}:
            team.append(pset)
    load_team(team)


def thin_line(name: str, core_set, dex, usage, fmt, counts: bool = True) -> str:
    """The 'Little data on X' line when the teammate model has few teams on this Pokémon, else ''.
    With counts, it says how many tournament teams and rated games there are (the Pokémon tab already
    shows them, so it passes counts=False)."""
    from src.core_report import thin_data, thin_note, tournament_core
    species = dex.get_species(name)
    if species is None or usage is None:
        return ""
    root = dex.sheet_id(species)
    thin = thin_data(root, getattr(usage, "teammates", None))
    if thin is None:
        return ""
    if not counts:
        return thin_note(name, thin, point_to_tab=False)
    from ui.analysis_tab import _tournament_teams
    form = core_set.battle_form(dex) if core_set is not None else None
    mega = form is not None and form.is_mega
    teams = _tournament_teams(fmt.regulation)
    tour = tournament_core(root, teams, dex, form.required_item if mega else None) if teams else None
    row = ((index(fmt.id) or {}).get("pokemon") or {}).get(root) or {}
    games = (row.get("mega_rated") if mega and row.get("mega_rated") else row.get("rated"))
    return thin_note(form.name if mega else name, thin, tour["teams"] if tour else None,
                     tour["players"] if tour else None, games)


def core_threats(core_set, fmt) -> list[str]:
    """The meta Pokémon that beat the core one-on-one, most used first (for the built-team cards)."""
    if core_set is None:
        return []
    from src.paste import export_paste
    calcs = matchups(fmt.id, fmt.regulation, export_paste([core_set]), fmt.is_doubles)
    return [n for n, _ in calcs["threats"][:SHOWN]]


def threats_line(team_sets, threats: list[str], core_label: str, dex, usage, doubles: bool) -> str:
    """'Answers 4 of the 5 Pokémon that beat Feraligatr-Mega (not Floette-Mega)' for a built team's card."""
    if not threats:
        return ""
    from src.core_report import answered
    yes, no = answered(team_sets, threats, usage, dex, doubles)
    total = len(yes) + len(no)
    if not total:
        return ""
    text = f"Answers {len(yes)} of the {total} Pokémon that beat {core_label}"
    return text + (f" (not {', '.join(no[:3])}{'…' if len(no) > 3 else ''})" if no else "")


__all__ = ["thin_line", "index", "matchups", "setup", "names", "pct_list", "vs_ratings", "load_real", "core_threats",
           "threats_line", "SHOWN"]
