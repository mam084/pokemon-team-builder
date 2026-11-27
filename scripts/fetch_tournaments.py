"""
fetch_tournaments.py

Downloads real tournament team lists for Champions regulations from the
Limitless tournament platform's public API (play.limitlesstcg.com/api) and
saves them to data/tournaments/<regulation>.json.

These are used to *evaluate* the recommender against teams real players
brought (see src/evaluate.py), and the match results (pairings) to check that
the team-vs-team matchup score predicts who wins (src/validate.py).

Writes data/tournaments/<regulation>.json (teams, with player id, placing and
record) and data/tournaments/<regulation>_matches.json (one row per match).

Usage:
    python scripts/fetch_tournaments.py                  # every regulation in REGULATIONS
    python scripts/fetch_tournaments.py --min-players 32 --days 60

Keeps every tournament from the last DAYS days (30, the same window as the sheet sets, the teammate
model and the Pokémon tab), up to --max-tournaments as a safety cap. It used to keep the newest 120
tournaments, which on a busy regulation reached back only ~19 days.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tournaments"
API = "https://play.limitlesstcg.com/api"

# our regulation key -> Limitless VGC format id (only the current regulation is
# evaluated; add older ones here if needed)
sys.path.insert(0, str(ROOT))
from src.formats import FORMATS  # noqa: E402

REGULATIONS = {f.regulation: f.limitless for f in FORMATS.values() if f.current and f.limitless}
DAYS = 30          # keep tournaments from this many days back (from today)
MAX_TOURNAMENTS = 600   # safety cap on requests
DELAY = 1.0  # seconds between requests; the API is free, so stay well under its rate limit


def get(path: str, **params):
    for attempt in range(4):
        time.sleep(DELAY)
        response = requests.get(f"{API}{path}", params=params, timeout=30)
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After") or 10 * (attempt + 1))
            print(f"  rate limited, waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    response.raise_for_status()


def list_tournaments(fmt: str, min_players: int, max_tournaments: int, days: int | None = DAYS) -> list[dict]:
    """Tournaments in this format with min_players+, newest first, dated within `days` of today."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d") if days else ""
    found, page = [], 1
    while len(found) < max_tournaments:
        batch = get("/tournaments", game="VGC", format=fmt, limit=100, page=page)
        if not batch or (found and batch[-1].get("id") == found[-1].get("id")):
            break  # empty page, or the API ignored `page` and repeated itself
        found += [t for t in batch if t.get("format") == fmt and (t.get("players") or 0) >= min_players
                  and (t.get("date") or "")[:10] >= cutoff]
        page += 1
        if page > 50 or (cutoff and all((t.get("date") or "")[:10] < cutoff for t in batch)):
            break  # past the window
    return found[:max_tournaments]


def clean_team(decklist) -> list[dict] | None:
    if not isinstance(decklist, list) or len(decklist) != 6:
        return None
    team = []
    for mon in decklist:
        if not isinstance(mon, dict) or not mon.get("name"):
            return None
        team.append({
            "species": mon["name"],
            "item": mon.get("item") or "",
            "ability": mon.get("ability") or "",
            "nature": mon.get("nature") or "",
            "moves": [m for m in (mon.get("attacks") or []) if m][:4],
        })
    return team


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-players", type=int, default=16)
    parser.add_argument("--days", type=int, default=DAYS, help="keep tournaments from the last N days (0: no limit)")
    parser.add_argument("--max-tournaments", type=int, default=MAX_TOURNAMENTS)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for reg, fmt in REGULATIONS.items():
        tournaments = list_tournaments(fmt, args.min_players, args.max_tournaments, args.days or None)
        teams, matches = [], []
        for n, t in enumerate(tournaments, 1):
            if n % 25 == 0:
                print(f"  {reg}: {n}/{len(tournaments)} tournaments, {len(teams)} teams so far", flush=True)
            try:
                standings = get(f"/tournaments/{t['id']}/standings")
            except requests.HTTPError as err:
                print(f"  skip {t['id']}: {err}")
                continue
            for row in standings or []:
                team = clean_team(row.get("decklist"))
                if team is None:
                    continue
                record = row.get("record") or {}
                teams.append({
                    "tournament": t["id"],
                    "player": str(row.get("player") or row.get("name") or ""),
                    "date": (t.get("date") or "")[:10],
                    "players": t.get("players"),
                    "placing": row.get("placing"),
                    "wins": record.get("wins"),
                    "losses": record.get("losses"),
                    "team": team,
                })
            try:
                pairings = get(f"/tournaments/{t['id']}/pairings")
            except requests.HTTPError as err:
                print(f"  no pairings for {t['id']}: {err}")
                pairings = []
            for m in pairings or []:
                p1, p2 = m.get("player1"), m.get("player2")
                if not p1 or not p2:
                    continue  # byes
                matches.append({
                    "tournament": t["id"],
                    "round": m.get("round"),
                    "phase": m.get("phase"),
                    "p1": str(p1), "p2": str(p2),
                    "winner": str(m.get("winner")) if m.get("winner") not in (None, "") else "",
                })
        teams.sort(key=lambda r: (r["date"], r["tournament"], r["placing"] or 9999))
        out = OUT_DIR / f"{reg}.json"
        out.write_text(json.dumps({
            "source": "play.limitlesstcg.com",
            "format": fmt,
            "tournaments": len({r["tournament"] for r in teams}),
            "teams": teams,
        }, separators=(",", ":")))
        print(f"{reg} ({fmt}): {len(tournaments)} tournaments, {len(teams)} team lists -> {out.relative_to(ROOT)}")
        if matches:
            mout = OUT_DIR / f"{reg}_matches.json"
            mout.write_text(json.dumps({"source": "play.limitlesstcg.com", "format": fmt, "matches": matches},
                                       separators=(",", ":")))
            print(f"  {len(matches)} matches -> {mout.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
