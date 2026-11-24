"""Does training team effects on rated replays (as well as tournaments) predict held-out tournament
matches better? Validation picks settings inside the training period; the test is touched once."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from src import match_model as M

tour = pd.read_pickle(M.CACHE_DIR / "lab_df.pkl")
rep = pd.read_pickle(M.CACHE_DIR / "regmc_replay_match_rows.pkl")
TEAM = M.FEATURES
EXTRA = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] else []
tour["rating diff"] = 0.0
for c in M.SKILL:
    rep[c] = 0.0
for c in EXTRA:
    if c not in rep:
        raise SystemExit(f"{c} missing in replay rows")
COLS = M.SKILL + ["rating diff"] + TEAM + EXTRA


class WLogit:
    def __init__(self, c): self.c = c
    def fit(self, x, y, w):
        self.s = np.sqrt((x ** 2).mean(axis=0)) + 1e-9
        z = x / self.s
        m = LogisticRegression(C=self.c, fit_intercept=False, max_iter=3000)
        m.fit(np.vstack([z, -z]), np.concatenate([y, 1 - y]), sample_weight=np.concatenate([w, w]))
        self.coef_ = m.coef_[0] / self.s
        return self
    def predict(self, x): return 1 / (1 + np.exp(-(x @ self.coef_)))


def fit(tr_t, tr_r, c, wt, cols=COLS):
    x = np.vstack([tr_t[cols].to_numpy(float), tr_r[cols].to_numpy(float)]) if len(tr_r) else tr_t[cols].to_numpy(float)
    y = np.concatenate([tr_t["won"].to_numpy(float), tr_r["won"].to_numpy(float)])
    w = np.concatenate([np.full(len(tr_t), wt), np.ones(len(tr_r))])
    return WLogit(c).fit(x, y, w)


tr, te = M.time_split(tour)
t_train, t_test = tour[tr], tour[te]
test_start = t_test["date"].min()
r_train = rep[rep["date"] < test_start]
r_test = rep[rep["date"] >= test_start]
# validation inside the training period: newest quarter of training tournaments
order = t_train.groupby("tournament")["date"].first().sort_values(kind="stable").index.tolist()
val_t = set(order[-len(order) // 4:])
v = t_train["tournament"].isin(val_t).to_numpy()
val_start = t_train[v]["date"].min()
best = {}
for name, use_rep in [("tournaments only", False), ("tournaments + replays", True)]:
    for c in (0.001, 0.003, 0.01, 0.03, 0.1):
        for wt in ((1.0, 3.0, 10.0) if use_rep else (1.0,)):
            m = fit(t_train[~v], r_train[r_train["date"] < val_start] if use_rep else rep.iloc[:0], c, wt)
            ll = M.metrics(m.predict(t_train[v][COLS].to_numpy(float)), t_train[v]["won"].to_numpy(float))["log_loss"]
            if name not in best or ll < best[name][0]:
                best[name] = (ll, c, wt)
    print(name, "validation pick", best[name], flush=True)

yt = t_test["won"].to_numpy(float)
preds = {}
for name, (ll, c, wt) in best.items():
    m = fit(t_train, r_train if "replays" in name else rep.iloc[:0], c, wt)
    preds[name] = (m, m.predict(t_test[COLS].to_numpy(float)))
base = M._losses(preds["tournaments only"][1], yt)
team_pred = preds["tournaments only"][0]
for name, (m, p) in preds.items():
    g = M._bootstrap_gain(base, M._losses(p, yt))
    mt = M.metrics(p, yt)
    pr = m.predict(r_test[COLS].to_numpy(float)); mr = M.metrics(pr, r_test["won"].to_numpy(float))
    print(f"{name:24s} TOURNAMENT TEST acc {mt['accuracy']:.4f} ll {mt['log_loss']:.5f} auc {mt['auc']:.4f} "
          f"gain95 [{g[0]:+.5f},{g[1]:+.5f}] | replay test acc {mr['accuracy']:.4f} ll {mr['log_loss']:.5f} auc {mr['auc']:.4f}")
    coef = dict(zip(COLS, m.coef_))
    print("   key coefs (pts per unit):", {k: round(25 * coef[k], 2) for k in ["skill (Elo)", "rating diff", "matchup score", "bring-4 score", "best damage (mean %)", "outspeeds (share)", "bulk (mean)"] + EXTRA})
# team-only part: drop skill, see how much team features alone predict on test
for name, (m, p) in preds.items():
    coef = m.coef_.copy(); coef[[COLS.index(c) for c in M.SKILL + ["rating diff"]]] = 0
    pt = 1 / (1 + np.exp(-(t_test[COLS].to_numpy(float) @ coef)))
    mt = M.metrics(pt, yt); mr = M.metrics(1 / (1 + np.exp(-(r_test[COLS].to_numpy(float) @ coef))), r_test["won"].to_numpy(float))
    print(f"{name:24s} team part alone: tournament acc {mt['accuracy']:.4f} auc {mt['auc']:.4f} | replay acc {mr['accuracy']:.4f} auc {mr['auc']:.4f}")
import pickle; pickle.dump({k: (dict(zip(COLS, m.coef_))) for k, (m, p) in preds.items()}, open("/tmp/lab2_coefs.pkl", "wb"))
