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
import math
from functools import lru_cache
from pathlib import Path

from src.dex import Dex, display_name, to_id
from src.stats import parse_spread
from src.team import PokemonSet

USAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "usage"

# How much of each section to keep when trimming (the long tails are noise).
KEEP = {"abilities": 4, "items": 10, "moves": 16, "spreads": 8, "teammates": 30, "counters": 12}
MIN_USAGE_PCT = 0.02  # rating-weighted usage...
MIN_RAW_COUNT = 100   # ...or this many appearances: rare Pokémon (Rotom-Fan) still get their sets


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
        if usage_pct < MIN_USAGE_PCT and int(entry.get("Raw count", 0)) < MIN_RAW_COUNT:
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
        # label the male of a gendered pair "-M" (Meowstic -> Meowstic-M), as the dex does
        self._variant_index: dict = {}
        self._set_cache: dict = {}
        self.cooc = None  # src.cooccurrence.Cooccurrence from tournament teams, when available
        self.teammates = None  # src.synergy.TeammateModel (learned from real teams), when available
        self.sheet_sets = None  # src.sheet_sets: whole sets from real team sheets, when available
        self.recent = None  # set when usage comes from recent replays (see apply_recent)
        self.pokemon: dict = {
            display_name(name): {key: ({display_name(n): v for n, v in sec.items()}
                                       if key in ("teammates", "counters") and isinstance(sec, dict) else sec)
                                 for key, sec in e.items()}
            for name, e in trimmed["pokemon"].items()
        }
        self._by_id = {to_id(name): name for name in self.pokemon}
        # {species id: {teammate id: pct}} so pair lookups are O(1)
        self._mates = {to_id(name): {to_id(m): pct for m, pct in e["teammates"].items()}
                       for name, e in self.pokemon.items()}

    @property
    def from_replays(self) -> bool:
        """Built from replays (src/replay_usage.py) because Smogon has no stats for the format yet."""
        return self.info.get("source") == "replays"

    # ---- basic lookups ------------------------------------------------
    def name_of(self, species: str) -> str | None:
        return self._by_id.get(to_id(species))

    def link_cosmetic(self, dex: Dex) -> None:
        """Cosmetic formes (Vivillon-Pokeball, Alcremie flavors...) are pooled into their base
        species in Smogon's stats: look them up as the base when they have no entry of their own."""
        for s in dex.selectable_species():
            if to_id(s.name) not in self._by_id and dex.is_cosmetic(s):
                base = self._by_id.get(to_id(s.base_species))
                if base:
                    self._by_id[to_id(s.name)] = base

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
        return self._mates.get(to_id(species), {}).get(to_id(teammate), 0.0)

    def lift(self, species: str, teammate: str) -> float:
        """How much more often `teammate` appears with `species` than on teams overall."""
        base = self.usage(teammate)
        return self.teammate_pct(species, teammate) / base if base else 0.0

    def pair_lift(self, a: str, b: str, shrink: float = 200.0) -> tuple[float, bool]:
        """
        Lift of the pair (a, b), shrunk toward 1 when either Pokemon is rare.

        Lift is symmetric in theory (P(a and b) / (P(a) P(b))), so whichever
        direction Smogon kept in its top-30 teammate list is used. If neither
        list has the pair, the true value is below the smallest listed one;
        that bound is returned with known=False.

        Shrinkage: log2(lift) is scaled by n / (n + shrink), where n is the
        smaller raw team count, so a Pokemon seen on a handful of teams can't
        post an extreme lift by luck.
        """
        ea, eb = self.entry(a), self.entry(b)
        if not ea or not eb:
            return 1.0, False
        known = True
        if self.teammate_pct(a, b):
            raw = self.teammate_pct(a, b) / eb.get("smogon_usage", eb["usage"])
        elif self.teammate_pct(b, a):
            raw = self.teammate_pct(b, a) / ea.get("smogon_usage", ea["usage"])
        else:
            known = False
            floor = min(ea["teammates"].values(), default=0.0)
            base_use = eb.get("smogon_usage", eb["usage"])
            raw = min(1.0, floor / base_use) if base_use else 1.0
        raw = max(raw, 0.25)
        n = min(ea.get("raw_count", 0), eb.get("raw_count", 0))
        weight = n / (n + shrink) if n else 0.0
        # Teammate stats are weighted toward the rating cutoff, where a Pokemon on 0.05% of
        # teams is one or two players. Shrink by that usage too, not only all-ratings counts.
        share = min(ea.get("smogon_usage", ea["usage"]), eb.get("smogon_usage", eb["usage"]))
        if USAGE_SHRINK:
            weight *= share / (share + USAGE_SHRINK)
        ladder = math.log2(raw) * weight  # already shrunk toward 0
        if self.cooc is not None:
            # blend in tournament pairings, each source weighted by its confidence
            tour, confidence = self.cooc.log_lift(a, b)
            if weight + confidence > 0:
                blended = (weight * ladder + confidence * tour * confidence) / (weight + confidence)
                return 2 ** blended, known or confidence > 0
        return 2 ** ladder, known

    def section(self, species: str, key: str) -> dict:
        e = self.entry(species)
        return e.get(key, {}) if e else {}

    # ---- team-sheet view (base species + its Mega entries) -------------
    def variants(self, species: str, dex: Dex) -> list[str]:
        """Usage entries that are this Pokemon on a team sheet, most used first."""
        base = dex.get_species(species)
        if base is None:
            return []
        index = self._variant_index.get(id(dex))
        if index is None:  # sheet id -> usage entries, built once per dex
            index = {}
            for name in sorted(self.pokemon, key=lambda n: -self.pokemon[n]["usage"]):
                s = dex.get_species(name)
                if s is not None:
                    index.setdefault(dex.sheet_id(s), []).append(name)
            self._variant_index[id(dex)] = index
        # Arcanine-Hisui stays Arcanine-Hisui, not Arcanine
        return list(index.get(dex.sheet_id(base), []))

    def sibling(self, species: str, dex: Dex) -> str | None:
        """For a forme with no usage entry of its own: the most used entry of a sibling forme with the
        same types and base stats (Squawkabilly-Yellow -> Squawkabilly, Toxtricity-Low-Key ->
        Toxtricity), whose moves, items and spread fit it too. Its ability stays its own."""
        s = dex.get_species(species)
        if s is None or s.is_mega or s.battle_only:
            return None
        family = {s.base_species} | {x.name for x in dex.selectable_species() if x.base_species == s.base_species}
        best = None
        for name in family - {s.name}:
            o = dex.get_species(name)
            if o is None or o.is_mega or o.types != s.types or o.base_stats != s.base_stats:
                continue
            for v in self.variants(name, dex):
                v_s = dex.get_species(v)
                if v != s.name and v_s is not None and not v_s.is_mega and (best is None or self.usage(v) > self.usage(best)):
                    best = v
        return best

    def species_usage(self, species: str, dex: Dex) -> float:
        return round(sum(self.pokemon[v]["usage"] for v in self.variants(species, dex)), 3)

    @staticmethod
    def sheet_name(name: str, dex: Dex) -> str | None:
        """The team-sheet species a usage entry belongs to (a Mega counts as its base)."""
        s = dex.get_species(name)
        if s is None:
            return None
        if s.is_mega or s.battle_only:
            base = dex.get_species(s.battle_only[0] if s.battle_only else s.base_species)
            return base.name if base else s.name
        return s.name

    def is_common(self, name: str, dex: Dex, cutoff: float = 3.0) -> bool:
        """On at least `cutoff`% of ladder teams (Megas count toward their base species)."""
        sheet = self.sheet_name(name, dex)
        return sheet is not None and self.team_sheet_usage(dex).get(sheet, 0.0) >= cutoff

    def apply_recent(self, recent: dict, dex: Dex) -> None:
        """Rescale every Pokemon's usage to its share of recent replay teams, keeping the monthly
        stats' sets and their Mega / base split (team preview doesn't show who Mega Evolves).
        Pokemon not seen recently fall to near zero."""
        old = self.team_sheet_usage(dex)
        share = recent["share"]
        for name, entry in self.pokemon.items():
            base = self.sheet_name(name, dex)
            s = dex.get_species(base) if base else None
            if s is None or not old.get(base):
                continue
            new = 100 * share.get(dex.sheet_id(s), 0.0)
            entry["smogon_usage"] = entry["usage"]  # teammate % in these stats is relative to this
            entry["usage"] = round(entry["usage"] * max(new, 0.01) / old[base], 4)
        self.pokemon = dict(sorted(self.pokemon.items(), key=lambda kv: -kv[1]["usage"]))
        self._sheet_usage = None
        self.recent = {k: v for k, v in recent.items() if k != "share"}

    def team_sheet_usage(self, dex: Dex) -> dict[str, float]:
        """{base species name: usage incl. its Megas}, highest first."""
        if getattr(self, "_sheet_usage", None) is None:
            totals: dict[str, float] = {}
            for name in self.pokemon:
                base = self.sheet_name(name, dex)
                if base is None:
                    continue
                totals[base] = totals.get(base, 0.0) + self.pokemon[name]["usage"]
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

    def popular_set(self, species: str, dex: Dex, taken_items: set[str] | None = None,
                    allow_mega: bool = True, team: list[PokemonSet] | None = None) -> PokemonSet | None:
        """Memoized: see _popular_set, then the moves and nature real team sheets run most when there
        are enough sheets (src/sheet_sets.apply), so every part of the app shows the same set.
        Returns a fresh copy, so callers may edit it."""
        support = None
        if team is not None:  # only what conditional items care about
            triggers = CONDITIONAL_TRIGGERS
            support = frozenset(x for p in team for x in [to_id(p.ability), *map(to_id, p.moves)] if x in triggers)
        key = (id(dex), to_id(species), frozenset(to_id(i) for i in (taken_items or ()) if i),
               allow_mega, support)
        if key not in self._set_cache:
            pset = self._popular_set(species, dex, taken_items, allow_mega, team)
            if pset is not None and self.sheet_sets:  # moves and nature from real team sheets, when enough
                from src.sheet_sets import apply as _sheet_apply
                pset = _sheet_apply(pset, dex, self.sheet_sets)
            self._set_cache[key] = pset
        cached = self._set_cache[key]
        return PokemonSet.from_dict(cached.to_dict()) if cached is not None else None

    def _popular_set(self, species: str, dex: Dex, taken_items: set[str] | None = None,
                     allow_mega: bool = True, team: list[PokemonSet] | None = None) -> PokemonSet | None:
        """
        The most common set for a team-sheet Pokemon: built from its most-used
        variant (e.g. Charizard -> Charizard-Mega-Y with Charizardite Y), using
        the top ability, spread and four legal moves, and the most popular item
        that doesn't break Item Clause. Given the team it joins, items that only
        work with something the team lacks (Psychic Seed without Psychic Terrain,
        Room Service without Trick Room) are skipped. With allow_mega=False (the team already
        has its Mega) the non-Mega variant is used, or the Mega's moves and
        spread with an ordinary item if no non-Mega data exists.
        """
        s = dex.get_species(species)
        if s is None:
            return None
        if s.is_mega or s.battle_only:  # asked for a battle form: build its team-sheet base
            entry_name = self.name_of(s.name) or s.name
            base = dex.get_species(s.battle_only[0] if s.battle_only else s.base_species)
        else:
            variants = self.variants(s.name, dex)
            if not variants and (sib := self.sibling(s.name, dex)):
                variants = [sib]  # a rare forme: its sibling's set, with its own ability and moves
            entry_name, base = (variants[0] if variants else None), s
        if entry_name is None or self.entry(entry_name) is None or base is None:
            return None
        form = dex.get_species(entry_name)
        taken = {to_id(i) for i in (taken_items or set())}
        if not allow_mega and form is not None and form.is_mega:
            plain = [v for v in self.variants(base.name, dex) if not dex.get_species(v).is_mega]
            if plain:
                entry_name, form = plain[0], dex.get_species(plain[0])

        if form is not None and form.is_mega and allow_mega:
            item = form.required_item or ""
        elif form is not None and form.is_mega:
            fallback = ["sitrusberry", "leftovers", "focussash", "lifeorb", "expertbelt", "mentalherb", "covertcloak"]
            item = next((dex.items[i]["name"] for i in fallback if i in dex.items and i not in taken), "")
        else:
            item = None  # chosen below, once the ability and moves are known
        legal_abilities = {to_id(a): a for a in base.abilities}
        ability = next((legal_abilities[to_id(a)] for a in self.section(base.name, "abilities")
                        if to_id(a) in legal_abilities), base.abilities[0])
        nature, sps = "Serious", None
        for spread in self.section(entry_name, "spreads"):
            nature, sps = parse_spread(spread)
            break
        moves = [m for m in self.common_moves(entry_name, dex) if dex.can_learn(base.id, m)][:4]
        if item is None:
            if team is not None:
                own = (to_id(ability), {to_id(m) for m in moves})
                support = [own] + [(to_id(p.ability), {to_id(m) for m in p.moves}) for p in team]
            move_ids = [to_id(m) for m in moves]
            item = next((dex.items[to_id(i)]["name"] for i in self.section(entry_name, "items")
                         if to_id(i) in dex.items and to_id(i) not in taken
                         and not dex.mega_stone_species(i)
                         and item_fits_moves(to_id(i), move_ids, dex)
                         and (team is None or item_has_support(to_id(i), support, own))), "")
        pset = PokemonSet(species=base.name, item=item, ability=ability, nature=nature, moves=moves)
        if sps:
            pset.sps = sps
        return pset


def typical_spread(usage: "UsageData", pset: PokemonSet, dex: Dex) -> dict | None:
    """The most common ladder spread for this Pokemon (its Mega entry if it holds the stone),
    preferring one with the set's nature. For team lists that don't publish stat points."""
    form = pset.battle_form(dex)
    entry = form.name if usage.entry(form.name) else pset.species
    fallback = None
    for spread in usage.section(entry, "spreads"):
        nature, sps = parse_spread(spread)
        if not sps:
            continue
        if to_id(nature) == to_id(pset.nature):
            return sps
        fallback = fallback or sps
    return fallback


# usage % at which pair lift keeps half its strength (see pair_lift); 0 turns it off
USAGE_SHRINK = 0.3


# Items that only do something when the team provides a condition:
# item -> (abilities that provide it, moves that provide it, must the holder provide it itself?)
CONDITIONAL_ITEMS = {
    "psychicseed": ({"psychicsurge"}, {"psychicterrain"}, False),
    "grassyseed": ({"grassysurge"}, {"grassyterrain"}, False),
    "electricseed": ({"electricsurge", "hadronengine"}, {"electricterrain"}, False),
    "mistyseed": ({"mistysurge"}, {"mistyterrain"}, False),
    "roomservice": (set(), {"trickroom"}, False),
    "damprock": ({"drizzle"}, {"raindance"}, True),
    "heatrock": ({"drought"}, {"sunnyday"}, True),
    "smoothrock": ({"sandstream"}, {"sandstorm"}, True),
    "icyrock": ({"snowwarning"}, {"snowscape", "chillyreception"}, True),
    "terrainextender": ({"psychicsurge", "grassysurge", "electricsurge", "mistysurge"},
                        {"psychicterrain", "grassyterrain", "electricterrain", "mistyterrain"}, True),
}


CONDITIONAL_TRIGGERS = frozenset(x for abilities, moves, _ in CONDITIONAL_ITEMS.values()
                                 for x in (*abilities, *moves))


# Status moves that real Choice-item sets carry (Bo3 open sheets, Reg M-C: Trick 97% of its sheets
# are on a Choice item, Soak 76%, Transform 43%, After You 25%, Fake Tears 13%, Skill Swap 10%);
# every other status move almost never is (Protect 0.5%, Parting Shot 0.3%, Tailwind 0.7%,
# Trick Room 1.4%). Assault Vest can't use status moves at all.
CHOICE_ITEMS = frozenset({"choicescarf", "choiceband", "choicespecs"})
CHOICE_STATUS_OK = frozenset({"trick", "switcheroo", "soak", "transform", "afteryou", "faketears", "skillswap"})


def item_fits_moves(item_id: str, move_ids, dex: Dex) -> bool:
    """False for a Choice item with a status move players don't pair with one (Choice Scarf with
    Protect), or Assault Vest with any status move."""
    status = [m for m in move_ids if m in dex.moves and dex.moves[m]["category"] == "Status"]
    if item_id == "assaultvest":
        return not status
    if item_id in CHOICE_ITEMS:
        return all(m in CHOICE_STATUS_OK for m in status)
    return True


def item_has_support(item_id: str, team: list[tuple[str, set[str]]], own: tuple[str, set[str]]) -> bool:
    """team / own: (ability id, move ids). True unless the item needs something nobody provides."""
    rule = CONDITIONAL_ITEMS.get(item_id)
    if rule is None:
        return True
    abilities, moves, self_only = rule
    holders = [own] if self_only else team
    return any(a in abilities or ms & moves for a, ms in holders)


def _before_start(path: Path, format_id: str) -> bool:
    """Smogon stats from a month before the format officially started (a few pre-release games)."""
    from src.formats import FORMATS as _FORMATS
    fmt = _FORMATS.get(format_id)
    if fmt is None or not fmt.start:
        return False
    try:
        month = json.loads(path.read_text())["info"]["month"]
    except (OSError, ValueError, KeyError):
        return False
    return month < fmt.start[:7]


@lru_cache(maxsize=None)
def load_usage(format_id: str, tournament_pairs: bool = True, recent: bool = True) -> UsageData | None:
    """Ladder usage for a format. For doubles formats with tournament team lists on disk,
    synergy also draws on those lists' pairings (see src/cooccurrence.py)."""
    path = USAGE_DIR / f"{format_id}.json"
    if not path.exists() or _before_start(path, format_id):
        # a new regulation before Smogon's first monthly stats: usage built from its replays
        from src.replay_usage import load as _load_replay_usage
        usage = _load_replay_usage(format_id)
        if usage is None:
            return None
    else:
        usage = UsageData(json.loads(path.read_text()))
    from src.formats import FORMATS as _FORMATS  # local: formats imports nothing heavy, but keep load order
    if format_id in _FORMATS:
        from src.dex import load_dex as _load_dex
        usage.link_cosmetic(_load_dex(_FORMATS[format_id].regulation))
        # current meta: usage from the last two weeks of replays, when there are enough
        recent_path = Path(__file__).resolve().parent.parent / "data" / "replays" / "summary" / \
            f"{format_id}_recent_usage.json"
        if recent and recent_path.exists() and not usage.from_replays:
            try:
                usage.apply_recent(json.loads(recent_path.read_text()), _load_dex(_FORMATS[format_id].regulation))
            except (OSError, ValueError, KeyError):
                pass
    if recent:  # whole sets from real team sheets, for the builder (src/sheet_sets.py)
        from src.sheet_sets import load as _load_sheets
        usage.sheet_sets = _load_sheets(format_id)
    if tournament_pairs:
        from src.cooccurrence import Cooccurrence  # local imports: these modules import this one
        from src.dex import load_dex
        from src.evaluate import load_tournament_teams
        from src.formats import FORMATS
        fmt = FORMATS.get(format_id)
        if fmt is not None and fmt.is_doubles:
            dex = load_dex(fmt.regulation)
            teams = load_tournament_teams(fmt.regulation, dex)
            if teams:
                usage.cooc = Cooccurrence([t["sets"] for t in teams], dex)
            from src.synergy import load_model as _load_teammates
            model = _load_teammates(fmt.regulation)
            if model is not None and format_id in model.formats:
                usage.teammates = model
    return usage
