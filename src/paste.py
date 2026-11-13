"""
paste.py

Import and export teams in Pokemon Showdown's paste format, the format every
Champions tool (Showdown, Pikalytics, team reports) shares:

    Garganacl @ Leftovers
    Ability: Purifying Salt
    Level: 50
    EVs: 32 HP / 2 Def / 32 SpD
    Careful Nature
    - Salt Cure
    - Body Press

Showdown stores Champions Stat Points in the "EVs" line, so that's what we
read and write. A "SPs:" line is accepted too. Lines that don't apply to
Champions (IVs, Tera Type, Shiny, Happiness...) are ignored.
"""

from __future__ import annotations

import re

from src.dex import STAT_LABELS, Dex
from src.stats import format_sps
from src.team import PokemonSet, empty_sps

_LABEL_TO_STAT = {label.lower(): stat for stat, label in STAT_LABELS.items()}
_GENDER = re.compile(r"\s*\((M|F)\)\s*$")


def _parse_header(line: str) -> tuple[str, str, str]:
    """'Nick (Species) (F) @ Item' -> (species, nickname, item)."""
    name, _, item = line.partition(" @ ")
    name = _GENDER.sub("", name.strip())
    match = re.match(r"^(.*?)\s*\(([^()]+)\)$", name)
    if match:
        nickname, species = match.group(1).strip(), match.group(2).strip()
    else:
        nickname, species = "", name
    return species, nickname, item.strip()


def _parse_sps(text: str) -> dict:
    sps = empty_sps()
    for chunk in text.split("/"):
        parts = chunk.strip().split()
        if len(parts) == 2 and parts[1].lower() in _LABEL_TO_STAT:
            sps[_LABEL_TO_STAT[parts[1].lower()]] = int(parts[0])
    return sps


def parse_paste(text: str, dex: Dex | None = None) -> tuple[list[PokemonSet], list[str]]:
    """
    Parse a Showdown paste. Returns (sets, warnings). When a dex is given,
    names are normalized to their canonical spelling and anything unknown is
    reported as a warning rather than raising.
    """
    sets: list[PokemonSet] = []
    warnings: list[str] = []
    blocks = [b for b in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")) if b.strip()]

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines or lines[0].startswith("==="):  # team-folder header lines
            lines = lines[1:]
        if not lines:
            continue
        species, nickname, item = _parse_header(lines[0])
        pset = PokemonSet(species=species, item=item, nickname=nickname)
        for line in lines[1:]:
            if line.startswith("- "):
                move = line[2:].strip()
                if move and len(pset.moves) < 4:
                    pset.moves.append(move)
            elif line.lower().startswith("ability:"):
                pset.ability = line.split(":", 1)[1].strip()
            elif line.lower().startswith(("evs:", "sps:", "stat points:")):
                pset.sps = _parse_sps(line.split(":", 1)[1])
            elif line.lower().endswith(" nature"):
                pset.nature = line[: -len(" nature")].strip()

        if dex is not None:
            _canonicalize(pset, dex, warnings)
        sets.append(pset)

    if len(sets) > 6:
        warnings.append(f"Paste has {len(sets)} Pokemon; only the first 6 were kept.")
        sets = sets[:6]
    return sets, warnings


def _canonicalize(pset: PokemonSet, dex: Dex, warnings: list[str]) -> None:
    species = dex.get_species(pset.species)
    if species is None:
        warnings.append(f"{pset.species} isn't legal in {dex.format_name}.")
    else:
        # A paste may name the Mega forme directly; team sheets list the base.
        if species.is_mega or species.battle_only:
            base = dex.get_species(species.battle_only[0] if species.battle_only else species.base_species)
            if species.is_mega and species.required_item and not pset.item:
                pset.item = species.required_item
            species = base or species
        pset.species = species.name
        if not pset.ability:
            pset.ability = species.abilities[0]

    for attr, getter in (("item", dex.get_item), ("ability", dex.get_ability), ("nature", dex.get_nature)):
        value = getattr(pset, attr)
        if not value:
            continue
        found = getter(value)
        if found is None:
            warnings.append(f"{pset.species}: unknown or illegal {attr} '{value}'.")
        else:
            setattr(pset, attr, found["name"])

    moves = []
    for move in pset.moves:
        found = dex.get_move(move)
        if found is None:
            warnings.append(f"{pset.species}: '{move}' isn't a legal move in this regulation.")
            moves.append(move)
        else:
            moves.append(found["name"])
    pset.moves = moves


def export_paste(team: list[PokemonSet]) -> str:
    blocks = []
    for pset in team:
        header = f"{pset.nickname} ({pset.species})" if pset.nickname else pset.species
        if pset.item:
            header += f" @ {pset.item}"
        lines = [header]
        if pset.ability:
            lines.append(f"Ability: {pset.ability}")
        lines.append("Level: 50")
        spread = format_sps(pset.sps)
        if spread:
            lines.append(f"EVs: {spread}")
        if pset.nature:
            lines.append(f"{pset.nature} Nature")
        lines.extend(f"- {move}" for move in pset.moves if move)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
