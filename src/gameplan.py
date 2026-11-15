"""
gameplan.py

How to play one matchup: what to bring, who to lead with, what to watch out
for and how the Speed order looks - built from the same pair scores and
damage calcs as the matchup heatmap.

- Bring: best bring-N by team score (matchup.best_bring).
- Leads: the pair from your bring that covers their team best, with a bonus for
  lead tools (Fake Out, Tailwind/Trick Room, Intimidate, redirection) - the
  pieces that decide turn one.
- Their likely leads: their two members with the most of those lead tools.
- Watch out for: their Pokemon your bring answers worst, with the hit they land.
- Speed order: everyone in the matchup, fastest first (Trick Room reverses it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import pandas as pd

from src.analysis import Member
from src.dex import Dex
from src.matchup import best_attack, team_score
from src.roles import set_roles

LEAD_TOOLS = {"Fake Out support": 0.35, "Tailwind setter": 0.3, "Trick Room setter": 0.3, "Screens": 0.3,
              "Intimidate": 0.15, "Redirector": 0.2, "Speed control": 0.1}


@dataclass
class Plan:
    bring: list[str]
    lead: list[str]
    back: list[str]
    lead_why: str
    their_leads: list[str]
    watch_out: list[dict] = field(default_factory=list)   # {pokemon, hit, why}
    strongest: str = ""
    strongest_why: str = ""
    speed: list[dict] = field(default_factory=list)       # {pokemon, side, speed}
    speed_note: str = ""
    support_note: str = ""
    usual: tuple | None = None   # (bring, lead, games) from replays, filled in by the UI
    their_leads_source: str = "calcs"
    bring_source: str = "calcs"


def _tools(m: Member, dex: Dex, doubles: bool) -> list[str]:
    if m.pset is None:
        return []
    return [t.label for t in set_roles(m.pset, dex, doubles) if t.label in LEAD_TOOLS]


def game_plan(members: list[Member], theirs: list[Member], matrix: pd.DataFrame, bring: list[str],
              dex: Dex, doubles: bool = True, trick_room: bool = False, weather: str | None = None) -> Plan:
    by_label = {m.label: m for m in members}
    brought = [by_label[b] for b in bring if b in by_label]
    tools = {m.label: _tools(m, dex, doubles) for m in brought}

    # leads: coverage of their team by the pair, plus lead tools (each kind counted once)
    best_key, lead = None, [b.label for b in brought[:2]]
    for pair in combinations([b.label for b in brought], 2):
        sub = matrix.loc[list(pair)]
        coverage = float(sub.max(axis=0).clip(-2, 2).mean())
        kinds = {t for p in pair for t in tools[p]}
        bonus = sum(LEAD_TOOLS[t] for t in kinds)
        key = coverage + bonus
        if best_key is None or key > best_key:
            best_key, lead = key, list(pair)
    back = [b for b in bring if b not in lead]
    short = lambda t: t.replace(" support", "").replace(" setter", "")  # noqa: E731
    lead_tools = [f"{' and '.join(short(t) for t in tools[p])} from {p}" for p in lead if tools[p]]
    covered = [c for c in matrix.columns if matrix.loc[lead, c].max() >= 0.5]
    lead_why = (f"Between them they beat {len(covered)} of their {len(matrix.columns)} Pokémon"
                + (f", with {', '.join(lead_tools)}" if lead_tools else "") + ".")

    # their likely leads: most lead tools, then the most dangerous
    their_tools = {o.label: _tools(o, dex, doubles) for o in theirs}
    danger = (-matrix.loc[bring]).max(axis=0)  # how hard each of theirs hits your bring
    their_leads = sorted((o.label for o in theirs),
                         key=lambda lbl: (-sum(LEAD_TOOLS[t] for t in their_tools[lbl]), -danger[lbl]))[:2]

    # watch out: their Pokemon your bring answers worst
    answers = matrix.loc[bring].max(axis=0).sort_values()
    watch = []
    for label, best in answers.items():
        if best >= 0.5 or len(watch) >= 3:
            continue
        opp = next(o for o in theirs if o.label == label)
        target = max(brought, key=lambda m: best_attack(opp, m, doubles, weather)[0])
        pct, move = best_attack(opp, target, doubles, weather)
        mine_pct, mine_move = max((best_attack(m, opp, doubles, weather) + (m.label,) for m in brought),
                                  key=lambda x: x[0])[:2]
        watch.append({
            "pokemon": label,
            "hit": f"{move} does {pct:.0f}% to your {target.label}" if move else "",
            "your best": f"your best hit on it is {mine_move} at {mine_pct:.0f}%" if mine_move else
                         "you have no real damage on it",
        })

    # strongest piece: wins the most pairings
    wins = (matrix.loc[bring] >= 0.5).sum(axis=1)
    strongest = wins.idxmax() if len(wins) else ""
    strongest_why = f"wins {int(wins.max())} of {len(matrix.columns)} pairings" if len(wins) else ""

    # speed order
    rows = [{"pokemon": m.label, "side": "yours", "speed": m.stats["spe"]} for m in brought]
    rows += [{"pokemon": o.label, "side": "theirs", "speed": o.stats["spe"]} for o in theirs]
    rows.sort(key=lambda r: r["speed"], reverse=not trick_room)
    note = "Trick Room: slowest moves first." if trick_room else ""
    if any("Tailwind setter" in t for t in their_tools.values()):
        note = (note + " " if note else "") + "They run Tailwind, which doubles their Speed for 4 turns."

    return Plan(bring=list(bring), lead=lead, back=back, lead_why=lead_why, their_leads=their_leads,
                watch_out=watch, strongest=strongest, strongest_why=strongest_why, speed=rows,
                speed_note=note)


__all__ = ["Plan", "game_plan", "team_score"]
