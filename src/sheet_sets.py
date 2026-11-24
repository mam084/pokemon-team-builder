"""
sheet_sets.py

Sets from real team sheets: Bo3 open team sheets (replays) and tournament team lists (Limitless).
Smogon's ladder stats count each move on its own; a sheet is a whole set someone ran. Keyed by the
Pokemon as written on a team sheet and whether it holds its Mega Stone, since a Mega and a non-Mega
Feraligatr play differently. Each player's set counts once (a ladder player's 40 games are one set).

labs/sheet_set_lab.py tests these against the ladder sets on held-out tournament sheets.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dex import Dex, to_id

SUMMARY_DIR = Path(__file__).resolve().parent.parent / "data" / "replays" / "summary"


def _stones(dex: Dex) -> set[str]:
    return {to_id(s.required_item) for s in dex.species.values() if s.is_mega and s.required_item}


def sheet_key(pset, dex: Dex, stones: set[str] | None = None) -> tuple[str, bool]:
    stones = stones if stones is not None else _stones(dex)
    s = dex.get_species(pset.species)
    root = dex.sheet_id(s) if s is not None else to_id(pset.species)
    return root, to_id(pset.item or "") in stones


def sheet_sets_from(tournament_teams: list[dict], bo3_records: list[dict], dex: Dex, end: str | None = None,
                    days: int | None = 30) -> dict:
    """{(sheet id, holds Mega Stone): {n, top4, mode, mode_n, items, nature, nature_n}}, from sheets
    dated before `end` (default: no limit) and within `days` of it (None: all)."""
    stones = _stones(dex)
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end else None
    start_dt = (end_dt - timedelta(days=days)) if (end_dt and days) else None
    if end_dt is None and days:
        stamps = [r["uploadtime"] for r in bo3_records if r.get("uploadtime")]
        if stamps:
            start_dt = datetime.fromtimestamp(max(stamps), timezone.utc) - timedelta(days=days)
    sets: dict[tuple, Counter] = {}
    seen = set()

    def add(key, moves, item, nature, who):
        ident = (who, key, moves)
        if len(moves) != 4 or ident in seen:
            return
        seen.add(ident)
        e = sets.setdefault(key, {"moves": Counter(), "combos": Counter(), "items": Counter(), "natures": Counter()})
        e["moves"].update(moves)
        e["combos"][moves] += 1
        if item:
            e["items"][to_id(item)] += 1
        if nature:
            e["natures"][nature] += 1

    for t in tournament_teams:
        d = datetime.strptime(t["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if (end_dt and d >= end_dt) or (start_dt and d < start_dt):
            continue
        for p in t["sets"]:
            moves = frozenset(to_id(m) for m in p.moves if to_id(m) in dex.moves)
            add(sheet_key(p, dex, stones), moves, p.item, p.nature, ("t", t.get("player"), t.get("tournament")))
    for r in bo3_records:
        ts = r.get("uploadtime") or 0
        d = datetime.fromtimestamp(ts, timezone.utc)
        if (end_dt and d >= end_dt) or (start_dt and d < start_dt):
            continue
        for side, sheet in (r.get("sheets") or {}).items():
            who = ("b", (r["players"][side].get("name") or "").lower())
            for mon in sheet or []:
                s = dex.get_species(mon["species"])
                if s is None:
                    continue
                moves = frozenset(to_id(m) for m in mon.get("moves") or [] if to_id(m) in dex.moves)
                item = mon.get("item") or ""
                key = (dex.sheet_id(s), to_id(item) in stones)
                add(key, moves, item, None, who)
    out = {}
    for key, e in sets.items():
        n = sum(e["combos"].values())
        mode, mode_n = e["combos"].most_common(1)[0]
        nat = e["natures"].most_common(1)
        out[key] = {"n": n, "top4": [m for m, _ in e["moves"].most_common(4)], "mode": sorted(mode),
                    "moves": {m: round(c / n, 3) for m, c in e["moves"].most_common(8)},
                    "mode_n": mode_n, "items": {i: c / n for i, c in e["items"].most_common(3)},
                    "nature": nat[0][0] if nat else None, "nature_n": sum(e["natures"].values())}
    return out


MIN_SHEETS = 10                      # fewer sheets than this: keep the ladder set
MODE_SHARE = 0.4   # whole set only when this share of sheets run it (labs/sheet_set_lab.py)
MIN_NATURES = 5                      # tournament sheets with a nature before it replaces the ladder's


def apply(pset, dex: Dex, sets: dict | None):
    """The set with the moves (and nature) real sheets run most, when there are enough of them.
    Held-out tournament sheets (labs/sheet_set_lab.py, 12,027 sets): +0.063 matching moves per set
    (95% +0.054 to +0.072) with the whole-set-at-40% rule, against +0.025 for always the most common
    whole set, and natures right 67.7% vs 62.5% of the time, against the ladder's popular set.
    The item stays (it was picked for Item Clause); the moves must fit it (usage.item_fits_moves)."""
    if not sets:
        return pset
    s = sets.get(sheet_key(pset, dex))
    if s is None or s["n"] < MIN_SHEETS:
        return pset
    from src.team import PokemonSet
    out = PokemonSet.from_dict(pset.to_dict())
    species = dex.get_species(pset.species)
    # the most common whole set when 40%+ of sheets share it, else the four moves most often on them
    pick = s["mode"] if s.get("mode_n", 0) >= MODE_SHARE * s["n"] else s["top4"]
    moves = [m for m in pick if m in dex.moves and dex.can_learn(species.id, m)]
    from src.usage import item_fits_moves
    if len(moves) == 4 and item_fits_moves(to_id(pset.item or ""), moves, dex):
        order = {to_id(m): i for i, m in enumerate(pset.moves)}   # keep the ladder set's order where shared
        moves.sort(key=lambda m: order.get(m, 9))
        out.moves = [dex.moves[m]["name"] for m in moves]
    if s.get("nature") and s.get("nature_n", 0) >= MIN_NATURES and dex.get_nature(s["nature"]):
        out.nature = s["nature"]
    return out


def save(sets: dict, format_id: str) -> Path:
    path = SUMMARY_DIR / f"{format_id}_sheet_sets.json"
    path.write_text(json.dumps({f"{k[0]}|{int(k[1])}": v for k, v in sets.items()}, separators=(",", ":")))
    return path


def load(format_id: str) -> dict | None:
    path = SUMMARY_DIR / f"{format_id}_sheet_sets.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return {(k.split("|")[0], k.split("|")[1] == "1"): v for k, v in raw.items()}


__all__ = ["sheet_key", "sheet_sets_from", "apply", "save", "load"]
