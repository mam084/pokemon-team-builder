#!/usr/bin/env python3
"""
fetch_replays.py

Downloads public Pokemon Showdown replays for Champions formats and stores
each as a compact parsed record (src/replay_parse.py), one gzip'd JSON-lines
file per format per upload day:

    data/replays/<format>/<YYYY-MM-DD>.jsonl.gz

Two directions, tracked in data/replays/state.json so runs pick up where the
last one stopped:

- new (default): everything uploaded since the newest replay already stored
- backfill: older replays, continuing below the oldest one stored, back to
  --since (the start of the regulation)

Each run stops cleanly before --minutes so it fits in a GitHub Actions job;
schedule it and it catches up on its own. Runs on GitHub Actions (the dev
sandbox can't reach Showdown). --samples N also saves N raw logs to
data/replays/samples/ for parser tests.

    python scripts/fetch_replays.py                     # new replays
    python scripts/fetch_replays.py --backfill --minutes 300
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.replay_parse import parse_log  # noqa: E402

OUT = ROOT / "data" / "replays"
STATE = OUT / "state.json"
SEARCH = "https://replay.pokemonshowdown.com/search.json"
REPLAY = "https://replay.pokemonshowdown.com/{id}.json"
from src.formats import replay_sources  # noqa: E402  (the current regulation's formats)

FORMATS = list(replay_sources())
SINCE = min((start for _, start in replay_sources().values() if start), default="2026-09-09")
HEADERS = {"User-Agent": "pokemon-team-builder replay fetcher (github.com/mam084/pokemon-team-builder)"}
DELAY = 0.35  # seconds between requests: be a polite client


def get(url: str, params: dict | None = None, tries: int = 4):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def day_of(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def stored_ids(fmt: str, day: str) -> set[str]:
    path = OUT / fmt / f"{day}.jsonl.gz"
    if not path.exists():
        return set()
    with gzip.open(path, "rt") as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


def append(fmt: str, records: list[dict]) -> None:
    """Merge records into their day files (rewrites only the days touched)."""
    by_day: dict[str, list[dict]] = {}
    for rec in records:
        by_day.setdefault(day_of(rec["uploadtime"]), []).append(rec)
    for day, recs in by_day.items():
        path = OUT / fmt / f"{day}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if path.exists():
            with gzip.open(path, "rt") as f:
                existing = [json.loads(line) for line in f if line.strip()]
        seen = {r["id"] for r in existing}
        merged = existing + [r for r in recs if r["id"] not in seen]
        merged.sort(key=lambda r: r["uploadtime"])
        with gzip.open(path, "wt", compresslevel=9) as f:
            for r in merged:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")


def fetch(fmt: str, state: dict, backfill: bool, deadline: float, since_ts: int, samples: int) -> dict:
    s = state.setdefault(fmt, {})
    newest_stored, oldest_stored = s.get("newest"), s.get("oldest")
    before = oldest_stored if backfill and oldest_stored else None
    batch_records, fetched, saved_samples = [], 0, 0
    sample_dir = OUT / "samples"
    stop = False
    while not stop and time.time() < deadline:
        page = get(SEARCH, {"format": fmt, **({"before": before} if before else {})})
        time.sleep(DELAY)
        if not page:
            break
        for item in page[:50]:
            ts = item["uploadtime"]
            if (not backfill and newest_stored and ts <= newest_stored) or ts < since_ts:
                stop = True
                break
            if time.time() >= deadline:
                stop = True
                break
            try:
                data = get(REPLAY.format(id=item["id"]))
            except requests.RequestException as err:
                print(f"  skip {item['id']}: {err}")
                continue
            time.sleep(DELAY)
            if samples and saved_samples < samples:
                sample_dir.mkdir(parents=True, exist_ok=True)
                (sample_dir / f"{item['id']}.json").write_text(json.dumps(data))
                saved_samples += 1
            rec = parse_log(data.get("log", ""), {**item, "format": fmt, "rating": data.get("rating", item.get("rating"))})
            batch_records.append(rec)
            fetched += 1
            s["newest"] = max(s.get("newest") or 0, ts)
            s["oldest"] = min(s.get("oldest") or ts, ts)
            if len(batch_records) >= 500:  # flush as we go, so a stopped run keeps its work
                append(fmt, batch_records)
                batch_records = []
                STATE.write_text(json.dumps(state, indent=1))
        if len(page) < 51:
            s["reached_end"] = backfill
            break
        before = page[-1]["uploadtime"]
    if batch_records:
        append(fmt, batch_records)
    if backfill and not stop and time.time() < deadline:
        s["reached_end"] = True
    s["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(state, indent=1))
    return {"format": fmt, "fetched": fetched}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="fetch older replays instead of new ones")
    parser.add_argument("--minutes", type=float, default=50, help="stop cleanly after this long")
    parser.add_argument("--since", default=SINCE, help="oldest upload day to fetch (YYYY-MM-DD)")
    parser.add_argument("--format", action="append", dest="formats", help="format id (repeatable)")
    parser.add_argument("--samples", type=int, default=0, help="also save this many raw logs per format")
    args = parser.parse_args()
    state = load_state()
    deadline = time.time() + args.minutes * 60
    since_ts = int(datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    formats = args.formats or FORMATS
    for i, fmt in enumerate(formats):
        # split the time budget between formats still to go
        share = (deadline - time.time()) / (len(formats) - i)
        out = fetch(fmt, state, args.backfill, time.time() + share, since_ts, args.samples)
        print(f"{fmt}: {out['fetched']} replays ({'backfill' if args.backfill else 'new'})")


if __name__ == "__main__":
    main()
