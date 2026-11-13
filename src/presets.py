"""
presets.py

Ready-made sets ("presets") for a Pokemon, built from Smogon usage stats.

Smogon publishes *marginal* distributions - how often each move, item and
spread appears - not complete sets, so presets are assembled from them:

1. Each usage entry of the Pokemon counts separately (Garchomp and
   Garchomp-Mega-Z are different entries, so the Mega gets its own presets).
2. Within an entry, every popular item (>= 8% of sets) seeds a preset. The item
   shapes the rest: Choice items drop Protect and status moves, and a Choice
   Scarf prefers a Speed-boosting spread.
3. Moves are the most popular legal moves that fit the item; the spread is the
   most popular one that fits too (falling back to the overall top spread).

Champions has no IVs: every stat is maxed, and the "spread" is the nature plus
the 66 Stat Points.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.dex import Dex, to_id
from src.stats import format_sps, parse_spread
from src.team import PokemonSet
from src.usage import UsageData

CHOICE_ITEMS = {"choicescarf", "choiceband", "choicespecs"}
MIN_ITEM_PCT = 8.0


@dataclass
class Preset:
    name: str          # short label, e.g. "Choice Scarf · Jolly"
    source: str        # the usage entry it came from, e.g. "Garchomp-Mega-Z"
    weight: float      # rough share of all this Pokemon's sets it represents (%)
    pset: PokemonSet

    @property
    def summary(self) -> str:
        spread = format_sps(self.pset.sps) or "no Stat Points"
        return f"{self.pset.item or 'No item'} · {self.pset.ability} · {self.pset.nature} · {spread}"


def _moves_for(entry_name: str, usage: UsageData, dex: Dex, base_id: str, choice: bool) -> list[str]:
    moves = []
    for move_id in usage.section(entry_name, "moves"):
        mv = dex.moves.get(to_id(move_id))
        if mv is None or not dex.can_learn(base_id, mv["id"]):
            continue
        if choice and mv["category"] == "Status":
            continue
        moves.append(mv["name"])
        if len(moves) == 4:
            break
    return moves


def _spread_for(entry_name: str, usage: UsageData, item_id: str) -> tuple[str, dict] | None:
    spreads = list(usage.section(entry_name, "spreads"))
    if not spreads:
        return None
    if item_id == "choicescarf":
        # Scarf users almost always max Speed with a +Spe nature.
        for spread in spreads:
            nature, sps = parse_spread(spread)
            if sps["spe"] >= 28 and nature in {"Jolly", "Timid", "Hasty", "Naive"}:
                return nature, sps
    return parse_spread(spreads[0])


def presets_for(species: str, usage: UsageData | None, dex: Dex, limit: int = 6) -> list[Preset]:
    if usage is None:
        return []
    base = dex.get_species(species)
    if base is None:
        return []
    if base.is_mega or base.battle_only:
        base = dex.get_species(base.battle_only[0] if base.battle_only else base.base_species)
    total_usage = usage.species_usage(base.name, dex) or 1.0

    presets: list[Preset] = []
    seen: set[tuple] = set()
    for entry_name in usage.variants(base.name, dex):
        form = dex.get_species(entry_name)
        entry_share = usage.usage(entry_name) / total_usage
        if form is not None and form.is_mega:
            item_options = [(to_id(form.required_item), 100.0)]
        else:
            item_options = [(to_id(i), pct) for i, pct in usage.section(entry_name, "items").items()
                            if pct >= MIN_ITEM_PCT and to_id(i) in dex.items
                            and not dex.mega_stone_species(i)]
            item_options = item_options or [("", 100.0)]

        # A Mega's own ability is fixed, so take the base forme's from its non-Mega entries.
        legal = {to_id(a): a for a in base.abilities}
        ability_pcts = usage.section(entry_name, "abilities")
        if form is not None and form.is_mega:
            ability_pcts = usage.section(base.name, "abilities")
        ability = next((legal[to_id(a)] for a in ability_pcts if to_id(a) in legal), base.abilities[0])
        for item_id, pct in item_options[:4]:
            choice = item_id in CHOICE_ITEMS
            moves = _moves_for(entry_name, usage, dex, base.id, choice)
            spread = _spread_for(entry_name, usage, item_id)
            nature, sps = spread if spread else ("Serious", None)
            item_name = dex.items[item_id]["name"] if item_id in dex.items else ""
            pset = PokemonSet(species=base.name, item=item_name, ability=ability, nature=nature, moves=moves)
            if sps:
                pset.sps = sps
            key = (pset.item, tuple(sorted(moves)), nature)
            if key in seen:
                continue
            seen.add(key)
            label = f"{item_name or 'No item'} · {nature}"
            if form is not None and form.is_mega:
                label = f"{form.name} · {nature}"
            presets.append(Preset(label, entry_name, round(entry_share * pct, 1), pset))

    presets.sort(key=lambda p: -p.weight)
    return presets[:limit]
