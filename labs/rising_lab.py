"""
rising_lab.py - is "rising this week" worth showing? A Pokemon whose share of ladder teams jumped this
week: does it keep the gain the next week (a real trend players can get ahead of), or fall back (noise)?

For every day d with two weeks behind it and one ahead, on rated players' teams (each player's team
once a week, like replays.recent_usage): share in the 7 days before d (this week), the 7 before that
(last week) and the 7 after d (next week). The risers are the Pokemon with the biggest rise from last
week to this week (at least MIN_TEAMS teams this week). Kept if they're still above last week's share
the week after, on average, and keep more of the rise than a coin flip would.

    python labs/rising_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.dex import load_dex  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.replays import load_records, team_shares  # noqa: E402

DAY = 86400
WEEK = 7 * DAY
TOP = 10
MIN_TEAMS = 40


def shares(records, start, end, dex):
    return team_shares(records, start, end, dex)


def main() -> None:
    dex = load_dex(CURRENT.regulation)
    recs = [r for f in (CURRENT.id, CURRENT.id + "bo3") for r in load_records(f) if r.get("uploadtime")]
    first, last = min(r["uploadtime"] for r in recs), max(r["uploadtime"] for r in recs)
    rows = []
    d = first + 2 * WEEK
    while d + WEEK <= last:
        last_w, _, n0 = shares(recs, d - 2 * WEEK, d - WEEK, dex)
        this_w, c1, n1 = shares(recs, d - WEEK, d, dex)
        next_w, _, n2 = shares(recs, d, d + WEEK, dex)
        if min(n0, n1, n2) >= 500:
            rise = {k: this_w[k] - last_w.get(k, 0.0) for k in this_w if c1[k] >= MIN_TEAMS}
            for k in sorted(rise, key=lambda k: -rise[k])[:TOP]:
                rows.append((d, k, last_w.get(k, 0.0), this_w[k], next_w.get(k, 0.0)))
        d += DAY
    if not rows:
        print("not enough weeks of replays yet")
        return
    a = np.array([(lw, tw, nw) for _, _, lw, tw, nw in rows])
    rise, kept = a[:, 1] - a[:, 0], a[:, 2] - a[:, 0]
    days = len({r[0] for r in rows})
    print(f"{days} days with a week before, a week of risers and a week after; top {TOP} risers each "
          f"(>= {MIN_TEAMS} teams this week); {len(rows)} riser-weeks")
    print(f"  rise last -> this week:          {rise.mean() * 100:+.2f} points of team share (mean)")
    print(f"  next week vs last week:          {kept.mean() * 100:+.2f} points "
          f"({kept.mean() / rise.mean():.0%} of the rise kept)")
    print(f"  still above last week next week: {(kept > 0).mean():.0%} of risers")
    sd = kept.std(ddof=1) / np.sqrt(days)   # risers of one day overlap the next: count days, not rows
    print(f"  95% interval of the kept gain (by day): {(kept.mean() - 1.96 * sd) * 100:+.2f} to "
          f"{(kept.mean() + 1.96 * sd) * 100:+.2f} points")


if __name__ == "__main__":
    main()
