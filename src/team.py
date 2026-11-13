"""
team.py

The team model: a list of up to six `PokemonSet`s, each a full competitive set
(item, ability, nature, Stat Points, moves) like a Showdown paste.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.dex import STATS, Dex, Species
from src.stats import calc_stats

TEAM_SIZE = 6


def empty_sps() -> dict:
    return {s: 0 for s in STATS}


@dataclass
class PokemonSet:
    species: str
    item: str = ""
    ability: str = ""
    nature: str = "Serious"
    sps: dict = field(default_factory=empty_sps)
    moves: list[str] = field(default_factory=list)
    nickname: str = ""

    def battle_form(self, dex: Dex) -> Species | None:
        return dex.battle_form(self.species, self.item)

    def battle_ability(self, dex: Dex) -> str:
        """A Mega's ability replaces whatever the base forme had."""
        form = self.battle_form(dex)
        if form is not None and form.is_mega:
            return form.abilities[0]
        return self.ability

    def stats(self, dex: Dex, mega: bool = True) -> dict:
        form = self.battle_form(dex) if mega else dex.get_species(self.species)
        if form is None:
            return {s: 0 for s in STATS}
        return calc_stats(form.base_stats, self.sps, dex.get_nature(self.nature))

    def is_mega(self, dex: Dex) -> bool:
        form = self.battle_form(dex)
        return bool(form and form.is_mega)

    def to_dict(self) -> dict:
        return {
            "species": self.species, "item": self.item, "ability": self.ability,
            "nature": self.nature, "sps": dict(self.sps), "moves": list(self.moves),
            "nickname": self.nickname,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PokemonSet":
        sps = empty_sps()
        sps.update({k: int(v) for k, v in (d.get("sps") or {}).items() if k in sps})
        return cls(
            species=d["species"], item=d.get("item", ""), ability=d.get("ability", ""),
            nature=d.get("nature", "Serious"), sps=sps, moves=list(d.get("moves", []))[:4],
            nickname=d.get("nickname", ""),
        )


def default_set(dex: Dex, species: str) -> PokemonSet:
    """A blank-but-valid starting set: first ability, neutral nature, no SP."""
    s = dex.get_species(species)
    if s is None:
        raise KeyError(species)
    return PokemonSet(species=s.name, ability=s.abilities[0])
