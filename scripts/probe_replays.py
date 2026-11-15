#!/usr/bin/env python3
"""
probe_replays.py

How much Showdown replay data exists for Champions? A one-off probe (run on
GitHub Actions; the dev sandbox can't reach Showdown).

For each candidate format it pages through replay.pokemonshowdown.com's public
search (newest first, ~51 per page) and records how many replays exist, their
date range, ladder ratings and per-month counts. It also downloads a few logs
and checks what they contain: team preview (|poke|), open team sheets
(|showteam|), and ratings in |player| lines.

    python scripts/probe_replays.py --pages 120
Writes data/replays/probe.json.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "replays" / "probe.json"
SEARCH = "https://replay.pokemonshowdown.com/search.json"
REPLAY = "https://replay.pokemonshowdown.com/{id}.json"
FORMATS = ["gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3", "gen9championsbssregmc",
           "gen9championsvgc2026regmb", "gen9championsvgc2026"]
HEADERS = {"User-Agent": "pokemon-team-builder replay probe (github.com/mam084/pokemon-team-builder)"}
DELAY = 0.6


def search(fmt: str, before: int | None) -> list[dict]:
    params = {"format": fmt}
    if before:
        params["before"] = before
    r = requests.get(SEARCH, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def log_summary(replay_id: str) -> dict:
    r = requests.get(REPLAY.format(id=replay_id), headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    lines = data.get("log", "").splitlines()
    kinds = Counter(line.split("|")[1] for line in lines if line.startswith("|") and len(line.split("|")) > 1)
    players = [line for line in lines if line.startswith("|player|")]
    return {"id": replay_id, "turns": kinds.get("turn", 0), "has_team_preview": kinds.get("poke", 0) > 0,
            "has_open_team_sheets": kinds.get("showteam", 0) > 0, "switches": kinds.get("switch", 0),
            "moves": kinds.get("move", 0), "player_lines": players[:4], "rating": data.get("rating"),
            "first_lines": lines[:12]}


def probe(fmt: str, pages: int) -> dict:
    seen, before = [], None
    for _ in range(pages):
        try:
            batch = search(fmt, before)
        except requests.HTTPError as err:
            return {"format": fmt, "error": str(err), "replays": len(seen)}
        if not batch:
            break
        seen += batch[:50]
        before = batch[-1]["uploadtime"]
        if len(batch) < 51:
            break
        time.sleep(DELAY)
    if not seen:
        return {"format": fmt, "replays": 0}
    times = [r["uploadtime"] for r in seen]
    ratings = [r.get("rating") or 0 for r in seen]
    months = Counter(datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m") for t in times)
    rated = [x for x in ratings if x]
    out = {
        "format": fmt, "replays": len(seen), "hit_page_limit": len(seen) >= pages * 50,
        "newest": datetime.fromtimestamp(max(times), timezone.utc).isoformat(),
        "oldest": datetime.fromtimestamp(min(times), timezone.utc).isoformat(),
        "per_month": dict(sorted(months.items())),
        "rated": len(rated),
        "rating_quantiles": ({q: int(sorted(rated)[int(q / 100 * (len(rated) - 1))]) for q in (10, 50, 90, 99)}
                             if rated else {}),
        "rated_1500_plus": sum(x >= 1500 for x in rated), "rated_1700_plus": sum(x >= 1700 for x in rated),
        "unique_players": len({p for r in seen for p in r.get("players", [])}),
        "samples": [],
    }
    for r in seen[:3]:
        try:
            out["samples"].append(log_summary(r["id"]))
        except requests.RequestException as err:
            out["samples"].append({"id": r["id"], "error": str(err)})
        time.sleep(DELAY)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=120, help="max search pages per format (~50 replays each)")
    args = parser.parse_args()
    report = {"probed_at": datetime.now(timezone.utc).isoformat(), "pages_per_format": args.pages,
              "formats": [probe(fmt, args.pages) for fmt in FORMATS]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1))
    for f in report["formats"]:
        print(f"{f['format']}: {f.get('replays')} replays {f.get('oldest', '')[:10]} .. {f.get('newest', '')[:10]}"
              f" rated={f.get('rated')} {f.get('error', '')}")


if __name__ == "__main__":
    main()
