"""
opponent.py - the team you're facing, from its team sheet.

Open team sheets (Bo3 and tournaments) show each Pokemon's item, ability and moves but not its nature or
stat points; a full Showdown paste has everything. Whatever a sheet leaves out comes from that Pokemon's
most common set, and the Battle plan says which ones were filled in. Trick Room and weather are read from
the sets themselves, not from what the Pokemon usually runs.
"""

from __future__ import annotations

from src.dex import Dex, to_id
from src.paste import parse_paste
from src.team import PokemonSet
from src.usage import UsageData

FILLED_SPREAD = "nature and stat points"


def _has_spread(pset: PokemonSet) -> bool:
    return pset.nature != "Serious" or any(pset.sps.values())


def sets_from_sheet(text: str, dex: Dex, usage: UsageData | None) -> tuple[list[PokemonSet], dict[str, list[str]], list[str]]:
    """(sets, {species: parts filled from its most common set}, warnings) for a pasted team sheet.
    Pokemon the dex doesn't know are dropped with a warning."""
    sets, warnings = parse_paste(text, dex)
    out, filled = [], {}
    for p in sets:
        if dex.get_species(p.species) is None:
            continue
        common = usage.popular_set(p.species, dex) if usage is not None else None
        parts = []
        if common is not None:
            if not _has_spread(p):
                p.nature, p.sps = common.nature, dict(common.sps)
                parts.append(FILLED_SPREAD)
            if not p.moves:
                p.moves = list(common.moves)
                parts.append("moves")
            if not p.ability:
                p.ability = common.ability
                parts.append("ability")
            if not p.item and common.item:
                p.item = common.item
                parts.append("item")
        if parts:
            filled[p.species] = parts
        out.append(p)
    return out, filled, warnings


def mega_first(sets: list[PokemonSet], dex: Dex, mega: str | None = None) -> list[PokemonSet]:
    """Only one Mega per battle: the chosen one (or the first stone) leads the list, so build_members(...,
    evolve=0) evolves it and the others play in their base forme."""
    stones = [p for p in sets if p.is_mega(dex)]
    if not stones:
        return list(sets)
    first = next((p for p in stones if p.species == mega), stones[0])
    return [first] + [p for p in sets if p is not first]


def style_of(sets: list[PokemonSet], dex: Dex) -> tuple[bool, str | None, list[str]]:
    """(sets Trick Room, weather it sets, style tags) from the sets as written: battle ability and moves."""
    from src.matchup import SETTERS, WEATHER_OF
    tags = []
    for label, abilities, moves in SETTERS:
        for i, p in enumerate(sets):
            evolves = i == 0  # mega_first order: only the first Mega Evolves
            abil = {to_id(p.battle_ability(dex, mega=evolves and p.is_mega(dex)))}
            if abil & abilities or {to_id(m) for m in p.moves} & moves:
                tags.append(label)
                break
    weather = next((WEATHER_OF[t] for t in tags if t in WEATHER_OF), None)
    return "Trick Room" in tags, weather, tags


__all__ = ["sets_from_sheet", "mega_first", "style_of", "FILLED_SPREAD"]
