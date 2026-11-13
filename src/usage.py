"""
usage.py

Smogon usage statistics for Champions formats.

`trim_chaos` turns Smogon's monthly "chaos" JSON into the compact file the app
ships with; `UsageData` loads that file and answers questions like "what does
Garganacl usually run?" and "who is it usually paired with?".

How the numbers are derived from the chaos file
-----------------------------------------------
For every Pokemon, chaos lists *weighted counts* (each team weighted by its
player's rating) for its abilities, items, moves, spreads and teammates. The
ability counts sum to that Pokemon's total weighted appearances, so dividing by
that sum turns every section into a percentage of "teams with this Pokemon":

    item %      = share of its teams running that item
    move %      = share running that move (4 moves, so these sum to ~400%)
    teammate %  = P(teammate on the team | this Pokemon on the team)

Smogon lists each Mega as its own entry ("Charizard-Mega-Y"), because that is
the form that battles. Team sheets list the base Pokemon plus its Mega Stone, so
`variants` / `combined_section` fold a species' base and Mega entries together
when the app needs the team-sheet view.

Teammate % is not symmetric: P(B | A) != P(A | B) when A and B have different
usage, which is why the recommender also looks at *lift* (P(B | A) / P(B)).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.dex import Dex, to_id
from src.stats import parse_spread
from src.team import PokemonSet

USAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "usage"

# How much of each section to keep when trimming (the long tails are noise).
KEEP = {"abilities": 4, "items": 10, "moves": 16, "spreads": 8, "teammates": 30, "counters": 12}
MIN_USAGE_PCT = 0.02


def _percentages(section: dict, total: float, keep: int) -> dict:
    if total <= 0:
        return {}
    rows = sorted(((k, v / total * 100) for k, v in section.items() if v > 0), key=lambda kv: -kv[1])
    return {k: round(v, 2) for k, v in rows[:keep]}


def trim_chaos(raw: dict, fmt: str, month: str, cutoff: int) -> dict:
    info = raw.get("info", {})
    pokemon = {}
    for name, entry in raw.get("data", {}).items():
        usage_pct = float(entry.get("usage", 0)) * 100
        if usage_pct < MIN_USAGE_PCT:
            continue
        total = sum(entry.get("Abilities", {}).values()) or float(entry.get("Raw count", 0))
        counters = {}
        for opp, values in (entry.get("Checks and Counters") or {}).items():
            # [number of encounters, P(opponent KOs or forces out this Pokemon), std dev]
            if isinstance(values, list) and len(values) >= 2 and values[0] >= 20:
                counters[opp] = round(values[1] * 100, 1)
        counters = dict(sorted(counters.items(), key=lambda kv: -kv[1])[: KEEP["counters"]])
        teammates = {k: v for k, v in (entry.get("Teammates") or {}).items() if k != name}
        pokemon[name] = {
            "usage": round(usage_pct, 3),
            "raw_count": int(entry.get("Raw count", 0)),
            "abilities": _percentages(entry.get("Abilities", {}), total, KEEP["abilities"]),
            "items": _percentages(entry.get("Items", {}), total, KEEP["items"]),
            "moves": _percentages(entry.get("Moves", {}), total, KEEP["moves"]),
            "spreads": _percentages(entry.get("Spreads", {}), total, KEEP["spreads"]),
            "teammates": _percentages(teammates, total, KEEP["teammates"]),
            "counters": counters,
        }
    pokemon = dict(sorted(pokemon.items(), key=lambda kv: -kv[1]["usage"]))
    return {
        "info": {
            "format": fmt,
            "month": month,
            "cutoff": cutoff,
            "battles": int(info.get("number of battles", 0)),
        },
        "pokemon": pokemon,
    }


class UsageData:
    def __init__(self, trimmed: dict):
        self.info: dict = trimmed["info"]
        self.pokemon: dict = trimmed["pokemon"]
        self._by_id = {to_id(name): name for name in self.pokemon}

    # ---- basic lookups ------------------------------------------------
    def name_of(self, species: str) -> str | None:
        return self._by_id.get(to_id(species))

    def entry(self, species: str) -> dict | None:
        name = self.name_of(species)
        return self.pokemon.get(name) if name else None

    def usage(self, species: str) -> float:
        e = self.entry(species)
        return e["usage"] if e else 0.0

    def ranked(self, n: int | None = None) -> list[tuple[str, float]]:
        rows = [(name, e["usage"]) for name, e in self.pokemon.items()]
        return rows[:n] if n else rows

    def teammate_pct(self, species: str, teammate: str) -> float:
        e = self.entry(species)
        if not e:
            return 0.0
        target = to_id(teammate)
        for name, pct in e["teammates"].items():
            if to_id(name) == target:
                return pct
        return 0.0

    def lift(self, species: str, teammate: str) -> float:
        """How much more often `teammate` appears with `species` than on teams overall."""
        base = self.usage(teammate)
        return self.teammate_pct(species, teammate) / base if base else 0.0

    def section(self, species: str, key: str) -> dict:
        e = self.entry(species)
        return e.get(key, {}) if e else {}

    # ---- team-sheet view (base species + its Mega entries) -------------
    def variants(self, species: str, dex: Dex) -> list[str]:
        """Usage entries that are this Pokemon on a team sheet, most used first."""
        base = dex.get_species(species)
        if base is None:
            return []
        base_id = to_id(base.battle_only[0] if base.battle_only else base.base_species)
        out = []
        for name in self.pokemon:
            s = dex.get_species(name)
            if s is None:
                continue
            root = to_id(s.battle_only[0] if s.battle_only else s.base_species)
            if s.id == base_id or (root == base_id and (s.is_mega or s.battle_only)):
                out.append(name)
        return sorted(out, key=lambda n: -self.pokemon[n]["usage"])

    def species_usage(self, species: str, dex: Dex) -> float:
        return round(sum(self.pokemon[v]["usage"] for v in self.variants(species, dex)), 3)

    def team_sheet_usage(self, dex: Dex) -> dict[str, float]:
        """{base species name: usage incl. its Megas}, highest first."""
        if getattr(self, "_sheet_usage", None) is None:
            totals: dict[str, float] = {}
            for name, entry in self.pokemon.items():
                s = dex.get_species(name)
                if s is None:
                    continue
                base = dex.get_species(s.battle_only[0] if s.battle_only else s.base_species) \
                    if (s.is_mega or s.battle_only) else s
                totals[base.name] = totals.get(base.name, 0.0) + entry["usage"]
            self._sheet_usage = dict(sorted(totals.items(), key=lambda kv: -kv[1]))
        return self._sheet_usage

    def combined_section(self, species: str, key: str, dex: Dex) -> dict:
        """A section averaged over the species' variants, weighted by their usage."""
        names = self.variants(species, dex)
        total = sum(self.pokemon[n]["usage"] for n in names)
        if not total:
            return {}
        merged: dict[str, float] = {}
        for n in names:
            w = self.pokemon[n]["usage"] / total
            for k, v in self.pokemon[n].get(key, {}).items():
                merged[k] = merged.get(k, 0.0) + v * w
        return {k: round(v, 2) for k, v in sorted(merged.items(), key=lambda kv: -kv[1])}

    # ---- sets ----------------------------------------------------------
    def common_item(self, species: str, dex: Dex) -> str:
        for iid in self.section(species, "items"):
            item = dex.get_item(iid)
            if item:
                return item["name"]
        return ""

    def common_moves(self, species: str, dex: Dex, min_pct: float = 0.0) -> list[str]:
        return [
            dex.moves[to_id(m)]["name"]
            for m, pct in self.section(species, "moves").items()
            if pct >= min_pct and to_id(m) in dex.moves
        ]

    def popular_set(self, species: str, dex: Dex, taken_items: set[str] | None = None) -> PokemonSet | None:
        """
        The most common set for a team-sheet Pokemon: built from its most-used
        variant (e.g. Charizard -> Charizard-Mega-Y with Charizardite Y), using
        the top ability, spread and four legal moves, and the most popular item
        that doesn't break Item Clause.
        """
        s = dex.get_species(species)
        if s is None:
            return None
        if s.is_mega or s.battle_only:  # asked for a battle form: build its team-sheet base
            entry_name = self.name_of(s.name) or s.name
            base = dex.get_species(s.battle_only[0] if s.battle_only else s.base_species)
        else:
            variants = self.variants(s.name, dex)
            entry_name, base = (variants[0] if variants else None), s
        if entry_name is None or self.entry(entry_name) is None or base is None:
            return None
        form = dex.get_species(entry_name)
        taken = {to_id(i) for i in (taken_items or set())}

        if form is not None and form.is_mega:
            item = form.required_item or ""
        else:
            item = next((dex.items[to_id(i)]["name"] for i in self.section(entry_name, "items")
                         if to_id(i) in dex.items and to_id(i) not in taken
                         and not dex.mega_stone_species(i)), "")
        legal_abilities = {to_id(a): a for a in base.abilities}
        ability = next((legal_abilities[to_id(a)] for a in self.section(base.name, "abilities")
                        if to_id(a) in legal_abilities), base.abilities[0])
        nature, sps = "Serious", None
        for spread in self.section(entry_name, "spreads"):
            nature, sps = parse_spread(spread)
            break
        moves = [m for m in self.common_moves(entry_name, dex) if dex.can_learn(base.id, m)][:4]
        pset = PokemonSet(species=base.name, item=item, ability=ability, nature=nature, moves=moves)
        if sps:
            pset.sps = sps
        return pset


@lru_cache(maxsize=None)
def load_usage(format_id: str) -> UsageData | None:
    path = USAGE_DIR / f"{format_id}.json"
    if not path.exists():
        return None
    return UsageData(json.loads(path.read_text()))
