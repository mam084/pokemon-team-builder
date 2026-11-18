"""Does the app's opinion of a team line up with how it actually did? Teams from the newest
tournaments (the held-out week) are scored by models fitted only on data from before it."""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from src import match_model as M
from src.analysis import mega_variants
from src.formats import CURRENT
from src.dex import load_dex
from src.usage import load_usage
from src.evaluate import load_tournament_teams
from src.matchup import build_archetypes, opponent_members
from src.swaps import SwapEngine
from src.synergy import (TeammateModel, tournament_rows, replay_rows, recent_records, build_vocab, root_of,
                         L2, TOURNAMENT_WEIGHT)
from src.replays import load_records
import datetime as dt


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    teams = load_tournament_teams(reg, dex, usage=usage)
    df = M.add_skill(M.build_dataset(verbose=False), reg)
    tr, te = M.time_split(df)
    cut = df[te]["date"].min()
    test_t = set(df[te]["tournament"])
    print("held-out week starts", cut, "|", len(test_t), "tournaments")

    # teammate model from data before the cut
    before = [t for t in teams if t["date"] < cut]
    end = dt.datetime.fromisoformat(cut).replace(tzinfo=dt.timezone.utc).timestamp() - 1
    recs = recent_records([r for f in CURRENT.replays for r in load_records(f)], end=end)
    rows = tournament_rows(before, dex, weight=TOURNAMENT_WEIGHT) + replay_rows(recs, dex)
    tm = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)

    # learned match model from matches before the cut
    feats = M.SKILL + M.FEATURES
    _, c, w = M._choose(df[tr], feats, [])
    lm = M.Logit(c, 0, w).fit(M._design(df[tr], [], feats), df[tr]["won"].to_numpy(float))
    model = {"model": {"features": feats, "species": [], "coef": list(lm.coef_)}}

    archetypes = build_archetypes(usage, dex)
    engine = SwapEngine(archetypes, usage, dex, True)
    meta_sides = [M.team_side(opponent_members(a.members, usage, dex),
                              [s for s in (usage.popular_set(m, dex) for m in a.members) if s], dex, usage, None, meta=0.0)
                  for a in archetypes]
    weights = np.array([a.popularity for a in archetypes], float); weights /= weights.sum()

    out = {}
    for t in teams:
        if t["tournament"] not in test_t:
            continue
        sets = t["sets"]
        roots = [r for s in sets if (r := root_of(s.species, dex))]
        fc = [x["prob"] for x in tm.fit_check(roots) if x["prob"]]
        mine = [M.team_side(m, sets, dex, usage, None, meta=0.0) for _, m in mega_variants(sets, dex)]
        chances = np.array([max(M.predict_match(model, a, b) for a in mine) for b in meta_sides])
        out[(t["tournament"], t["player"])] = {
            "wins": t.get("wins") or 0, "losses": t.get("losses") or 0, "placing": t.get("placing") or 0,
            "players": t.get("players") or 0,
            "damage-calc score vs meta": engine.overall(sets),
            "learned win chance vs meta": float(chances @ weights),
            "teammate fit (typical team)": float(np.mean(np.log(fc))) if fc else np.nan,
            "popularity": float(np.mean([usage.species_usage(s.species, dex) for s in sets])),
        }
    T = pd.DataFrame.from_dict(out, orient="index")
    SIG = ["damage-calc score vs meta", "learned win chance vs meta", "teammate fit (typical team)", "popularity"]
    z = lambda c: (T[c] - T[c].mean()) / T[c].std()  # noqa: E731
    T["fit + learned (equal z)"] = z("teammate fit (typical team)") + z("learned win chance vs meta")
    T["fit + damage calc (equal z)"] = z("teammate fit (typical team)") + z("damage-calc score vs meta")
    SIG += ["fit + learned (equal z)", "fit + damage calc (equal z)"]
    for key, row in T.iterrows():
        out[key].update({k: row[k] for k in SIG[-2:]})
    g = T[(T.wins + T.losses) >= 4].copy()
    g["win rate"] = g.wins / (g.wins + g.losses)
    g["top cut"] = (g.players >= 16) & (g.placing > 0) & (g.placing <= 8)
    print(f"\nTEAM LEVEL: {len(g)} teams with 4+ games, {int(g['top cut'].sum())} top cuts")
    for s in SIG:
        r, pv = spearmanr(g[s], g["win rate"], nan_policy="omit")
        q = pd.qcut(g[s].rank(method="first"), 4, labels=False)
        wr = g.groupby(q)["win rate"].mean().values
        print(f"  {s:30s} spearman {r:+.3f} (p={pv:.3f}) | win rate by quarter low->high: "
              + " ".join(f"{x:.3f}" for x in wr)
              + f" | top-cut vs rest mean: {g[g['top cut']][s].mean():.4f} vs {g[~g['top cut']][s].mean():.4f}")

    # match level: does the higher-scoring team win, beyond the Elo gap?
    m = df[te].copy()
    for s in SIG:
        a = m.apply(lambda r: out.get((r.tournament, r.p1), {}).get(s, np.nan), axis=1)
        b = m.apply(lambda r: out.get((r.tournament, r.p2), {}).get(s, np.nan), axis=1)
        m[s] = a - b
    m = m.dropna(subset=SIG)
    y = m["won"].to_numpy(float)
    from sklearn.linear_model import LogisticRegression
    print(f"\nMATCH LEVEL: {len(m)} held-out matches")
    for s in SIG:
        x = m[s].to_numpy(float)
        auc = roc_auc_score(y, x)
        X = np.c_[m["skill (Elo)"], x / (x.std() + 1e-12)]
        boots = []
        rng = np.random.default_rng(0)
        tours = m["tournament"].unique()
        idx_by = {t: np.flatnonzero(m["tournament"].to_numpy() == t) for t in tours}
        for _ in range(300):
            idx = np.concatenate([idx_by[t] for t in rng.choice(tours, len(tours))])
            Xb = np.vstack([X[idx], -X[idx]]); yb = np.r_[y[idx], 1 - y[idx]]
            boots.append(LogisticRegression(C=1e4, fit_intercept=False, max_iter=2000).fit(Xb, yb).coef_[0][1])
        lo, hi = np.percentile(boots, [5, 95])
        print(f"  {s:30s} alone: higher-scoring team wins {np.mean((x > 0) == (y == 1)) if (x!=0).any() else float('nan'):.3f} (AUC {auc:.3f}) "
              f"| beyond Elo, +1 sd = {25*np.mean(boots):+.2f} pts (90% {25*lo:+.2f} to {25*hi:+.2f})")


if __name__ == "__main__":
    main()
