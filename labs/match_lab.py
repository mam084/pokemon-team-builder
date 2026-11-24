"""Experiments for the learned match model. Caches every match's raw pair parts once, then
tries feature sets / models; all judged on the newest held-out tournaments (time_split)."""
import sys, json, pickle, time, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from src import match_model as M
from src.formats import CURRENT
from src.dex import load_dex
from src.usage import load_usage
from src.evaluate import load_tournament_teams

PARTS = M.CACHE_DIR / f"{CURRENT.regulation}_match_parts.pkl"


def parts_cache():
    if PARTS.exists():
        return pickle.loads(PARTS.read_bytes())
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    teams = {(t["tournament"], t["player"]): t for t in load_tournament_teams(reg, dex, usage=usage)}
    matches = json.loads((M.TOURNAMENT_DIR / f"{reg}_matches.json").read_text())["matches"]
    used = {(m["tournament"], p) for m in matches for p in (m["p1"], m["p2"])}
    teams = {k: v for k, v in teams.items() if k in used}
    members = M._sides(teams, dex)
    out, t0 = {}, time.time()
    for n, m in enumerate(matches):
        a, b = (m["tournament"], m["p1"]), (m["tournament"], m["p2"])
        if a not in teams or b not in teams or m["winner"] not in (m["p1"], m["p2"]):
            continue
        out[(m["tournament"], m["p1"], m["p2"])] = M.pair_parts(members[a], members[b])
        if n % 2000 == 0:
            print(n, f"{time.time()-t0:.0f}s", flush=True)
    PARTS.write_bytes(pickle.dumps(out))
    return out


def extra_features(p: dict) -> dict:
    a, b = p["a_pct"], p["b_pct"]                    # a[i, j]: my i hits their j; b[i, j]: their j hits my i
    ha, hb = M._hits(a), M._hits(b)
    faster, slower = p["a_spe"] > p["b_spe"], p["a_spe"] < p["b_spe"]
    a_wins = (ha < hb) | ((ha == hb) & faster)       # my i beats their j one-on-one
    b_wins = (hb < ha) | ((ha == hb) & slower)
    f = {}
    f["answers"] = (a_wins.any(axis=0).mean() - b_wins.any(axis=1).mean())
    f["answers (2+)"] = ((a_wins.sum(axis=0) >= 2).mean() - (b_wins.sum(axis=1) >= 2).mean())
    f["1v1 wins (share)"] = a_wins.mean() - b_wins.mean()
    f["walled"] = ((b.max(axis=0) < 25).mean() - (a.max(axis=1) < 25).mean())   # their mons that wall... flipped below
    f["walled"] = -f["walled"]
    f["super effective share"] = 0.0
    lg = np.log2(hb / ha)
    f["matchup log-hits mean"] = float(np.clip(lg, -3, 3).mean())
    return f


def main():
    df = M.add_skill(M.build_dataset(verbose=False), CURRENT.regulation)
    parts = parts_cache()
    ex = pd.DataFrame([extra_features(parts[(r.tournament, r.p1, r.p2)]) for r in df.itertuples()])
    df = pd.concat([df.reset_index(drop=True), ex], axis=1)
    df["matchup score^3"] = df["matchup score"] ** 3
    df["bring-4 score^3"] = df["bring-4 score"] ** 3
    df.to_pickle(M.CACHE_DIR / "lab_df.pkl")
    y = df["won"].to_numpy(float); tr, te = M.time_split(df); train = df[tr]; yt = y[te]
    base_feats = M.SKILL + M.FEATURES
    EXTRA = list(ex.columns.drop("super effective share"))

    def logit(cols):
        cv, c, w = M._choose(train, cols, [])
        m = M.Logit(c, 0, w).fit(M._design(train, [], cols), y[tr])
        return m.predict(M._design(df[te], [], cols)), c, cv

    def trees(cols, **kw):
        m = M.Trees(**kw).fit(train[cols].to_numpy(float), y[tr])
        return m.predict(df[te][cols].to_numpy(float)), None, None

    team_only_pred = logit(M.FEATURES)[0]
    lopsided = np.abs(team_only_pred - 0.5) >= np.quantile(np.abs(team_only_pred - 0.5), 0.8)
    base, *_ = logit(base_feats); lb = M._losses(base, yt)
    res = {}
    def report(name, pred, c=None, cv=None):
        g = M._bootstrap_gain(lb, M._losses(pred, yt))
        mt = M.metrics(pred, yt); ml = M.metrics(pred[lopsided], yt[lopsided])
        res[name] = (mt, g)
        print(f"{name:42s} acc {mt['accuracy']:.4f} ll {mt['log_loss']:.5f} auc {mt['auc']:.4f} | "
              f"lopsided acc {ml['accuracy']:.3f} ll {ml['log_loss']:.4f} | gain95 [{g[0]:+.5f},{g[1]:+.5f}] C={c} cv={cv}", flush=True)
    report("current", base)
    for e in EXTRA:
        report(f"+ {e}", *logit(base_feats + [e]))
    report("+ all extras", *logit(base_feats + EXTRA))
    report("+ cubes", *logit(base_feats + ["matchup score^3", "bring-4 score^3"]))
    report("trees", *trees(base_feats))
    report("trees + extras", *trees(base_feats + EXTRA))
    report("trees slow", *trees(base_feats + EXTRA, learning_rate=0.01, max_iter=600, max_leaf_nodes=7, min_samples_leaf=200))


if __name__ == "__main__":
    main()
