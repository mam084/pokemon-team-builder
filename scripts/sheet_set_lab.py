"""Real team sheets vs ladder stats for a Pokemon's set (Nov 2026).

Popular sets (UsageData.popular_set) come from Smogon's ladder stats, which count each move on its
own. Bo3 replays publish open team sheets and Limitless publishes tournament sheets: whole sets real
players ran. For each Pokemon (and whether it holds its Mega Stone), build its set from sheets dated
before the held-out week and compare with the ladder set on every member of every held-out tournament
team: how many of its four moves, and whether its nature, match what that player ran.

  ladder        popular_set's top four moves and top spread's nature
  sheet top 4   the four moves most often on sheets
  sheet mode    the most common complete moveset on sheets
  mode X%+      the most common complete moveset when at least X% of sheets share it, else sheet top 4
Sheet sets are used only with at least MIN sheets, else the ladder set. Natures: tournament sheets only
(Bo3 sheets don't show them).

    python scripts/sheet_set_lab.py
"""
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from src.dex import load_dex, to_id
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.replays import load_records
from src.sheet_sets import sheet_key, sheet_sets_from
from src.usage import load_usage

CUT = "2026-11-12"
KINDS = ("top4", "mode", "mode15", "mode25", "mode40")


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, tournament_pairs=False, recent=False)
    teams = load_tournament_teams(reg, dex)
    train_t = [t for t in teams if t["date"] < CUT]
    held = [t for t in teams if t["date"] >= CUT]
    from datetime import datetime, timezone
    cut_ts = datetime.strptime(CUT, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    bo3 = [r for f in CURRENT.replays for r in load_records(f) if (r.get("uploadtime") or 0) < cut_ts and r.get("sheets")]
    print(f"{len(held)} held-out teams; sheets before {CUT}: {len(train_t)} tournament teams, {len(bo3)} Bo3 games")

    variants = {}
    for days in (30, None):
        for min_n in (10, 30):
            variants[(days, min_n)] = sheet_sets_from(train_t, bo3, dex, end=CUT, days=days)
    rows = []
    for ti, t in enumerate(held):
        for p in t["sets"]:
            key = sheet_key(p, dex)
            real = {to_id(m) for m in p.moves}
            if len(real) < 4:
                continue
            lad = usage.popular_set(p.species, dex, allow_mega=key[1])
            if lad is None:
                continue
            row = {"team": ti, "ladder": len(real & {to_id(m) for m in lad.moves}),
                   "ladder_nat": lad.nature == p.nature}
            for (days, min_n), sets in variants.items():
                s = sets.get(key)
                ok = s is not None and s["n"] >= min_n
                for kind in KINDS:
                    if not ok:
                        mv = [to_id(m) for m in lad.moves]
                    elif kind.startswith("mode") and kind != "mode":
                        share = int(kind[4:]) / 100
                        mv = s["mode"] if s["mode_n"] >= share * s["n"] else s["top4"]
                    else:
                        mv = s[kind]
                    row[(days, min_n, kind)] = len(real & set(mv))
                nat = s.get("nature") if ok and s.get("nature_n", 0) >= 5 else lad.nature
                row[(days, min_n, "nat")] = nat == p.nature
                row[(days, min_n, "used")] = ok
            rows.append(row)
    print(f"{len(rows)} held-out sets\n")
    print(f"{'set from':34s} moves matching /4   natures   sets using sheets")
    print(f"{'ladder (shipped)':34s} {np.mean([r['ladder'] for r in rows]):.3f}            "
          f"{np.mean([r['ladder_nat'] for r in rows]):.1%}")
    rng = random.Random(0)
    by_team = defaultdict(list)
    for r in rows:
        by_team[r["team"]].append(r)
    keys = list(by_team)
    for (days, min_n) in variants:
        for kind in KINDS:
            k = (days, min_n, kind)
            gain = np.mean([r[k] - r["ladder"] for r in rows])
            boots = []
            for _ in range(1000):
                sample = [r for kk in (rng.choice(keys) for _ in keys) for r in by_team[kk]]
                boots.append(np.mean([r[k] - r["ladder"] for r in sample]))
            lo, hi = np.percentile(boots, [2.5, 97.5])
            name = f"sheets {days or 'all'}d, {min_n}+, {kind}"
            print(f"{name:34s} {np.mean([r[k] for r in rows]):.3f} ({gain:+.3f}, 95% {lo:+.3f} to {hi:+.3f})  "
                  f"{np.mean([r[(days, min_n, 'nat')] for r in rows]):.1%}    "
                  f"{np.mean([r[(days, min_n, 'used')] for r in rows]):.0%}")


if __name__ == "__main__":
    main()
