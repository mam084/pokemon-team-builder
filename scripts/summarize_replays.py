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
from src.replays import REPLAY_DIR, load_records, recent_usage, rising, species_stats  # noqa: E402

from src.formats import replay_sources  # noqa: E402

FORMATS = list(replay_sources())


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
    # current-meta usage per app format, from all its replay formats (ladder + Bo3) together
    from src.dex import load_dex
    from src.formats import FORMATS as APP_FORMATS
    for app_id in sorted({app for app, _ in replay_sources().values()}):
        fmt = APP_FORMATS[app_id]
        records = [r for f in fmt.replays for r in load_records(f)]
        dex = load_dex(fmt.regulation)
        up = rising(records, dex)
        if up:
            (out_dir / f"{app_id}_rising.json").write_text(json.dumps({"format": app_id, **up}, indent=0))
            print(f"{app_id}: rising this week from {up['teams']} teams vs {up['teams_before']}")
        recent = recent_usage(records, dex)
        path = out_dir / f"{app_id}_recent_usage.json"
        if recent:
            path.write_text(json.dumps({"format": app_id, **recent}, indent=0))
            print(f"{app_id}: recent usage from {recent['teams']} teams ({recent['first_day']} to {recent['last_day']})")
        # usage built from replays alone: the app's usage until Smogon has stats for the format
        from src.replay_usage import build_for as build_replay_usage, save as save_replay_usage
        from src.usage import USAGE_DIR
        from src.usage import _before_start
        smogon = USAGE_DIR / f"{app_id}.json"
        if not smogon.exists() or _before_start(smogon, app_id):
            built = build_replay_usage(fmt, records, dex)
            if built:
                save_replay_usage(built, app_id)
                print(f"{app_id}: no Smogon stats yet; usage from {built['info']['teams']} replay teams "
                      f"({built['info']['first_day']} to {built['info']['last_day']})")
        # turn-1 moves per lead, overall and against each opposing lead (Battle plan tab)
        from src.replays import turn1_table
        from src.synergy import recent_records
        t1 = turn1_table(recent_records(records, days=30))
        (out_dir / f"{app_id}_turn1.json").write_text(json.dumps({"format": app_id, "pokemon": t1},
                                                                  separators=(",", ":")))
        print(f"{app_id}: turn-1 moves for {len(t1)} leads")
        # whole sets from the last 30 days of real team sheets (src/sheet_sets.py)
        from src.evaluate import load_tournament_teams
        from src.sheet_sets import save as save_sheets, sheet_sets_from
        sheets = sheet_sets_from(load_tournament_teams(fmt.regulation, dex), records, dex)
        if sheets:
            save_sheets(sheets, app_id)
            print(f"{app_id}: sheet sets for {len(sheets)} Pokémon")
        # per-Pokemon "what players do with it" for the builder's core report (src/core_report.py)
        from src.core_report import plan_setters, replay_index
        from src.usage import load_usage
        usage = load_usage(app_id)
        cores = replay_index(records, dex, setters=plan_setters(usage, dex) if usage is not None else None)
        # how to play against Trick Room, Tailwind, weather... (src/playbook.py)
        if usage is not None:
            from src.playbook import common_moves, replay_playbook, save as save_book, style_setters
            book = replay_playbook(records, dex, style_setters(usage, dex), common=common_moves(usage))
            if book:
                save_book(book, app_id)
                print(f"{app_id}: playbook for {len(book['styles'])} styles")
        if cores:
            (out_dir / f"{app_id}_cores.json").write_text(json.dumps({"format": app_id, **cores}, separators=(",", ":")))
            print(f"{app_id}: core report for {len(cores['pokemon'])} Pokémon ({cores['from']} to {cores['to']})")


if __name__ == "__main__":
    main()
