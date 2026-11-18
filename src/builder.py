"""
builder.py

Build a whole team around one Pokemon.

Starting from the core Pokemon (its popular set, or the set you made), the
builder adds one Pokemon at a time: whichever the recommender ranks highest
for the team so far, using that Pokemon's popular set with an item that keeps
Item Clause (up to two Mega Stones - you choose which Mega Evolves each game). To give real
alternatives rather than three near-copies, the second Pokemon differs per
team: the best pick overall, then the best setter of each game plan the core
already benefits from (a sand setter for Garganacl, Trick Room for slow
attackers), then the next best picks. After that each team is filled greedily.

The finished teams are then ordered by src/team_rating.py: teammate fit plus the learned win
chance against the meta teams, the combination that tracked real tournament results best
(scripts/app_vs_results.py). Without that model, by the damage-calc score vs the meta.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis import build_members, mega_variants
from src.dex import Dex, to_id
from src.recommend import recommend
from src.team import MAX_MEGAS, PokemonSet
from src.usage import UsageData

TEAM_SIZE = 6


@dataclass
class BuiltTeam:
    sets: list[PokemonSet]
    reasons: list[str] = field(default_factory=list)   # why each added Pokemon was picked
    meta_score: float | None = None
    rating: float | None = None                        # src.team_rating combined z-score
    chance: float | None = None                        # learned win chance vs the meta
    percentile: float | None = None                    # share of tournament teams it rates above
    theme: str = ""                                    # e.g. "Sand" when seeded by a sand setter


def _set_for(name: str, team: list[PokemonSet], dex: Dex, usage: UsageData) -> PokemonSet | None:
    taken = {p.item for p in team if p.item}
    megas = sum(p.is_mega(dex) for p in team)
    return usage.popular_set(name, dex, taken_items=taken, allow_mega=megas < MAX_MEGAS, team=team)


ANCHOR_WEIGHT = 1.0  # how many times the core's pairings count while filling (tested: builder_lab)


def _complete(team: list[PokemonSet], reasons: list[str], dex: Dex, usage: UsageData, doubles: bool,
              mode: str, weights: dict | None) -> None:
    while len(team) < TEAM_SIZE:
        recs = recommend(build_members(team, dex), dex, usage, doubles=doubles, weights=weights,
                         top_n=15, mode=mode, anchor=team[0].species, anchor_weight=ANCHOR_WEIGHT)
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
                archetypes=None, regulation: str | None = None) -> list[BuiltTeam]:
    if isinstance(core, str):
        core = usage.popular_set(core, dex)
        if core is None:
            return []
    first = recommend(build_members([core], dex), dex, usage, doubles=doubles, weights=weights,
                      top_n=None, mode=mode).reset_index(drop=True)
    if first.empty:
        return []
    # seeds: best overall, then the best starter of each plan the core benefits from, then the rest
    seeds = [0]
    starters = first[(first["starts"] != "") & (first["plan"] >= 0.3)]
    for plan_label, group in starters.groupby("starts", sort=False):
        if len(seeds) < alternatives and plan_label != first.iloc[0]["starts"]:
            seeds.append(int(group.index[0]))
    seeds = sorted(set(seeds), key=seeds.index)
    seeds += [i for i in range(min(len(first), alternatives * 3)) if i not in seeds]
    teams: list[BuiltTeam] = []
    for i in seeds:
        if len(teams) >= alternatives:
            break
        row = first.iloc[i]
        second = _set_for(row["pokemon"], [core], dex, usage)
        if second is None:
            continue
        built = BuiltTeam([core, second], [f"{second.species}: {row['why']}"], theme=row["starts"])
        _complete(built.sets, built.reasons, dex, usage, doubles, mode, weights)
        if len(built.sets) == TEAM_SIZE and all(
            {to_id(p.species) for p in built.sets} != {to_id(p.species) for p in t.sets} for t in teams
        ):
            teams.append(built)

    if archetypes and regulation and _rate(teams, dex, usage, archetypes, regulation):
        return teams
    if archetypes:
        from src.matchup import meta_matchups
        for t in teams:
            table = meta_matchups(mega_variants(t.sets, dex), archetypes, usage, dex, doubles=doubles)
            w = table["popularity"]
            t.meta_score = float((table["score"] * w).sum() / w.sum()) if len(table) else 0.0
        teams.sort(key=lambda t: -(t.meta_score or 0))
    return teams


def _rate(teams: list[BuiltTeam], dex: Dex, usage: UsageData, archetypes, regulation: str) -> bool:
    """Order by the tested team rating; False when its models aren't available."""
    from src import team_rating as R
    from src.match_model import load_model
    ref, model = R.load_reference(regulation), load_model(regulation)
    if ref is None or model is None or usage.teammates is None:
        return False
    sides, weights = R.meta_sides(archetypes, usage, dex)
    for t in teams:
        fit = R.teammate_fit(t.sets, dex, usage.teammates)
        if fit is None:
            return False
        t.chance = R.learned_vs_meta(t.sets, dex, usage, model, sides, weights)
        t.rating = R.combined(fit, t.chance, ref)
        t.percentile = R.percentile(t.rating, ref)
    teams.sort(key=lambda t: -t.rating)
    return True
