"""
rare_prior_lab.py - can rarely used Pokemon borrow partners from similar ones?

The teammate model (src/synergy.py) shrinks every pair's pull toward 0, so a Pokemon on few teams ends
up with almost no pulls and the builder does worst around it (README "Little data on a core": 55-70%
top 10 under 400 weighted teams vs 87% overall). Here pulls are shrunk toward a guess from what the
two Pokemon are instead: types, Speed, physical / special, the support tools of its most common set
(src/match_model.TOOLS: Trick Room, Tailwind, weather, Fake Out, redirection, Intimidate...), Mega,
weather and Trick Room abusers. Two stages (empirical Bayes):

1. fit the shipped model;
2. learn how feature pairs predict pulls (ridge regression of the fitted pulls on feature x feature
   products, each pair weighted by how much data backs it), giving a guess W0 = F A F' for every pair;
3. refit with the pulls shrunk toward W0 instead of 0.

Same split as src/evaluate.py: fitted on the oldest tournaments plus replays from before the tuning
tournaments, judged on the newest tournaments (each member hidden in turn, ranked from the other five
among every Pokemon the model or the test teams know). Results by how much data the least-seen of the
five has, like scripts/thin_core_lab.py; the prior's strength is chosen on the tuning tournaments.

    python scripts/rare_prior_lab.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import build_members  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams, split_by_date  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.match_model import TOOLS, tools_of  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import L2, TOURNAMENT_WEIGHT, build_vocab, recent_records, replay_rows, root_of, tournament_rows  # noqa: E402
from src.usage import load_usage  # noqa: E402
from scripts.regulation_start_lab import PriorModel, queries, ranks  # noqa: E402

FMT = CURRENT.id
ABUSERS = {"swiftswim": "rain abuser", "chlorophyll": "sun abuser", "solarpower": "sun abuser",
           "sandrush": "sand abuser", "sandforce": "sand abuser", "slushrush": "snow abuser"}
BINS = [0, 100, 200, 400, 800, 1600, 1e9]
BOOT = 1000


def features(vocab, dex, usage) -> np.ndarray:
    """One row per Pokemon: what it is, from its most common set."""
    types = sorted({t for s in dex.species.values() for t in s.types}) if hasattr(dex, "species") else []
    names = (["type: " + t for t in types] + ["speed <50", "speed 50-79", "speed 80-99", "speed 100+",
             "physical", "special", "mega"] + [f"tool: {t}" for t in TOOLS] + sorted(set(ABUSERS.values())))
    col = {n: i for i, n in enumerate(names)}
    F = np.zeros((len(vocab), len(names)))
    for i, root in enumerate(vocab):
        sp = dex.get_species(root)
        pset = usage.popular_set(sp.name, dex) if sp else None
        if pset is None:
            continue
        m = build_members([pset], dex, evolve=0 if pset.is_mega(dex) else None)[0]
        form = m.form
        for t in form.types:
            if "type: " + t in col:
                F[i, col["type: " + t]] = 1
        spe = form.base_stats["spe"]
        F[i, col["speed <50" if spe < 50 else "speed 50-79" if spe < 80 else "speed 80-99" if spe < 100
                 else "speed 100+"]] = 1
        F[i, col["physical" if form.base_stats["atk"] >= form.base_stats["spa"] else "special"]] = 1
        F[i, col["mega"]] = float(form.is_mega)
        for t in tools_of(m):
            F[i, col[f"tool: {t}"]] = 1
        if m.ability_id in ABUSERS:
            F[i, col[ABUSERS[m.ability_id]]] = 1
    return F


def feature_prior(model, F, ridge: float = 10.0) -> np.ndarray:
    """W0 = F A F': A from a weighted ridge regression of the fitted pulls on feature-pair products."""
    v, k = F.shape
    iu = np.triu_indices(v, 1)
    conf = model.counts / (model.counts + 100.0)
    w = np.minimum(conf[iu[0]], conf[iu[1]])            # how much data backs each fitted pull
    y = model.W[iu]
    X = np.einsum("pi,pj->pij", F[iu[0]], F[iu[1]])
    X = (X + X.transpose(0, 2, 1)).reshape(len(y), k * k) / 2
    keep = w > 0.05
    Xk, yk, wk = X[keep], y[keep], w[keep]
    A = np.linalg.solve(Xk.T @ (Xk * wk[:, None]) + ridge * np.eye(k * k), Xk.T @ (wk * yk)).reshape(k, k)
    A = (A + A.T) / 2
    W0 = F @ A @ F.T
    np.fill_diagonal(W0, 0.0)
    return W0


def main():
    dex, usage = load_dex(CURRENT.regulation), load_usage(FMT)
    teams = load_tournament_teams(CURRENT.regulation, dex)
    train, test = split_by_date(teams)
    pairs_from, tune = split_by_date(train, 0.4)
    cut = datetime.fromisoformat(min(t["date"] for t in tune)).replace(tzinfo=timezone.utc).timestamp()
    recs = recent_records([r for f in (FMT, FMT + "bo3") for r in load_records(f)], end=cut - 1)
    rows = tournament_rows(pairs_from, dex, TOURNAMENT_WEIGHT) + replay_rows(recs, dex)
    vocab = build_vocab(rows)
    base = PriorModel(vocab).fit(rows, l2=L2)
    F = features(vocab, dex, usage)
    print(f"{len(vocab)} Pokemon, {F.shape[1]} features; fitted on {len(pairs_from)} tournament teams + "
          f"{len(recs)} replays")
    roots = lambda ts: [sorted({root_of(p.species, dex) for p in t["sets"]} - {None}) for t in ts]  # noqa: E731
    tune_t = [t for t in roots(tune) if len(t) == 6]
    test_t = [t for t in roots(test) if len(t) == 6]
    count = dict(zip(vocab, base.counts))

    def evaluate(model, ts):
        q = queries(ts)
        universe = sorted(set(vocab) | {r for t in ts for r in t})
        rr = ranks(model, q, universe)
        least = np.array([min(count.get(r, 0.0) for r in ctx) for _, _, ctx in q])
        team = np.array([n for n, _, _ in q])
        return rr, least, team

    # prior strength (scale of W0) and its ridge, chosen on the tuning tournaments
    best = None
    rb_tune = evaluate(base, tune_t)[0]
    for ridge in (3.0, 30.0):
        W0 = feature_prior(base, F, ridge)
        for scale in (0.5, 1.0):
            m = PriorModel(vocab, scale * W0).fit(rows, l2=L2)
            gain = (1 / evaluate(m, tune_t)[0]).mean() - (1 / rb_tune).mean()
            print(f"  tuning: ridge {ridge}, strength {scale}: MRR {gain:+.4f}", flush=True)
            if best is None or gain > best[0]:
                best = (gain, ridge, scale, m)
    _, ridge, scale, prior_m = best
    rb, least, team = evaluate(base, test_t)
    rp, _, _ = evaluate(prior_m, test_t)
    rng = np.random.default_rng(0)
    boots = [rng.integers(0, len(test_t), len(test_t)) for _ in range(BOOT)]
    print(f"\ntest: {len(test_t)} newest tournament teams; prior ridge {ridge}, strength {scale}")
    print(f"{'least-seen of the five':>24s} {'queries':>8s}  top 10: shipped -> prior    MRR gain (95%)")
    for lo, hi in [(0, 1e9)] + list(zip(BINS, BINS[1:])):
        m = (least >= lo) & (least < hi)
        if not m.any():
            continue
        d = np.bincount(team[m], (1 / rp - 1 / rb)[m], minlength=len(test_t))
        c = np.bincount(team[m], minlength=len(test_t))
        bs = [d[b].sum() / max(c[b].sum(), 1) for b in boots]
        label = "all" if hi == 1e9 and lo == 0 else f"{lo:.0f}-{hi if hi < 1e9 else 'up':}"
        print(f"{label:>24s} {int(m.sum()):8d}  {(rb[m] <= 10).mean():6.1%} -> {(rp[m] <= 10).mean():6.1%}"
              f"   {(1 / rp - 1 / rb)[m].mean():+.4f} ({np.percentile(bs, 2.5):+.4f} to {np.percentile(bs, 97.5):+.4f})")


if __name__ == "__main__":
    main()
