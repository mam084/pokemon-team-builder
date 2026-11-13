"""
dex.py

Loads the per-regulation dex exported from Pokemon Showdown
(scripts/export_dex.js) and answers the questions the rest of the tool asks:
which Pokemon / items / moves are legal, what a Pokemon turns into when it
holds its Mega Stone, and what it can learn.

All lookups go through `to_id`, Showdown's own id scheme ("Rotom-Wash" ->
"rotomwash", "Farfetch’d" -> "farfetchd"), so names from pastes, Smogon usage
stats and the UI all resolve to the same key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEX_DIR = Path(__file__).resolve().parent.parent / "data" / "dex"
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_LABELS = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}
SPRITE_URL = "https://play.pokemonshowdown.com/sprites/gen5/{}.png"


_NON_ID = re.compile(r"[^a-z0-9]")


@lru_cache(maxsize=65536)
def _to_id(text: str) -> str:
    return _NON_ID.sub("", text.lower())


def to_id(text: str | None) -> str:
    """Showdown-style id: lowercase alphanumerics only."""
    return _to_id(text or "")


@dataclass(frozen=True)
class Species:
    id: str
    name: str
    num: int
    base_species: str
    forme: str
    types: tuple[str, ...]
    base_stats: dict
    abilities: tuple[str, ...]
    is_mega: bool
    battle_only: tuple[str, ...]
    required_item: str | None
    sprite: str
    tier: str
    doubles_tier: str
    learnset: frozenset = field(repr=False)

    @property
    def bst(self) -> int:
        return sum(self.base_stats.values())

    @property
    def sprite_url(self) -> str:
        return SPRITE_URL.format(self.sprite)


class Dex:
    """One regulation's worth of legal Pokemon data."""

    def __init__(self, raw: dict):
        self.regulation: str = raw["regulation"]
        self.format_name: str = raw["formatName"]
        self.generated_at: str = raw.get("generatedAt", "")
        self.rules: dict = raw["rules"]
        self.items: dict = raw["items"]
        self.moves: dict = raw["moves"]
        self.abilities: dict = raw["abilities"]
        self.natures: dict = raw["natures"]
        self.typechart: dict = raw["typechart"]
        self.species: dict[str, Species] = {
            sid: Species(
                id=sid,
                name=s["name"],
                num=s["num"],
                base_species=s["baseSpecies"],
                forme=s["forme"],
                types=tuple(s["types"]),
                base_stats=s["baseStats"],
                abilities=tuple(s["abilities"]),
                is_mega=s["isMega"],
                battle_only=tuple(s["battleOnly"]),
                required_item=s["requiredItem"],
                sprite=s["sprite"],
                tier=s.get("tier", ""),
                doubles_tier=s.get("doublesTier", ""),
                learnset=frozenset(s["learnset"]),
            )
            for sid, s in raw["species"].items()
        }
        # Mega Stone item id -> {base species id: mega species id}
        self._mega_stones: dict[str, dict[str, str]] = {
            iid: {to_id(base): to_id(mega) for base, mega in item["megaStone"].items()}
            for iid, item in self.items.items()
            if item.get("megaStone")
        }

    # ---- lookups -------------------------------------------------------
    def get_species(self, name: str | None) -> Species | None:
        return self.species.get(to_id(name))

    def get_item(self, name: str | None) -> dict | None:
        return self.items.get(to_id(name))

    def get_move(self, name: str | None) -> dict | None:
        return self.moves.get(to_id(name))

    def get_ability(self, name: str | None) -> dict | None:
        return self.abilities.get(to_id(name))

    def get_nature(self, name: str | None) -> dict | None:
        return self.natures.get(to_id(name))

    # ---- team-building helpers ----------------------------------------
    def selectable_species(self) -> list[Species]:
        """Pokemon you can put on a team sheet: no Megas or battle-only formes."""
        rows = [s for s in self.species.values() if not s.is_mega and not s.battle_only]
        return sorted(rows, key=lambda s: (s.num, s.name))

    def mega_stone_species(self, item: str | None) -> dict[str, str]:
        return self._mega_stones.get(to_id(item), {})

    def battle_form(self, species: str | None, item: str | None) -> Species | None:
        """The forme a Pokemon actually fights in: its Mega if holding the matching stone."""
        base = self.get_species(species)
        if base is None:
            return None
        mega_id = self.mega_stone_species(item).get(base.id)
        return self.species.get(mega_id, base) if mega_id else base

    def mega_options(self, species: str | None) -> list[str]:
        """Names of the Mega Stones a Pokemon can use (e.g. Charizard: X and Y)."""
        sid = to_id(species)
        return sorted(
            self.items[iid]["name"] for iid, mapping in self._mega_stones.items() if sid in mapping
        )

    def legal_items(self, species: str | None = None) -> list[str]:
        """All legal held items, hiding other Pokemon's Mega Stones."""
        sid = to_id(species)
        names = []
        for iid, item in self.items.items():
            stone = self._mega_stones.get(iid)
            if stone and sid not in stone:
                continue
            names.append(item["name"])
        return sorted(names)

    def learnable_moves(self, species: str | None) -> list[str]:
        s = self.get_species(species)
        if s is None:
            return []
        return sorted(self.moves[m]["name"] for m in s.learnset if m in self.moves)

    def can_learn(self, species: str | None, move: str | None) -> bool:
        s = self.get_species(species)
        return bool(s) and to_id(move) in s.learnset


@lru_cache(maxsize=None)
def load_dex(regulation: str) -> Dex:
    path = DEX_DIR / f"{regulation}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing - run `node scripts/export_dex.js` (see README) to build it."
        )
    return Dex(json.loads(path.read_text()))
