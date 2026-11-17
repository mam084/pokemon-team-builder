"""
similar_teams.py

Tournament teams like yours: real Limitless team lists that share most of your Pokemon, with
how they placed and their records - a "proven to win" check next to the usage-based ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.dex import Dex


@dataclass
class Similar:
    shared: int
    placing: int
    players: int
    wins: int
    losses: int
    date: str
    player: str
    extra: list[str]     # their Pokemon you don't have (team-sheet ids)
    missing: list[str]   # yours they don't run


def roots_of(sets, dex: Dex) -> set[str]:
    out = set()
    for p in sets:
        s = dex.get_species(p.species)
        if s is not None:
            out.add(dex.sheet_id(s))
    return out


def find_similar(team, tournament_teams: list[dict], dex: Dex) -> tuple[list[Similar], int]:
    """(teams sharing the most of yours, best first; how many you must share to count). Shares
    needed: 4 for a team of 5-6, 3 for 3-4, so the matches really are 'like yours'."""
    mine = roots_of(team, dex)
    need = 4 if len(mine) >= 5 else 3
    if len(mine) < 3:
        return [], need
    out = []
    for t in tournament_teams:
        theirs = roots_of(t["sets"], dex)
        shared = len(mine & theirs)
        if shared >= need:
            out.append(Similar(shared, int(t.get("placing") or 0), int(t.get("players") or 0),
                               int(t.get("wins") or 0), int(t.get("losses") or 0), t["date"], t.get("player", ""),
                               sorted(theirs - mine), sorted(mine - theirs)))
    # most shared first, then how high they finished (as a share of the field)
    out.sort(key=lambda s: (-s.shared, s.placing / max(s.players, 1) if s.placing else 1.0))
    return out, need


def top_cut(s: Similar) -> bool:
    """Top 8, in an event of at least 16 players."""
    return s.players >= 16 and 0 < s.placing <= 8


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


__all__ = ["Similar", "find_similar", "top_cut", "ordinal", "roots_of"]
