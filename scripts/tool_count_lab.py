"""Does a second (third...) Pokemon with the same support tool help? (Nov 2026)

The match model counts tool users linearly, so the swap search stacked them: four Wide Guard users.
This checks diminishing returns two ways:

1. Tournaments: refit the match model with tool counts capped / square-rooted / logged, fitted on
   older matches and judged on the newest week (paired bootstrap on log loss).
2. Bo3 replays (open team sheets, never used to fit the match model): fit "first user" and "each
   extra user" per tool with both players' ladder ratings, bootstrapped by player; then use the
   tournament-fitted tool effects (linear vs capped) to predict the Bo3 games.

    python scripts/tool_count_lab.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression

from src import match_model as M
from src.analysis import build_members
from src.dex import load_dex
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.replays import load_records
from src.usage import load_usage

TOOLS = [f for f in M.SUPPORT]
TRANSFORMS = {"linear (shipped)": lambda x: x, "cap at 1": lambda x: np.minimum(x, 1),
              "cap at 2": lambda x: np.minimum(x, 2), "sqrt": np.sqrt, "log(1+n)": np.log1p}


def tournament_counts():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    prof = {}
    for t in load_tournament_teams(reg, dex, usage=usage):
        megas = [i for i, p in enumerate(t["sets"]) if p.is_mega(dex)]
        prof[(t["tournament"], t["player"])] = M.side_profile(
            build_members(t["sets"], dex, evolve=megas[0] if megas else None))
    df = M.add_skill(M.build_dataset(verbose=False), reg)
    df = df[[(t, a) in prof and (t, b) in prof for t, a, b in zip(df.tournament, df.p1, df.p2)]].reset_index(drop=True)
    A = pd.DataFrame([prof[(t, p)] for t, p in zip(df.tournament, df.p1)])
    B = pd.DataFrame([prof[(t, p)] for t, p in zip(df.tournament, df.p2)])
    return df, A, B, pd.DataFrame(prof.values())


def tournaments(df, A, B, allp):
    print("Share of tournament team sheets with n users:")
    for t in ["tool: Wide Guard", "tool: Setup", "tool: Sleep", "tool: Intimidate", "tool: Fake Out"]:
        print(f"  {t:20s}", allp[t].value_counts(normalize=True).sort_index().round(3).to_dict())
    y = df["won"].to_numpy(float)
    tr, te = M.time_split(df)
    feats = M.SKILL + M.FEATURES
    losses = {}
    print("\nTool counts transformed, fitted on older matches, tested on the newest week:")
    for name, f in TRANSFORMS.items():
        d = df.copy()
        for t in TOOLS:
            d[t] = f(A[t].to_numpy()) - f(B[t].to_numpy())
        cv, c, w = M._choose(d[tr], feats, [])
        p = M.Logit(c, 0, w).fit(M._design(d[tr], [], feats), y[tr]).predict(M._design(d[te], [], feats))
        losses[name] = M._losses(p, y[te])
        line = f"  {name:18s} CV {cv:.5f}  test log loss {losses[name].mean():.5f}"
        if name != "linear (shipped)":
            lo, hi = M._bootstrap_gain(losses["linear (shipped)"], losses[name])
            line += f"  gain vs linear {lo:+.5f} to {hi:+.5f}"
        print(line)


def bo3_sides():
    idn = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    rows = []
    for r in load_records(f"{CURRENT.id}bo3"):
        sh = r.get("sheets") or {}
        if set(sh) != {"p1", "p2"} or r["winner"] not in ("p1", "p2"):
            continue
        ra, rb = r["players"]["p1"].get("rating"), r["players"]["p2"].get("rating")
        if not ra or not rb:
            continue
        row = {"player": r["players"]["p1"]["name"], "won": int(r["winner"] == "p1"),
               "rating": (ra - rb) / 400 * np.log(10)}
        for side in ("p1", "p2"):
            for t, (moves, abilities) in M.TOOLS.items():
                row[f"{side} {t}"] = sum(bool({idn(x) for x in m["moves"]} & moves or idn(m.get("ability", "")) in abilities)
                                         for m in sh[side])
        rows.append(row)
    return pd.DataFrame(rows)


def bo3(g, df, A, B):
    # priority isn't readable from team sheets without the dex's move data, so it's left out here
    tools = [t for t in M.TOOLS if t != "Priority attack"]
    y = g.won.to_numpy(float)
    X = {"rating": g.rating}
    for t in tools:
        a, b = g[f"p1 {t}"], g[f"p2 {t}"]
        X[t + " first"] = np.minimum(a, 1) - np.minimum(b, 1)
        X[t + " extra"] = np.maximum(a - 1, 0) - np.maximum(b - 1, 0)
    X = pd.DataFrame(X)

    def fit(idx):
        x = X.values[idx]
        m = LogisticRegression(C=1.0, fit_intercept=False, max_iter=3000)
        m.fit(np.vstack([x, -x]), np.r_[y[idx], 1 - y[idx]])
        return m.coef_[0]

    players = g.player.values
    groups = {p: np.flatnonzero(players == p) for p in np.unique(players)}
    keys = list(groups)
    rng = np.random.default_rng(0)
    draws = [np.concatenate([groups[k] for k in rng.choice(keys, len(keys))]) for _ in range(100)]
    full, boot = fit(np.arange(len(y))), np.array([fit(d) for d in draws])
    lo, hi = np.percentile(boot, 5, 0), np.percentile(boot, 95, 0)
    col = {c: i for i, c in enumerate(X.columns)}
    print(f"\nBo3, {len(y):,} rated games: win-chance points, 90% player-bootstrap range")
    for t in tools:
        f, e = col[t + " first"], col[t + " extra"]
        print(f"  {t:14s} first {25 * full[f]:+5.1f} ({25 * lo[f]:+.1f} to {25 * hi[f]:+.1f})   each extra "
              f"{25 * full[e]:+5.1f} ({25 * lo[e]:+.1f} to {25 * hi[e]:+.1f})  [extra differs in "
              f"{(X.iloc[:, e] != 0).mean():.1%} of games]")

    # tournament-fitted tool effects (all tournaments: Bo3 is the held-out set) on Bo3 games
    feats = M.SKILL + M.FEATURES
    yt = df["won"].to_numpy(float)

    def ll(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    def with_rating(z):   # only the rating scale is fitted on Bo3
        f = lambda a: ll(1 / (1 + np.exp(-(a * g.rating.values + z)))).mean()
        a = minimize_scalar(f, bounds=(0, 3), method="bounded").x
        return ll(1 / (1 + np.exp(-(a * g.rating.values + z))))

    L = {"ratings only": with_rating(np.zeros(len(y)))}
    for name, cap in (("linear", None), ("cap at 1", 1), ("cap at 2", 2)):
        d = df.copy()
        for t in TOOLS:
            a, b = A[t].to_numpy(), B[t].to_numpy()
            d[t] = (np.minimum(a, cap) - np.minimum(b, cap)) if cap else a - b
        _, c, w = M._choose(d, feats, [])
        co = dict(zip(feats, M.Logit(c, 0, w).fit(d[feats].to_numpy(float), yt).coef_))
        z = np.zeros(len(y))
        for t in tools:
            a, b = g[f"p1 {t}"].to_numpy(), g[f"p2 {t}"].to_numpy()
            z += co["tool: " + t] * ((np.minimum(a, cap) - np.minimum(b, cap)) if cap else a - b)
        L[name] = with_rating(z)
    print("\nTournament-fitted tool effects predicting Bo3 games (log loss, lower is better):")
    for k, v in L.items():
        line = f"  {k:14s} {v.mean():.5f}"
        if k != "linear":
            gains = [(L["linear"][d] - v[d]).mean() for d in draws]
            line += f"  gain vs linear {np.percentile(gains, 2.5):+.5f} to {np.percentile(gains, 97.5):+.5f}"
        print(line)


if __name__ == "__main__":
    df, A, B, allp = tournament_counts()
    tournaments(df, A, B, allp)
    bo3(bo3_sides(), df, A, B)
