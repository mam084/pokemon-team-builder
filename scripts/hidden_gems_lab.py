"""Are Hidden gems picks any good? Tested on ladder and Bo3 replays (Nov 2026).

Tournaments can't judge off-meta picks: almost nobody brings them there. Ladder replays can: ~100,000
rated games with both teams' previews, plenty of uncommon Pokemon among them.

1. Each Pokemon's win edge, adjusted for both players' ratings: a logistic regression of the result on
   the rating gap plus which Pokemon each side brought (ridge-penalized, so a Pokemon with few games
   stays near zero). In points of win chance; 90% ranges from a bootstrap by player.
2. Take real tournament teams, hide one member, and ask each style for its top 3 picks.
3. Compare the edge of the picks with what the style could have picked: for Hidden gems, every
   uncommon Pokemon; for the others, their whole pool.

Picks don't use results at all (only who is run with whom), so the edges are an independent check.

    python scripts/hidden_gems_lab.py
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from src.analysis import build_members
from src.dex import load_dex
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.recommend import HIDDEN_MAX, recommend
from src.replays import load_records
from src.usage import load_usage

TEAMS = 300
TOP = 3
BOOT = 40


def games(dex):
    rows = []
    for fmt in CURRENT.replays:
        for r in load_records(fmt):
            prev, pl = r.get("preview") or {}, r["players"]
            if set(prev) != {"p1", "p2"} or r.get("winner") not in ("p1", "p2") or r.get("forfeit"):
                continue
            if not (pl["p1"].get("rating") and pl["p2"].get("rating")):
                continue
            sides = []
            for p in ("p1", "p2"):
                roots = set()
                for name in prev[p]:
                    sp = dex.get_species(name)
                    if sp is not None:
                        roots.add(dex.sheet_id(sp))
                sides.append(roots)
            rows.append((pl["p1"]["name"], (pl["p1"]["rating"] - pl["p2"]["rating"]) / 400 * np.log(10),
                         sides[0], sides[1], int(r["winner"] == "p1")))
    return rows


def fit_edges(rows, idx, pick=None):
    pick = np.arange(len(rows)) if pick is None else pick
    data, ri, ci = [], [], []
    for n, k in enumerate(pick):
        _, gap, a, b, _ = rows[k]
        ri.append(n); ci.append(0); data.append(gap)
        for r in a - b:
            ri.append(n); ci.append(1 + idx[r]); data.append(1.0)
        for r in b - a:
            ri.append(n); ci.append(1 + idx[r]); data.append(-1.0)
    X = sparse.csr_matrix((data, (ri, ci)), shape=(len(pick), 1 + len(idx)))
    y = np.array([rows[k][4] for k in pick], float)
    m = LogisticRegression(C=0.05, fit_intercept=False, max_iter=2000)
    m.fit(sparse.vstack([X, -X]), np.r_[y, 1 - y])
    return 25 * m.coef_[0][1:]   # log-odds -> win-chance points near 50%


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id)
    rows = games(dex)
    count = Counter(r for g in rows for side in (g[2], g[3]) for r in side)
    vocab = sorted(count)
    idx = {r: i for i, r in enumerate(vocab)}
    print(f"{len(rows):,} rated games, {len(vocab)} Pokemon seen")
    edge = fit_edges(rows, idx)
    players = np.array([g[0] for g in rows])
    by = {p: np.flatnonzero(players == p) for p in np.unique(players)}
    keys = list(by)
    rng = np.random.default_rng(0)
    boots = [fit_edges(rows, idx, np.concatenate([by[k] for k in rng.choice(keys, len(keys))]))
             for _ in range(BOOT)]
    print("bootstrap done", flush=True)

    root_of = lambda name: dex.sheet_id(dex.get_species(name)) if dex.get_species(name) else None  # noqa: E731
    teams = [t for t in load_tournament_teams(reg, dex, usage=usage) if len(t["sets"]) == 6]
    random.Random(0).shuffle(teams)
    teams = teams[:TEAMS]
    common = {root_of(n) for n, _ in usage.ranked(10_000) if usage.is_common(n, dex, HIDDEN_MAX)}

    print(f"\nwin edge of each style's top {TOP} picks for {len(teams)} real teams missing one member "
          "(points of win chance, rating-adjusted; 90% range by player bootstrap)")
    for mode in ("popular", "neutral", "hidden"):
        picks, pools = [], []
        for t in teams:
            k = random.Random(t["player"]).randrange(6)
            rest = t["sets"][:k] + t["sets"][k + 1:]
            recs = recommend(build_members(rest, dex), dex, usage, mode=mode, top_n=None)
            if recs.empty:
                continue
            roots = [root_of(n) for n in recs["pokemon"]]
            roots = [r for r in roots if r in idx]
            picks += roots[:TOP]
            pools.append(roots)
        pool = sorted({r for p in pools for r in p})
        pick_ids = [idx[r] for r in picks]
        pool_ids = [idx[r] for r in pool]
        diff = [b[pick_ids].mean() - b[pool_ids].mean() for b in boots]
        print(f"  {mode:8s} picks {edge[pick_ids].mean():+.2f} vs its pool {edge[pool_ids].mean():+.2f}: "
              f"{edge[pick_ids].mean() - edge[pool_ids].mean():+.2f} ({np.percentile(diff, 5):+.2f} to "
              f"{np.percentile(diff, 95):+.2f}) | {len(set(picks))} different Pokemon, pool {len(pool)}", flush=True)
        if mode == "hidden":
            top = Counter(picks).most_common(12)
            names = {dex.sheet_id(s): s.name for s in dex.selectable_species()}
            print("    most picked:", ", ".join(f"{names.get(r, r)} {edge[idx[r]]:+.1f} ({count[r]:,} games)"
                                             for r, _ in top))
            uncommon = [i for r, i in idx.items() if r not in common]
            print(f"    every uncommon Pokemon: {edge[uncommon].mean():+.2f}; common ones: "
                  f"{edge[[idx[r] for r in common if r in idx]].mean():+.2f}")


if __name__ == "__main__":
    main()
