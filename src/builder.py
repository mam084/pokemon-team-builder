"""
builder.py

Build a whole team around one Pokemon.

Starting from the core Pokemon (its popular set, or the set you made), the
builder adds one Pokemon at a time: whichever the recommender ranks highest
for the team so far, using that Pokemon's popular set with an item that keeps
Item Clause, and a non-Mega set once the team has its Mega. To give real
alternatives rather than three near-copies, team k starts from the k-th best
second Pokemon; after that each team is filled greedily.

The finished teams are then scored against the rebuilt meta teams with the
same damage-based matchup engine as the Matchups tab, and ordered by that score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis import build_members
from src.dex import Dex, to_id
from src.recommend import recommend
from src.team import PokemonSet
from src.usage import UsageData

TEAM_SIZE = 6


@dataclass
class BuiltTeam:
    sets: list[PokemonSet]
    reasons: list[str] = field(default_factory=list)   # why each added Pokemon was picked
    meta_score: float | None = None


def _set_for(name: str, team: list[PokemonSet], dex: Dex, usage: UsageData) -> PokemonSet | None:
    taken = {p.item for p in team if p.item}
    has_mega = any(p.is_mega(dex) for p in team)
    return usage.popular_set(name, dex, taken_items=taken, allow_mega=not has_mega)


def _complete(team: list[PokemonSet], reasons: list[str], dex: Dex, usage: UsageData, doubles: bool,
              mode: str, weights: dict | None) -> None:
    while len(team) < TEAM_SIZE:
        recs = recommend(build_members(team, dex), dex, usage, doubles=doubles, weights=weights,
                         top_n=15, mode=mode)
        added = False
        for _, row in recs.iterrows():
            pset = _set_for(row["pokemon"], team, dex, usage)
            if pset is not None and to_id(pset.species) not in {to_id(p.species) for p in team}:
                team.append(pset)
                reasons.append(f"{pset.species}: {row['why']}")
                added = True
                break
        if not added:
            break


def build_teams(core: PokemonSet | str, dex: Dex, usage: UsageData, doubles: bool = True,
                mode: str = "popular", weights: dict | None = None, alternatives: int = 3,
                archetypes=None) -> list[BuiltTeam]:
    if isinstance(core, str):
        core = usage.popular_set(core, dex)
        if core is None:
            return []
    first = recommend(build_members([core], dex), dex, usage, doubles=doubles, weights=weights,
                      top_n=alternatives * 3, mode=mode)
    teams: list[BuiltTeam] = []
    for _, row in first.iterrows():
        if len(teams) >= alternatives:
            break
        second = _set_for(row["pokemon"], [core], dex, usage)
        if second is None:
            continue
        built = BuiltTeam([core, second], [f"{second.species}: {row['why']}"])
        _complete(built.sets, built.reasons, dex, usage, doubles, mode, weights)
        if len(built.sets) == TEAM_SIZE and all(
            {to_id(p.species) for p in built.sets} != {to_id(p.species) for p in t.sets} for t in teams
        ):
            teams.append(built)

    if archetypes:
        from src.matchup import meta_matchups
        for t in teams:
            table = meta_matchups(build_members(t.sets, dex), archetypes, usage, dex, doubles=doubles)
            w = table["popularity"]
            t.meta_score = float((table["score"] * w).sum() / w.sum()) if len(table) else 0.0
        teams.sort(key=lambda t: -(t.meta_score or 0))
    return teams
