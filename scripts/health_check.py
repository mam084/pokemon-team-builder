"""Model health check: is everything the app ships still beating its baseline, and is the data fresh?

The refresh workflow re-runs every held-out evaluation (monthly and when data scripts change) and writes
data/evaluation/; nothing read those back. This does, read-only:

- recommender: tuned weights beat popularity alone on held-out tournament teams (MRR)
- learned win model: beats the damage-calc score (95% interval of the gain above 0), and stays calibrated
- team check: its ranking of held-out teams still lines up with their records (Spearman > 0, top quarter
  won more than the bottom quarter)
- bring / lead model: matches real picks at least as well as players' usual picks
- data: replays fetched in the last 2 days, usage stats no more than 2 months old, a tournament in the
  last 14 days

Prints a table; exits 1 if any check fails (the weekly workflow then opens or updates an issue).

    python scripts/health_check.py [--markdown]
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "data" / "evaluation"
sys.path.insert(0, str(ROOT))


def _load(name: str) -> dict | None:
    path = EVAL / name
    return json.loads(path.read_text()) if path.exists() else None


GRACE_DAYS = 35
WAITING = "waiting:"


def checks(reg: str | None = None, now: datetime | None = None) -> list[tuple[str, bool, str]]:
    from src.formats import CURRENT
    reg = reg or CURRENT.regulation
    now = now or datetime.now(timezone.utc)
    out: list[tuple[str, bool, str]] = []
    # a new regulation has no held-out evaluations until tournaments and replays pile up:
    # a missing file is a wait, not a failure, for its first GRACE_DAYS
    start = datetime.strptime(CURRENT.start, "%Y-%m-%d").replace(tzinfo=timezone.utc) if CURRENT.start else None
    young = start is not None and (now - start).days < GRACE_DAYS

    def missing() -> tuple[bool, str]:
        if young:
            return True, f"{WAITING} new regulation (started {CURRENT.start}): needs a few weeks of tournaments"
        return False, "no evaluation file"

    rec = _load(f"{reg}.json")
    if rec:
        r = rec["results"]
        tuned, pop = r["tuned weights"]["mrr"], r["popularity only"]["mrr"]
        out.append(("Recommender beats popularity", tuned > pop,
                    f"MRR {tuned:.3f} vs {pop:.3f} on {rec['test_teams']} held-out teams ({rec['test_dates'][0]}+)"))
    else:
        out.append(("Recommender beats popularity", *missing()))

    mm = _load(f"{reg}_match_model.json")
    if mm:
        lo, hi = mm["gain_ci95"]["learned vs damage-calc score"]
        out.append(("Win model beats damage calcs", lo > 0,
                    f"log-loss gain 95% [{lo:+.4f}, {hi:+.4f}] on {mm['test_matches']} held-out matches"))
        worst = max(abs(c["predicted"] - c["actual"]) for c in mm["calibration"])
        out.append(("Win model calibrated", worst <= 0.05, f"largest gap between predicted and actual {worst:.3f}"))
    else:
        out.append(("Win model beats damage calcs", *missing()))

    tc = _load(f"{reg}_team_check.json")
    if tc:
        w = tc["ranking"]["with bounds"]
        q = w["quarters"]
        ok = w["spearman"] > 0 and q[-1]["actual"] > q[0]["actual"]
        out.append(("Team check ranks real teams", ok,
                    f"Spearman {w['spearman']:.3f}; top quarter won {q[-1]['actual']:.1%}, bottom {q[0]['actual']:.1%}"))
    else:
        out.append(("Team check ranks real teams", *missing()))

    bm = _load(f"{reg}_bring_model.json")
    if bm:
        for part in ("bring", "lead"):
            r = bm["results"][part]
            ok = r["learned"][0] >= r["usual picks"][0]
            out.append((f"Bring model ({part}) beats usual picks", ok,
                        f"{r['learned'][0]:.1%} vs {r['usual picks'][0]:.1%} on {bm['test_sides']} held-out sides"))
    else:
        out.append(("Bring model beats usual picks", *missing()))

    # data freshness
    newest = 0
    for fmt in CURRENT.replays:
        files = sorted((ROOT / "data" / "replays" / fmt).glob("*.jsonl.gz"))
        for f in files[-2:]:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        newest = max(newest, json.loads(line).get("uploadtime") or 0)
                    except json.JSONDecodeError:
                        continue
    age_h = (now.timestamp() - newest) / 3600 if newest else float("inf")
    out.append(("Replays are fresh", age_h <= 48, f"newest replay {age_h:.0f} hours old"))
    usage_file = ROOT / "data" / "usage" / f"{CURRENT.id}.json"
    if young and not usage_file.exists():
        out.append(("Usage stats are current", True,
                    f"{WAITING} no Smogon stats yet for the new regulation; usage comes from its replays"))
    elif rec:
        y, m = map(int, rec["usage_month"].split("-"))
        months = (now.year - y) * 12 + now.month - m
        out.append(("Usage stats are current", months <= 2, f"Smogon month {rec['usage_month']} ({months} months back)"))
    tour = ROOT / "data" / "tournaments" / f"{reg}.json"
    if tour.exists():
        dates = [t.get("date") for t in json.loads(tour.read_text()).get("teams", []) if t.get("date")]
        last = max(dates) if dates else None
        days = (now - datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days if last else 999
        out.append(("Tournaments are fresh", days <= 14, f"latest tournament {last} ({days} days ago)"))
    elif young:
        out.append(("Tournaments are fresh", True, f"{WAITING} no tournament lists yet for the new regulation"))
    return out


def main() -> int:
    results = checks()
    failed = [r for r in results if not r[1]]
    if "--markdown" in sys.argv:
        print("| check | | detail |\n|---|---|---|")
        for name, ok, detail in results:
            mark = "⏳" if detail.startswith(WAITING) else ("✅" if ok else "❌")
            print(f"| {name} | {mark} | {detail.removeprefix(WAITING).strip()} |")
    else:
        for name, ok, detail in results:
            mark = "WAIT" if detail.startswith(WAITING) else ("PASS" if ok else "FAIL")
            print(f"{mark}  {name}: {detail.removeprefix(WAITING).strip()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
