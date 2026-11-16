"""
replays.py

What real players do in battle, from parsed Showdown replays
(scripts/fetch_replays.py -> data/replays/<format>/<day>.jsonl.gz).

- species_stats: for each Pokemon, how often it's brought when it's on team
  preview, how often it leads, its win rate when brought, how often it Mega
  Evolves, and its most common turn-1 moves.
- check_game_plans: does the Matchups tab's game plan predict what players
  actually bring and lead? Each side's team is rebuilt from its preview (the
  Bo3 format's open team sheets give exact sets; otherwise each Pokemon gets its
  most popular ladder set), the bring-4 and lead pair are predicted against the
  opponent's six, and compared with what that player really brought and led.
  Baselines: a random pick, and "the Pokemon players bring / lead most often"
  measured on older replays only.

Only finished games with both team previews count (replay_parse.is_usable).
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
import random
from collections import Counter, defaultdict
from pathlib import Path

from src.dex import Dex, to_id
from src.replay_parse import PLAYERS, is_usable

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data" / "replays"


def load_records(fmt: str, min_rating: int = 0, days: int | None = None) -> list[dict]:
    """Usable records for a format, oldest first; min_rating filters on the lower player rating
    (unrated games count as 0)."""
    folder = REPLAY_DIR / fmt
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.jsonl.gz"))
    if days:
        files = files[-days:]
    out = []
    for path in files:
        with gzip.open(path, "rt") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if not is_usable(rec):
                    continue
                if min_rating and min((rec["players"][p]["rating"] or 0) for p in PLAYERS) < min_rating:
                    continue
                out.append(rec)
    return sorted(out, key=lambda r: r["uploadtime"] or 0)


def species_stats(records: list[dict], min_previews: int = 30) -> list[dict]:
    seen = Counter()
    brought = Counter()
    led = Counter()
    won_brought = Counter()
    mega = Counter()
    turn1: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        for p in PLAYERS:
            win = rec["winner"] == p
            mega_base = (rec["mega"][p] or "").replace("-Mega-X", "").replace("-Mega-Y", "").replace("-Mega", "")
            for s in set(rec["preview"][p]):
                seen[s] += 1
            for s in set(rec["brought"][p]):
                brought[s] += 1
                won_brought[s] += win
            for s in set(rec["leads"][p]):
                led[s] += 1
            if mega_base:
                mega[mega_base] += 1
            for species, move, _target in rec["turn1"][p]:
                turn1[species][move] += 1
    rows = []
    for s, n in seen.items():
        if n < min_previews:
            continue
        top = turn1[s].most_common(3)
        total1 = sum(turn1[s].values())
        rows.append({
            "pokemon": s, "previews": n,
            "brought %": brought[s] / n, "leads %": led[s] / n,
            "win % when brought": won_brought[s] / brought[s] if brought[s] else None,
            "mega %": mega[s] / brought[s] if brought[s] else 0.0,
            "turn 1": ", ".join(f"{m} {c / total1:.0%}" for m, c in top) if total1 else "",
        })
    return sorted(rows, key=lambda r: -r["previews"])


# --------------------------------------------------------------------------
# Does the game plan predict real bring / lead choices?
# --------------------------------------------------------------------------
def _sets_for(rec: dict, p: str, dex: Dex, usage) -> list:
    from src.team import PokemonSet
    sheet = rec.get("sheets", {}).get(p)
    if sheet:  # Bo3: open team sheets give the real sets
        sets = []
        for e in sheet:
            sp = dex.get_species(e["species"])
            if sp is None:
                continue
            item = dex.items.get(to_id(e["item"]), {}).get("name", "") if e["item"] else ""
            ability = next((a for a in sp.abilities if to_id(a) == to_id(e["ability"])), e["ability"])
            moves = [dex.moves[to_id(m)]["name"] for m in e["moves"] if to_id(m) in dex.moves]
            sets.append(PokemonSet(species=sp.name, item=item, ability=ability, moves=moves))
        return sets
    sets, taken = [], set()
    for name in rec["preview"][p]:
        pset = usage.popular_set(name, dex, taken_items=taken, team=list(sets))
        if pset is not None:
            sets.append(pset)
            taken.add(pset.item)
    return sets


def check_game_plans(records: list[dict], dex: Dex, usage, test_share: float = 0.5,
                     max_games: int | None = 3000, seed: int = 0) -> dict:
    """Overlap of predicted vs real bring-4 and lead pair, against baselines fitted on the
    older replays (the first 1 - test_share of them)."""
    from src.analysis import build_members
    from src.gameplan import game_plan
    from src.matchup import best_bring, pair_matrix

    cut = int(len(records) * (1 - test_share))
    past, test = records[:cut], records[cut:]
    if max_games and len(test) > max_games:
        test = random.Random(seed).sample(test, max_games)
    # baselines from older replays: each Pokemon's bring and lead rate when on preview
    stats = {r["pokemon"]: r for r in species_stats(past, min_previews=1)}

    def rate(s, key):
        return stats[s][key] if s in stats else 0.0

    totals = Counter()
    for rec in test:
        for p, q in (("p1", "p2"), ("p2", "p1")):
            real_bring = set(rec["brought"][p])
            real_lead = set(rec["leads"][p])
            if len(real_bring) < 3 or len(real_lead) < 2:
                continue  # games that ended before most of the team came out say little
            mine, theirs = _sets_for(rec, p, dex, usage), _sets_for(rec, q, dex, usage)
            if len(mine) < 5 or len(theirs) < 4:
                continue
            ma, mb = build_members(mine, dex, evolve=None), build_members(theirs, dex, evolve=None)
            label = {m.label: rec["preview"][p][i] if i < len(rec["preview"][p]) else m.label
                     for i, m in enumerate(ma)}
            matrix = pair_matrix(ma, mb)
            picks, _ = best_bring(matrix, 4)
            plan = game_plan(ma, mb, matrix, picks, dex)
            ours_bring = {label.get(x, x) for x in picks}
            ours_lead = {label.get(x, x) for x in plan.lead}
            preview = list(dict.fromkeys(rec["preview"][p]))
            pop_bring = set(sorted(preview, key=lambda s: -rate(s, "brought %"))[:4])
            pop_lead = set(sorted(preview, key=lambda s: -rate(s, "leads %"))[:2])
            rnd = random.Random(hash((rec["id"], p)) & 0xFFFF)
            rnd_bring, rnd_lead = set(rnd.sample(preview, 4)), set(rnd.sample(preview, 2))
            totals["games"] += 1
            for name, guess in (("game plan", ours_bring), ("most-brought", pop_bring), ("random", rnd_bring)):
                totals[f"bring {name}"] += len(guess & real_bring) / len(real_bring)
            for name, guess in (("game plan", ours_lead), ("most-led", pop_lead), ("random", rnd_lead)):
                totals[f"lead {name}"] += len(guess & real_lead) / 2
                totals[f"lead exact {name}"] += guess == real_lead
    n = totals.pop("games", 0)
    return {"games": n, **{k: round(v / n, 4) for k, v in totals.items()}} if n else {"games": 0}


RECENT_DAYS = 14      # "current meta" window: tested best at predicting the next week's usage
RECENT_MIN_RATING = 1300


def recent_usage(records: list[dict], dex, days: int = RECENT_DAYS,
                 min_rating: int = RECENT_MIN_RATING) -> dict | None:
    """Share of teams each Pokemon is on (team-sheet id -> 0..1) over the last `days` of
    replays, from players rated min_rating+, each player's team counted once. On the next
    week's ladder and tournament teams this beat last month's Smogon stats (top-30 usage
    error 0.85 vs 2.09 points on ladder, 2.43 vs 3.13 on tournaments)."""
    from src.synergy import root_of
    stamped = [r for r in records if r.get("uploadtime")]
    if not stamped:
        return None
    end = max(r["uploadtime"] for r in stamped)
    start = end - days * 86400
    counts: dict[str, int] = {}
    seen = set()
    for r in stamped:
        if r["uploadtime"] < start:
            continue
        for p in ("p1", "p2"):
            if (r["players"][p]["rating"] or 0) < min_rating:
                continue
            roots = frozenset(x for sp in r["preview"][p] if (x := root_of(sp, dex)))
            key = (r["players"][p]["name"].lower(), roots)
            if len(roots) < 4 or key in seen:
                continue
            seen.add(key)
            for x in roots:
                counts[x] = counts.get(x, 0) + 1
    if len(seen) < 500:  # too few teams to trust over the monthly stats
        return None
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    return {"teams": len(seen), "first_day": day(start), "last_day": day(end), "min_rating": min_rating,
            "share": {k: round(v / len(seen), 5) for k, v in sorted(counts.items(), key=lambda x: -x[1])}}


def day_range(first: str, last: str) -> str:
    """'2026-11-01', '2026-11-15' -> 'Nov 1–15' (or 'Oct 25 – Nov 8')."""
    a, b = (datetime.strptime(d, "%Y-%m-%d") for d in (first, last))
    if a.month == b.month:
        return f"{a:%b} {a.day}–{b.day}"
    return f"{a:%b} {a.day} – {b:%b} {b.day}"


def load_summary(format_id: str) -> dict | None:
    """Per-Pokemon replay stats for a format and its Bo3 twin, merged (weighted by previews),
    keyed by species id. From scripts/summarize_replays.py."""
    rows, games, days = {}, 0, []
    for fmt in (format_id, format_id + "bo3"):
        path = REPLAY_DIR / "summary" / f"{fmt}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        games += data["games"]
        days += [data["first_day"], data["last_day"]]
        for r in data["pokemon"]:
            key = to_id(r["pokemon"])
            if key not in rows:
                rows[key] = {**r}
                continue
            a, n_a, n_b = rows[key], rows[key]["previews"], r["previews"]
            for k in ("brought %", "leads %", "mega %"):
                a[k] = (a[k] * n_a + r[k] * n_b) / (n_a + n_b)
            if r.get("win % when brought") is not None and a.get("win % when brought") is not None:
                a["win % when brought"] = (a["win % when brought"] * n_a + r["win % when brought"] * n_b) / (n_a + n_b)
            if n_b > n_a:
                a["turn 1"] = r["turn 1"]
            a["previews"] = n_a + n_b
    if not rows:
        return None
    return {"games": games, "from": min(days), "to": max(days), "pokemon": rows}


def usual_picks(summary: dict, species: list[str]) -> tuple[list[str], list[str]]:
    """The four players bring most and the two they lead with most, among these Pokemon."""
    rate = lambda s, k: summary["pokemon"].get(to_id(s), {}).get(k, 0.0)  # noqa: E731
    bring = sorted(species, key=lambda s: -rate(s, "brought %"))[:4]
    lead = sorted(bring, key=lambda s: -rate(s, "leads %"))[:2]
    return bring, lead
