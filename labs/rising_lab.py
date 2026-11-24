"""
rising_lab.py - is "rising this week" worth showing? A Pokemon whose share of ladder teams jumped this
week: does it keep the gain the next week (a real trend players can get ahead of), or fall back (noise)?

Tests the rule the app ships (src/replays.rising: weeks start Sunday, UTC; this week is Sunday so far,
falling back to the last full week early on Sunday) as of the end of every day in the replays: its top
10 risers, and their share in the next full Sunday-Saturday week after "this week". Kept if they're
still above last week's share then, on average, with a 95% interval above zero.

    python labs/rising_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402

from src.dex import load_dex  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.replays import load_records, rising, team_shares, week_start  # noqa: E402

DAY = 86400
WEEK = 7 * DAY
TOP = 10
MIN_TEAMS = 40


def main() -> None:
    dex = load_dex(CURRENT.regulation)
    recs = [r for f in CURRENT.replays for r in load_records(f) if r.get("uploadtime")]
    first, last = min(r["uploadtime"] for r in recs), max(r["uploadtime"] for r in recs)
    rows, days = [], 0
    d = week_start(first) + 2 * WEEK + DAY - 1          # end of a day with a full week behind this one
    while d <= last:
        up = rising(recs, dex, top=TOP, min_teams=MIN_TEAMS, now=d)
        if up:
            this_start = int(datetime.fromisoformat(up["first_day"]).replace(tzinfo=timezone.utc).timestamp())
            nxt, _, n_next = team_shares(recs, this_start + WEEK, this_start + 2 * WEEK, dex)
            if this_start + 2 * WEEK <= last and n_next >= 500:
                days += 1
                rows += [(d, r["id"], r["before"], r["share"], nxt.get(r["id"], 0.0)) for r in up["pokemon"]]
        d += DAY
    if not rows:
        print("not enough weeks of replays yet")
        return
    a = np.array([(lw, tw, nw) for _, _, lw, tw, nw in rows])
    rise, kept = a[:, 1] - a[:, 0], a[:, 2] - a[:, 0]
    print(f"{days} days (Sunday weeks) with a full week before and after; top {TOP} risers each "
          f"(>= {MIN_TEAMS} teams this week); {len(rows)} riser-weeks")
    print(f"  rise last -> this week:          {rise.mean() * 100:+.2f} points of team share (mean)")
    print(f"  next week vs last week:          {kept.mean() * 100:+.2f} points "
          f"({kept.mean() / rise.mean():.0%} of the rise kept)")
    print(f"  still above last week next week: {(kept > 0).mean():.0%} of risers")
    per_day = {}
    for (dd, *_), k in zip(rows, kept):
        per_day.setdefault(dd, []).append(k)
    means = np.array([np.mean(v) for v in per_day.values()])
    sd = means.std(ddof=1) / np.sqrt(len(means))   # days overlap: one mean per day, then across days
    print(f"  95% interval of the kept gain (by day): {(means.mean() - 1.96 * sd) * 100:+.2f} to "
          f"{(means.mean() + 1.96 * sd) * 100:+.2f} points")

if __name__ == "__main__":
    main()
