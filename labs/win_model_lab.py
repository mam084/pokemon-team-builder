"""
win_model_lab.py - two fixes to the learned match model (src/match_model.py), tested the way it's trained.

1. Support tools are counted per Pokemon ("tool: Wide Guard" = how many of your six carry it, minus theirs),
   so each extra copy earns the same points as the first. Variants: has-it (0/1 per side), and the square
   root of the count (a second copy counts ~0.4 of the first).
2. Features are standardized by their root-mean-square before the L2 penalty, so a feature that differs in
   only ~1% of matches (Paralysis) is barely penalized per raw unit and can take a huge weight (-16 points
   per Pokemon). Variant: a floor on that scale for tool features, so rare tools are shrunk like common ones.

Same procedure as src/match_model.train_and_report: L2 logistic on skill + team features, both
orientations, C chosen by forward-chaining CV inside the training period (oldest 70% of tournaments),
judged once on the newest 30%. Paired bootstrap over test matches against the shipped setup.

    python labs/win_model_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import match_model as M  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.usage import load_usage  # noqa: E402

TOOL_COLS = [f"tool: {t}" for t in M.TOOLS]


def side_counts(regulation: str) -> dict:
    """(tournament, player) -> {tool: count} from the same members the dataset used."""
    dex, usage = load_dex(regulation), load_usage(CURRENT.id, recent=False)
    teams = {(t["tournament"], t["player"]): t for t in load_tournament_teams(regulation, dex, usage=usage)}
    members = M._sides(teams, dex)
    out = {}
    for k, ms in members.items():
        tools = [M.tools_of(m) for m in ms]
        out[k] = {f"tool: {t}": float(sum(t in ts for ts in tools)) for t in M.TOOLS}
    return out


def transformed(df: pd.DataFrame, counts: dict, f) -> pd.DataFrame:
    out = df.copy()
    a = [counts.get((t, p)) for t, p in zip(df["tournament"], df["p1"])]
    b = [counts.get((t, p)) for t, p in zip(df["tournament"], df["p2"])]
    ok = np.array([x is not None and y is not None for x, y in zip(a, b)])
    for col in TOOL_COLS:
        va = np.array([x[col] if x else 0.0 for x in a])
        vb = np.array([y[col] if y else 0.0 for y in b])
        out.loc[ok, col] = (f(va) - f(vb))[ok]
    # the context terms use "has Trick Room / Tailwind" already (min(count, 1)); unchanged
    return out


class FloorLogit(M.Logit):
    """M.Logit with a floor on the scale of the tool columns (so rare tools are shrunk like common ones)."""

    def __init__(self, c, floor, tool_idx):
        super().__init__(c)
        self.floor, self.tool_idx = floor, tool_idx

    def fit(self, x, y):
        from sklearn.linear_model import LogisticRegression
        self.scale_ = np.sqrt((x ** 2).mean(axis=0)) + 1e-9
        self.scale_[self.tool_idx] = np.maximum(self.scale_[self.tool_idx], self.floor)
        z = x / self.scale_
        model = LogisticRegression(C=self.c, fit_intercept=False, max_iter=2000)
        model.fit(np.vstack([z, -z]), np.concatenate([y, 1 - y]))
        self.coef_ = model.coef_[0] / self.scale_
        return self


def run(df, features, make, label, train_mask, test_mask, y):
    train = df[train_mask]
    best = None
    for c in (0.0003, 0.001, 0.003, 0.01, 0.03):
        cv = M.forward_cv(train, lambda part, full: part[features].to_numpy(float), lambda c=c: make(c))
        if best is None or cv < best[0]:
            best = (cv, c)
    model = make(best[1]).fit(train[features].to_numpy(float), y[train_mask])
    p = model.predict(df[test_mask][features].to_numpy(float))
    coef = dict(zip(features, model.coef_))
    return {"label": label, "cv": best[0], "C": best[1], "p": p, "coef": coef}


def main():
    reg = CURRENT.regulation
    df = M.add_skill(M.build_dataset(reg, CURRENT.id, verbose=True), reg)
    counts = side_counts(reg)
    y = df["won"].to_numpy(float)
    tr, te = M.time_split(df)
    features = M.SKILL + M.FEATURES
    tool_idx = [features.index(c) for c in TOOL_COLS]
    variants = {
        "shipped: count per Pokemon": (df, lambda c: M.Logit(c)),
        "has it (0/1)": (transformed(df, counts, lambda v: np.minimum(v, 1)), lambda c: M.Logit(c)),
        "sqrt(count)": (transformed(df, counts, np.sqrt), lambda c: M.Logit(c)),
    }
    for floor in (0.3, 0.5):
        variants[f"count, rare-tool floor {floor}"] = (df, (lambda fl: lambda c: FloorLogit(c, fl, tool_idx))(floor))
        variants[f"has it, rare-tool floor {floor}"] = (transformed(df, counts, lambda v: np.minimum(v, 1)),
                                                     (lambda fl: lambda c: FloorLogit(c, fl, tool_idx))(floor))
        variants[f"sqrt, rare-tool floor {floor}"] = (transformed(df, counts, np.sqrt),
                                                   (lambda fl: lambda c: FloorLogit(c, fl, tool_idx))(floor))
    res = [run(d, features, mk, name, tr, te, y) for name, (d, mk) in variants.items()]
    # skill-only baseline, for "does the team add anything"
    skill = run(df, M.SKILL, lambda c: M.Logit(c), "skill only", tr, te, y)
    yt = y[te]
    base_l = M._losses(res[0]["p"], yt)
    skill_l = M._losses(skill["p"], yt)
    rng = np.random.default_rng(0)
    idx = [rng.integers(0, len(yt), len(yt)) for _ in range(2000)]
    print(f"\ntrain {int(tr.sum())} matches, test {int(te.sum())} (newest 30%)")
    print(f"{'variant':34s} {'CV loss':>8s} {'test loss':>9s} {'AUC':>6s}  vs shipped (loss drop, 95%)       "
          f"team beyond skill (95%)      Wide Guard  Paralysis  Setup  (pts per unit)")
    for r in res:
        l = M._losses(r["p"], yt)
        d = base_l - l
        dd = [d[i].mean() for i in idx]
        g = skill_l - l
        gg = [g[i].mean() for i in idx]
        auc = M.metrics(r["p"], yt)["auc"]
        print(f"{r['label']:34s} {r['cv']:.5f} {l.mean():9.5f} {auc:6.3f}  {d.mean():+.5f} ({np.percentile(dd, 2.5):+.5f} "
              f"to {np.percentile(dd, 97.5):+.5f})  {g.mean():+.5f} ({np.percentile(gg, 2.5):+.5f} to "
              f"{np.percentile(gg, 97.5):+.5f})  {r['coef']['tool: Wide Guard'] * 25:+6.2f}  "
              f"{r['coef']['tool: Paralysis'] * 25:+7.2f}  {r['coef']['tool: Setup'] * 25:+5.2f}")


if __name__ == "__main__" and "--swaps" not in sys.argv:
    main()


# --------------------------------------------------------------------------
# Does a version pick better swaps? (`--swaps`; needs /tmp/core_games.pkl from swap_quality_lab's core pass)
# --------------------------------------------------------------------------
def swaps_check():
    """Each version, fitted on all tournaments (replay outcomes are out of sample for every one), scores
    the same-five / different-sixth pairs from rated replays (labs/swap_quality_lab.py). Trust bounds
    off for all, so they're compared as fitted."""
    import pickle
    from collections import defaultdict
    from src import team_rating as R
    from src.matchup import build_archetypes
    from labs.swap_quality_lab import wcorr
    reg = CURRENT.regulation
    df = M.add_skill(M.build_dataset(reg, CURRENT.id, verbose=False), reg)
    counts = side_counts(reg)
    y = df["won"].to_numpy(float)
    tr, _ = M.time_split(df)
    features = M.SKILL + M.FEATURES
    tool_idx = [features.index(c) for c in TOOL_COLS]
    has = lambda v: np.minimum(v, 1)  # noqa: E731
    versions = {
        "shipped: count per Pokemon": (df, None, lambda c: M.Logit(c)),
        "has it (0/1)": (transformed(df, counts, has), has, lambda c: M.Logit(c)),
        "has it, rare-tool floor 0.5": (transformed(df, counts, has), has, lambda c: FloorLogit(c, 0.5, tool_idx)),
        "count, rare-tool floor 0.5": (df, None, lambda c: FloorLogit(c, 0.5, tool_idx)),
    }
    games, _ = pickle.load(open("/tmp/core_games.pkl", "rb"))
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0.0, None]))
    for _, roots, species, res in games:
        for i in range(6):
            core = frozenset(roots[:i] + roots[i + 1:])
            a = agg[core][roots[i]]
            a[0] += 1
            a[1] += res
            if a[2] is None:
                a[2] = species
    pairs = []
    for core, d in agg.items():
        six = [(s, v) for s, v in d.items() if v[0] >= 20]
        for i in range(len(six)):
            for j in range(i + 1, len(six)):
                (x, vx), (yy, vy) = six[i], six[j]
                pairs.append((core, vx[2], vy[2], vy[1] / vy[0] - vx[1] / vx[0], 1 / (1 / vx[0] + 1 / vy[0])))
    dex, usage = load_dex(reg), load_usage(CURRENT.id)
    arch = build_archetypes(usage, dex, team_size=6)
    orig_profile = M.side_profile
    keys = sorted({id(p[0]) for p in pairs})
    kid = {k: i for i, k in enumerate(keys)}
    byc = defaultdict(list)
    for i, p in enumerate(pairs):
        byc[kid[id(p[0])]].append(i)
    rng = np.random.default_rng(0)
    ks = list(byc)
    boots = [np.concatenate([byc[ks[k]] for k in rng.integers(0, len(ks), len(ks))]) for _ in range(1000)]
    obs = np.array([p[3] for p in pairs])
    w = np.array([p[4] for p in pairs])
    base = None
    print(f"\n{len(pairs)} same-five pairs in {len(keys)} cores (each sixth 20+ games)")
    for name, (d, f, make) in versions.items():
        train = d[tr]
        c = min((M.forward_cv(train, lambda part, full: part[features].to_numpy(float), lambda c=c: make(c)), c)
                for c in (0.001, 0.003, 0.01))[1]
        mdl = make(c).fit(d[features].to_numpy(float), y)
        model = {"model": {"features": features, "species": [], "coef": list(mdl.coef_)}}

        def profile(members, f=f):
            prof = orig_profile(members)
            if f is not None:
                for col in TOOL_COLS:
                    prof[col] = float(f(np.array(prof[col])))
            return prof
        M.side_profile = profile
        sides, weights = R.meta_sides(arch, usage, dex)
        cache = {}

        def chance(species):
            k = frozenset(species)
            if k not in cache:
                sets = [s for s in (usage.popular_set(n, dex) for n in species) if s is not None]
                cache[k] = R.learned_vs_meta(sets, dex, usage, model, sides, weights) if len(sets) == 6 else None
            return cache[k]
        pred = np.array([(chance(b) or 0) - (chance(a) or 0) for _, a, b, _, _ in pairs])
        M.side_profile = orig_profile
        cr = wcorr(pred, obs, w)
        cs = np.array([wcorr(pred[b], obs[b], w[b]) for b in boots])
        line = f"  {name:30s} win chance alone: corr {cr:+.3f} ({np.percentile(cs, 2.5):+.3f} to {np.percentile(cs, 97.5):+.3f})"
        if base is None:
            base = cs
        else:
            dd = cs - base
            line += f"  vs shipped {np.mean(dd):+.3f} ({np.percentile(dd, 2.5):+.3f} to {np.percentile(dd, 97.5):+.3f})"
        print(line, flush=True)


if __name__ == "__main__" and "--swaps" in sys.argv:
    swaps_check()
