"""
replay_usage.py

Usage stats built from replays alone, in the same shape as a Smogon stats file
(src/usage.py's trimmed format), for the first weeks of a new regulation:
Smogon publishes a month's stats a few days after it ends, so a regulation that
starts on Dec 3 has none until early January, while replays arrive twice a day
from the first day.

From each unique player team (name + six, counted once):
- usage: share of teams with the Pokémon (team preview), split between the base
  form and its Megas by how often the Pokémon Mega Evolved when brought
- teammates: share of its teams that also have each other Pokémon
- moves, items, abilities: from open team sheets (Bo3) when there are enough;
  otherwise the previous regulation's stats for that Pokémon if it was there;
  otherwise the moves players were seen using
- spreads: the previous regulation's, when it had the Pokémon (sheets don't show them)

    usage_from_replays(records, dex, "gen9championsvgc2026regmd", prev=load_usage(<last reg>))
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from src.dex import Dex, to_id
from src.usage import KEEP

MIN_TEAMS = 200   # fewer unique teams than this: not enough to stand in for monthly stats
MIN_SHEETS = 10   # open sheets needed before a Pokémon's moves / items come from sheets
PLAYERS = ("p1", "p2")


def _pct(counter: Counter, total: float, keep: int) -> dict:
    if not total:
        return {}
    return {k: round(100 * v / total, 2) for k, v in counter.most_common(keep)}


def _mega_base(name: str) -> str:
    for suffix in ("-Mega-X", "-Mega-Y", "-Mega-Z", "-Mega"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def usage_from_replays(records: list[dict], dex: Dex, format_id: str, prev=None,
                       min_rating: int = 0, min_teams: int = MIN_TEAMS) -> dict | None:
    """A trimmed usage dict (UsageData(...) accepts it) from replay records, or None when there
    are fewer than min_teams unique teams. prev: the previous regulation's UsageData, for the sets
    of Pokémon that carry over."""
    teams: dict[tuple, list[str]] = {}
    megas: dict[tuple, set[str]] = defaultdict(set)      # team -> Mega formes it used
    brought: dict[tuple, set[str]] = defaultdict(set)    # team -> Pokémon it brought at least once
    seen_moves: dict[tuple, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    sheets: dict[tuple, dict] = {}                       # (player, species) -> latest sheet
    stamped = [r["uploadtime"] for r in records if r.get("uploadtime")]
    for rec in records:
        for p in PLAYERS:
            if (rec["players"][p]["rating"] or 0) < min_rating:
                continue
            preview = [s for s in rec["preview"][p] if dex.get_species(s)]
            if len(preview) < 4:
                continue
            player = rec["players"][p]["name"].lower()
            key = (player, frozenset(preview))
            teams.setdefault(key, preview)
            brought[key].update(rec["brought"][p])
            if rec["mega"][p]:
                megas[key].add(rec["mega"][p])
            for species, moves in (rec.get("moves") or {}).get(p, {}).items():
                seen_moves[key][_mega_base(species)].update(to_id(m) for m in moves)
            for sheet in (rec.get("sheets") or {}).get(p) or []:
                sheets[(player, sheet["species"])] = sheet
    if len(teams) < min_teams:
        return None

    n = len(teams)
    on = Counter()                      # teams with the Pokémon
    pairs: dict[str, Counter] = defaultdict(Counter)
    brought_n = Counter()               # teams that brought it at least once
    mega_n: dict[str, Counter] = defaultdict(Counter)  # base -> Mega forme -> teams
    revealed: dict[str, Counter] = defaultdict(Counter)
    for key, preview in teams.items():
        names = set(preview)
        for s in names:
            on[s] += 1
            for t in names - {s}:
                pairs[s][t] += 1
            if s in brought[key]:
                brought_n[s] += 1
            for m in seen_moves[key].get(s, ()):
                revealed[s][m] += 1
        for forme in megas[key]:
            mega_n[_mega_base(forme)][forme] += 1

    by_species: dict[str, list[dict]] = defaultdict(list)
    for (_player, species), sheet in sheets.items():
        by_species[species].append(sheet)

    def sets_from_sheets(rows: list[dict]) -> dict:
        k = len(rows)
        return {"moves": _pct(Counter(to_id(m) for r in rows for m in r.get("moves", [])), k, KEEP["moves"]),
                "items": _pct(Counter(to_id(r.get("item", "")) for r in rows if r.get("item")), k, KEEP["items"]),
                "abilities": _pct(Counter(to_id(r.get("ability", "")) for r in rows if r.get("ability")), k,
                                  KEEP["abilities"])}

    def prev_entry(name: str) -> dict | None:
        return prev.entry(name) if prev is not None else None

    pokemon: dict[str, dict] = {}
    for base, count in on.items():
        share = 100 * count / n
        rate = {f: c / max(brought_n[base], 1) for f, c in mega_n[base].items()}
        rate_total = min(sum(rate.values()), 1.0)
        mates = _pct(pairs[base], count, KEEP["teammates"])
        rows = by_species.get(base, [])
        for forme, part in [(base, 1.0 - rate_total)] + sorted(rate.items(), key=lambda kv: -kv[1]):
            if part <= 0 and forme != base:
                continue
            species = dex.get_species(forme)
            if species is None:
                continue
            stone = to_id(species.required_item or "")
            forme_rows = [r for r in rows if (to_id(r.get("item", "")) == stone) == bool(stone)] if rows else []
            old = prev_entry(forme)
            if len(forme_rows) >= MIN_SHEETS:
                sets, source = sets_from_sheets(forme_rows), "sheets"
            elif old is not None:
                sets, source = {k: dict(old.get(k, {})) for k in ("moves", "items", "abilities")}, "previous"
            else:
                sets = {"moves": _pct(revealed[base], max(brought_n[base], 1), KEEP["moves"]),
                        "items": {stone: 100.0} if stone else {},
                        "abilities": {to_id(species.abilities[0]): 100.0} if species.abilities else {}}
                source = "seen"
            pokemon[forme] = {
                "usage": round(share * max(part, 0.0), 3),
                "raw_count": round(count * max(part, 0.0)),
                **sets,
                "spreads": dict(old.get("spreads", {})) if old else {},
                "teammates": mates,
                "counters": {},
                "set_source": source,
            }
    pokemon = dict(sorted(pokemon.items(), key=lambda kv: -kv[1]["usage"]))
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    return {"info": {"format": format_id, "month": "replays", "source": "replays", "cutoff": min_rating,
                     "battles": len(records), "teams": n,
                     "first_day": day(min(stamped)) if stamped else "", "last_day": day(max(stamped)) if stamped else ""},
            "pokemon": pokemon}


# --------------------------------------------------------------------------
# Saved by scripts/summarize_replays.py; read by src/usage.py's load_usage when the
# format has no Smogon stats yet.
# --------------------------------------------------------------------------
REPLAY_USAGE_DAYS = 7  # set by labs/new_regulation_lab.py


def path_for(format_id: str):
    from src.replays import REPLAY_DIR
    return REPLAY_DIR / "summary" / f"{format_id}_replay_usage.json"


def build_for(fmt, records: list[dict], dex: Dex, days: int = REPLAY_USAGE_DAYS) -> dict | None:
    """Replay usage for an app format from its last `days` of replays, with the previous
    regulation's sets for Pokémon that carry over."""
    import json
    from src.synergy import recent_records
    from src.usage import USAGE_DIR, UsageData
    prev = None
    prev_path = USAGE_DIR / f"{fmt.previous}.json" if fmt.previous else None
    if prev_path is not None and prev_path.exists():
        prev = UsageData(json.loads(prev_path.read_text()))
    return usage_from_replays(recent_records(records, days=days), dex, fmt.id, prev=prev)


def save(data: dict, format_id: str) -> None:
    import json
    path_for(format_id).write_text(json.dumps(data, separators=(",", ":")))


def load(format_id: str):
    """A UsageData from the saved replay usage, or None. Its `recent` is set like apply_recent's
    so the app's 'meta from replays ...' labels read the same."""
    import json
    from src.usage import UsageData
    path = path_for(format_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        usage = UsageData(data)
    except (OSError, ValueError, KeyError):
        return None
    info = data["info"]
    usage.recent = {"teams": info["teams"], "first_day": info["first_day"], "last_day": info["last_day"],
                    "min_rating": info.get("cutoff", 0)}
    return usage
