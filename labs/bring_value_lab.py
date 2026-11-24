"""Does the bring / lead model pick what *wins*, or only what players *choose*? (Nov 2026)

src/bring_model.py learns which four players bring and which two they lead (72% / 44% on held-out replays).
That's imitation. This asks whether following it is worth anything: on held-out replays (same chronological
split as the model: prior half for rates, third quarter to fit, last quarter to test), do players whose real
bring / lead overlaps more with a model's picks win more than their ratings predicted (Elo)?

  imitation      the shipped model: every side
  winners only   the same features, fitted only on sides that beat their rating that game
  weighted       every side, weighted by 1 + 2 x (won - rating-predicted), floored at 0

Slope: points of win chance above the ratings' prediction per Pokemon of overlap (bring: 0-4, lead: 0-2),
90% interval from a bootstrap over sides. Rated games only (both players 1100+), no forfeits.

    python labs/bring_value_lab.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from src.bring_model import FEATURES, build_rows, predict, rates
from src.dex import load_dex
from src.formats import CURRENT
from src.replays import load_records
from src.usage import load_usage

MAX_GAMES = 12000
MIN_RATING = 1100


def fit(x, y, c, w=None):
    from sklearn.linear_model import LogisticRegression
    scale = x.std(axis=0) + 1e-9
    mean = x.mean(axis=0)
    m = LogisticRegression(C=c, max_iter=3000).fit((x - mean) / scale, y, sample_weight=w)
    coef = m.coef_[0] / scale
    return {"coef": coef.tolist(), "intercept": float(m.intercept_[0] - (mean * coef).sum())}


def residuals(records):
    out = {}
    for r in records:
        if r.get("forfeit"):
            continue
        ra, rb = (r["players"][p].get("rating") or 0 for p in ("p1", "p2"))
        if min(ra, rb) < MIN_RATING:
            continue
        for p, own, opp in (("p1", ra, rb), ("p2", rb, ra)):
            out[(r["id"], p)] = (r["winner"] == p) - 1 / (1 + 10 ** ((opp - own) / 400))
    return out


def by_side(groups):
    idx = {}
    for i, g in enumerate(groups):
        idx.setdefault(g, []).append(i)
    return idx


def evaluate(model, x, y, groups, k, res):
    """(imitation overlap, slope of residual on overlap, 90% interval, sides)"""
    p = predict(model, x)
    over, slope_x, slope_y = [], [], []
    for g, idx in by_side(groups).items():
        top = set(sorted(idx, key=lambda i: -p[i])[:k])
        real = {i for i in idx if y[i] == 1}
        o = len(top & real)
        over.append(o / max(1, len(real)))
        if g in res:
            slope_x.append(o)
            slope_y.append(res[g])
    xs, ys = np.array(slope_x, float), np.array(slope_y)
    slope = np.polyfit(xs, ys, 1)[0]
    rng = np.random.default_rng(0)
    bs = []
    for _ in range(1000):
        i = rng.integers(0, len(xs), len(xs))
        if xs[i].std() > 0:
            bs.append(np.polyfit(xs[i], ys[i], 1)[0])
    return np.mean(over), 100 * slope, 100 * np.percentile(bs, 5), 100 * np.percentile(bs, 95), len(xs), xs.mean()


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    records = []
    for f in CURRENT.replays:
        records += load_records(f)
    records.sort(key=lambda r: r["uploadtime"] or 0)
    n = len(records)
    prior_part, train_part, test_part = records[: n // 2], records[n // 2: 3 * n // 4], records[3 * n // 4:]
    prior = rates(prior_part)
    x_tr, b_tr, l_tr, g_tr = build_rows(train_part, dex, usage, prior, MAX_GAMES)
    x_te, b_te, l_te, g_te = build_rows(test_part, dex, usage, prior, MAX_GAMES)
    res_tr, res_te = residuals(train_part), residuals(test_part)
    print(f"{n} replays; fit on {len(set(g_tr))} sides, test on {len(set(g_te))} "
          f"({sum(1 for g in set(g_te) if g in res_te)} rated); {len(FEATURES)} features")
    row_res = np.array([res_tr.get(g, np.nan) for g in g_tr])
    rated = ~np.isnan(row_res)
    for label, y_tr, y_te, k, c in (("bring", b_tr, b_te, 4, 1.0), ("lead", l_tr, l_te, 2, 0.01)):
        variants = {
            "imitation": fit(x_tr, y_tr, c),
            "winners only": fit(x_tr[rated & (row_res > 0)], y_tr[rated & (row_res > 0)], c),
            "weighted": fit(x_tr[rated], y_tr[rated], c, np.clip(1 + 2 * row_res[rated], 0, None)),
        }
        print(f"\n{label} (top {k})")
        for name, m in variants.items():
            acc, s, lo, hi, sides, mean_o = evaluate(m, x_te, y_te, g_te, k, res_te)
            print(f"  {name:13s} matches real picks {acc:.1%}  | follow it: {s:+.2f} pts per Pokemon "
                  f"(90% {lo:+.2f} to {hi:+.2f}), avg overlap {mean_o:.2f}/{k}, {sides} rated sides")


if __name__ == "__main__":
    main()
