#!/usr/bin/env python3
"""
summarize_replays.py

Per-Pokemon replay stats (src/replays.species_stats) for the app, so it doesn't
load every replay: data/replays/summary/<format>.json with, for each Pokemon,
how often it's brought / leads when on team preview, its win rate when brought,
how often it Mega Evolves, and its usual turn-1 moves. Run after each fetch.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.replays import REPLAY_DIR, load_records, species_stats  # noqa: E402

FORMATS = ["gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3"]


def main() -> None:
    out_dir = REPLAY_DIR / "summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    for fmt in FORMATS:
        records = load_records(fmt)
        if not records:
            continue
        rated = [r for r in records if min((r["players"][p]["rating"] or 0) for p in ("p1", "p2")) >= 1300]
        summary = {
            "format": fmt, "games": len(records), "games_1300_plus": len(rated),
            "first_day": datetime.fromtimestamp(records[0]["uploadtime"], timezone.utc).strftime("%Y-%m-%d"),
            "last_day": datetime.fromtimestamp(records[-1]["uploadtime"], timezone.utc).strftime("%Y-%m-%d"),
            "pokemon": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}
                        for row in species_stats(records, min_previews=30)],
        }
        (out_dir / f"{fmt}.json").write_text(json.dumps(summary, indent=0))
        print(f"{fmt}: {len(records)} games, {len(summary['pokemon'])} Pokémon")


if __name__ == "__main__":
    main()
