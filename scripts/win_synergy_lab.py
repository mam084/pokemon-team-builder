"""
win_synergy_lab.py - can replays tell which *pairs* win more together?

Logistic models of who wins a ladder / Bo3 game, fitted on older replays and scored on the
newest 25% (log loss, accuracy):

    rating      the two players' ratings only
    + species   which Pokemon each side brought to preview (team A minus team B)
    + pairs     plus every pair on each team (the "win synergy" a recommender would use)

If the pair terms don't beat "+ species" on new games, pair win-rates are noise at this data
size and shouldn't drive recommendations.

    python scripts/win_synergy_lab.py
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import root_of  # noqa: E402

FMT = "gen9championsvgc2026regmc"


def main():
    dex = load_dex("regmc")
    records = sorted((r for f in (FMT, FMT + "bo3") for r in load_records(f) if not r.get("forfeit")),
                     key=lambda r: r["uploadtime"] or 0)
    games = []
    for r in records:
        teams = []
        for p in ("p1", "p2"):
            roots = sorted({x for s in r["preview"][p] if (x := root_of(s, dex))})
            teams.append(roots)
        if min(len(t) for t in teams) < 6:
            continue
        ra, rb = (r["players"][p]["rating"] or 0 for p in ("p1", "p2"))
        games.append((teams[0], teams[1], ra, rb, 1.0 if r["winner"] == "p1" else 0.0))
    cut = int(len(games) * 0.75)
    print(f"{len(games)} games; train {cut}, test {len(games) - cut}")

    species = sorted({s for g in games[:cut] for t in g[:2] for s in t})
    s_idx = {s: i for i, s in enumerate(species)}
    pair_counts = {}
    for g in games[:cut]:
        for t in g[:2]:
            for pr in combinations(t, 2):
                pair_counts[pr] = pair_counts.get(pr, 0) + 1
    pairs = sorted(pr for pr, n in pair_counts.items() if n >= 30)
    p_idx = {pr: i for i, pr in enumerate(pairs)}
    print(f"{len(species)} species, {len(pairs)} pairs seen 30+ times")

    def features(g, with_species, with_pairs):
        a, b, ra, rb, _ = g
        known = float(ra > 0 and rb > 0)
        base = [known * (ra - rb) / 400, float(ra > 0) - float(rb > 0)]
        cols, vals = list(range(2)), base
        off = 2
        if with_species:
            for s in a:
                if s in s_idx:
                    cols.append(off + s_idx[s]); vals.append(1.0)
            for s in b:
                if s in s_idx:
                    cols.append(off + s_idx[s]); vals.append(-1.0)
            off += len(species)
        if with_pairs:
            for pr in combinations(a, 2):
                if pr in p_idx:
                    cols.append(off + p_idx[pr]); vals.append(1.0)
            for pr in combinations(b, 2):
                if pr in p_idx:
                    cols.append(off + p_idx[pr]); vals.append(-1.0)
            off += len(pairs)
        return cols, vals, off

    def matrix(gs, ws, wp):
        rows, cols, vals = [], [], []
        width = 2
        for n, g in enumerate(gs):
            c, v, width = features(g, ws, wp)
            rows += [n] * len(c); cols += c; vals += v
        x = sparse.csr_matrix((vals, (rows, cols)), shape=(len(gs), width))
        y = np.array([g[4] for g in gs])
        # both orientations so the model can't learn a p1 bias
        return sparse.vstack([x, -x]), np.r_[y, 1 - y]

    train, test = games[:cut], games[cut:]
    for name, ws, wp in (("rating", False, False), ("+ species", True, False), ("+ pairs", True, True)):
        xtr, ytr = matrix(train, ws, wp)
        xte, yte = matrix(test, ws, wp)
        best = None
        for c in (0.003, 0.01, 0.03, 0.1, 0.3):
            # pick C on the last 20% of train (forward), then refit on all train
            k = int(len(train) * 0.8)
            xa, ya = matrix(train[:k], ws, wp)
            xb, yb = matrix(train[k:], ws, wp)
            xa = xa[:, :xtr.shape[1]] if xa.shape[1] >= xtr.shape[1] else sparse.hstack(
                [xa, sparse.csr_matrix((xa.shape[0], xtr.shape[1] - xa.shape[1]))]).tocsr()
            xb = xb[:, :xtr.shape[1]] if xb.shape[1] >= xtr.shape[1] else sparse.hstack(
                [xb, sparse.csr_matrix((xb.shape[0], xtr.shape[1] - xb.shape[1]))]).tocsr()
            m = LogisticRegression(C=c, fit_intercept=False, max_iter=2000).fit(xa, ya)
            ll = log_loss(yb, m.predict_proba(xb)[:, 1])
            if best is None or ll < best[0]:
                best = (ll, c)
        m = LogisticRegression(C=best[1], fit_intercept=False, max_iter=2000).fit(xtr, ytr)
        p = m.predict_proba(xte)[:, 1]
        print(f"{name:10s} C={best[1]}: test log loss {log_loss(yte, p):.4f}, "
              f"accuracy {accuracy_score(yte, p > 0.5):.4f}")
        if wp:
            coef = m.coef_[0][2 + len(species):]
            top = np.argsort(-coef)[:12]
            print("   strongest pairs:", [(pairs[i], round(float(coef[i]), 3)) for i in top])


if __name__ == "__main__":
    main()
