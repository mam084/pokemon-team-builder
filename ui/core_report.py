"""Build around a Pokémon: what real players do with it (src/core_report.py), shown before you build."""

from __future__ import annotations

import math

import streamlit as st

from src.dex import to_id
from src.similar_teams import ordinal

SHOWN = 5   # entries per line: enough to act on, short enough for a phone


@st.cache_data(show_spinner=False, ttl=3600)
def _index(format_id: str) -> dict | None:
    from src.core_report import load_index
    return load_index(format_id)


@st.cache_data(show_spinner=False, max_entries=64)
def _matchups(format_id: str, regulation: str, core_paste: str, doubles: bool) -> dict:
    from src.core_report import core_matchups
    from src.dex import load_dex
    from src.paste import parse_paste
    from src.usage import load_usage
    dex = load_dex(regulation)
    return core_matchups(parse_paste(core_paste, dex)[0][0], load_usage(format_id), dex, doubles=doubles)


def _names(ids, dex) -> list[str]:
    names = {dex.sheet_id(s): s.name for s in dex.selectable_species() if not dex.is_cosmetic(s)}
    return [names.get(i, i) for i in ids]


def _pct_list(d: dict, label=lambda k: k, n: int = 6) -> str:
    return ", ".join(f"{label(k)} {v:.0%}" for k, v in list(d.items())[:n])


def _vs_ratings(won: int, n: int, expected: float) -> str:
    """'won 48 of 107; ratings predicted 51 (normal luck)' - the honest way to show a small sample."""
    if n < 10:
        return f"won {won} of {n} rated games (too few to judge)"
    sd = math.sqrt(n * 0.25)
    gap = won - expected
    verdict = ("in line with that" if abs(gap) < 1.5 * sd else
               "clearly more" if gap > 0 else "clearly fewer")
    return f"won **{won} of {n}** rated games; the players' ratings predicted {expected:.0f} ({verdict})"


def core_report_section(core_name: str, core_set, dex, usage, fmt) -> list[str]:
    """Render the report; returns the core's threats (most used first) for the built-team cards."""
    from src.paste import export_paste
    from ui.analysis_tab import _tournament_teams
    form = core_set.battle_form(dex) if core_set else None
    label = form.name if form else core_name
    root = dex.sheet_id(dex.get_species(core_name))
    lines = []

    idx = _index(fmt.id)
    row = (idx or {}).get("pokemon", {}).get(root)
    if row:
        when = f"{idx['from'][5:].replace('-', '/')}–{idx['to'][5:].replace('-', '/')}"
        mega = form is not None and form.is_mega and row.get("mega_rated")
        n, won, exp = ((row["mega_rated"], row["mega_rated_won"], row["mega_expected"]) if mega else
                       (row["rated"], row["rated_won"], row["rated_expected"]))
        lines.append(f"**Ladder & Bo3** ({when}): on {row['previews']:,} team previews"
                     + (f"; when it Mega Evolved, {_vs_ratings(won, n, exp)}" if mega else
                        f"; when brought, {_vs_ratings(won, n, exp)}") + ".")
        if row.get("partners"):
            lines.append("**Usual partners:** " + _pct_list(
                dict(zip(_names(row["partners"], dex), row["partners"].values())), n=SHOWN))
        if row.get("moves"):
            moves = {dex.moves[m]["name"] if m in dex.moves else m: v for m, v in row["moves"].items()}
            items = {dex.items[i]["name"] if i in dex.items else i: v for i, v in row.get("items", {}).items()}
            lines.append(f"**On {row['sheets']} open team sheets:** {_pct_list(moves, n=SHOWN)}"
                         + (f" · {_pct_list(items, n=2)}" if items else ""))

    teams = _tournament_teams(fmt.regulation)
    tour = None
    if teams:
        from src.core_report import tournament_core
        tour = tournament_core(root, teams, dex, form.required_item if form is not None and form.is_mega else None)
        if tour["teams"]:
            w, l = tour["wins"], tour["losses"]
            text = (f"**Tournaments:** {tour['teams']} team{'s' if tour['teams'] != 1 else ''} went {w}–{l} "
                    f"({w / max(w + l, 1):.0%}, against {tour['base']:.0%} for all teams)")
            if tour["natures"]:
                text += "; natures " + _pct_list(tour["natures"], n=3)
            lines.append(text + ".")
        else:
            lines.append(f"**Tournaments:** none of the {len(teams):,} team lists ran {label}.")

    calcs = _matchups(fmt.id, fmt.regulation, export_paste([core_set]), fmt.is_doubles) if core_set else None
    threats = []
    if calcs:
        if calcs["beats"]:
            lines.append(f"**{label} beats one-on-one:** " + ", ".join(
                f"{n} ({c})" for n, c in calcs["beats"][:SHOWN]))
        if calcs["threats"]:
            threats = [n for n, _ in calcs["threats"][:SHOWN]]
            lines.append(f"**Beats {label}:** " + ", ".join(f"{n} ({c})" for n, c in calcs["threats"][:SHOWN])
                         + ". Each team below says which of these it answers.")

    if not lines:
        return threats
    with st.container(border=True):
        st.markdown(f"**What players do with {label}**")
        st.markdown("\n".join(f"- {x}" for x in lines))
        proven = []
        if row:
            for t in row.get("teams", []):
                proven.append((f"Ladder{' Bo3' if t['bo3'] else ''} win, {t['rating']} rated, "
                               f"{t['date'][5:].replace('-', '/')}: " + ", ".join(t["team"]), t["team"]))
        if tour:
            for t in tour["best"]:
                place = f"{ordinal(t['placing'])} of {t['players']}" if t.get("placing") else "tournament"
                proven.append((f"{place} ({t['wins']}–{t['losses']}), {t['date'][5:].replace('-', '/')}: "
                               + ", ".join(t["team"]), t["team"]))
        if proven:
            pick = st.selectbox("Start from a real team", range(len(proven)), key="core_proven",
                                format_func=lambda i: proven[i][0])
            st.button("Load this real team", key="core_proven_load", width="stretch",
                      on_click=_load_real, args=(proven[pick][1], core_name, core_set, dex, usage))
        st.caption("Ratings, not teams, decide most games, so a win count is only shown next to what the "
                   "two players' ratings predicted. Damage calcs use each Pokémon's most common set. "
                   "Real teams load with each Pokémon's most common set.")
    return threats


def _load_real(species: list[str], core_name: str, core_set, dex, usage) -> None:
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


def threats_line(team_sets, threats: list[str], core_label: str, dex, usage, doubles: bool) -> str:
    """'Answers 7 of 8 threats to Feraligatr-Mega (not Floette-Mega)' for a built team's card."""
    if not threats:
        return ""
    from src.core_report import answered
    yes, no = answered(team_sets, threats, usage, dex, doubles)
    total = len(yes) + len(no)
    if not total:
        return ""
    text = f"Answers {len(yes)} of the {total} threats to {core_label}"
    return text + (f" (not {', '.join(no[:3])}{'…' if len(no) > 3 else ''})" if no else "")


__all__ = ["core_report_section", "threats_line"]
