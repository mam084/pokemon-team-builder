"""
legality.py

Team checks that mirror the in-game rules for Champions regulations, so a team
built here can be entered in game without surprises:

- every Pokemon, item, ability and move is legal in the regulation
- Species Clause (no duplicate Pokemon) and Item Clause (no duplicate items)
- Stat Points: at most 32 in a stat, 66 in total
- six Pokemon on the sheet

It also raises softer warnings - e.g. three or more Mega Stones is legal, but
only one Pokemon can Mega Evolve per battle (two is normal: you pick at team
preview).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.dex import Dex, to_id
from src.stats import sp_problems
from src.team import MAX_MEGAS, TEAM_SIZE, PokemonSet


@dataclass(frozen=True)
class Issue:
    level: str   # "error" (illegal) or "warning" (legal but probably a mistake)
    message: str
    slot: int | None = None


def check_set(pset: PokemonSet, dex: Dex, slot: int | None = None) -> list[Issue]:
    issues: list[Issue] = []
    name = pset.nickname or pset.species

    species = dex.get_species(pset.species)
    if species is None:
        return [Issue("error", f"{pset.species} isn't legal in this regulation.", slot)]

    if pset.item and dex.get_item(pset.item) is None:
        issues.append(Issue("error", f"{name}'s item {pset.item} isn't legal.", slot))
    stone_targets = dex.mega_stone_species(pset.item)
    if stone_targets and species.id not in stone_targets:
        issues.append(Issue("warning", f"{name} can't use {pset.item}; it does nothing here.", slot))

    if pset.ability and to_id(pset.ability) not in {to_id(a) for a in species.abilities}:
        issues.append(Issue("error", f"{name} can't have the ability {pset.ability}.", slot))

    moves = [m for m in pset.moves if m]
    for move in moves:
        if not dex.can_learn(species.id, move):
            issues.append(Issue("error", f"{name} can't learn {move} in this regulation.", slot))
    dupes = [m for m, n in Counter(to_id(m) for m in moves).items() if n > 1]
    if dupes:
        issues.append(Issue("error", f"{name} has a duplicate move.", slot))
    if not moves:
        issues.append(Issue("warning", f"{name} has no moves yet.", slot))
    elif len(moves) < 4:
        issues.append(Issue("warning", f"{name} only has {len(moves)} move(s).", slot))

    if pset.nature and dex.get_nature(pset.nature) is None:
        issues.append(Issue("error", f"{name}'s nature {pset.nature} doesn't exist.", slot))

    rules = dex.rules
    for problem in sp_problems(pset.sps, rules["statPointTotal"], rules["statPointMax"]):
        issues.append(Issue("error", f"{name}: {problem}", slot))
    spent = sum(pset.sps.values())
    if spent < rules["statPointTotal"]:
        issues.append(Issue("warning", f"{name} has {rules['statPointTotal'] - spent} unspent Stat Points.", slot))
    return issues


def check_team(team: list[PokemonSet], dex: Dex) -> list[Issue]:
    issues: list[Issue] = []
    for i, pset in enumerate(team):
        issues.extend(check_set(pset, dex, slot=i))

    species_ids = [to_id(p.species) for p in team]
    for sid, n in Counter(species_ids).items():
        if n > 1:
            issues.append(Issue("error", f"Species Clause: {dex.get_species(sid).name if dex.get_species(sid) else sid} appears {n} times."))

    items = [to_id(p.item) for p in team if p.item]
    for iid, n in Counter(items).items():
        if n > 1:
            item_name = dex.items[iid]["name"] if iid in dex.items else iid
            issues.append(Issue("error", f"Item Clause: {item_name} is held by {n} Pokemon."))

    megas = [p.species for p in team if p.is_mega(dex)]
    if len(megas) > MAX_MEGAS:
        issues.append(Issue(
            "warning",
            f"{len(megas)} Mega Stones ({', '.join(megas)}): only one can Mega Evolve per battle, so the "
            "extras mostly hold an item that does nothing. Two is common (choose at team preview); "
            "three or more is rare.",
        ))

    if 0 < len(team) < TEAM_SIZE:
        issues.append(Issue("warning", f"Team has {len(team)}/6 Pokemon - Champions requires a full six."))
    return issues


def is_legal(team: list[PokemonSet], dex: Dex) -> bool:
    return not any(i.level == "error" for i in check_team(team, dex))
