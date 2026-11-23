"""Do Bo3 games (open team sheets) make the learned match model better at predicting held-out
tournament matches? (Nov 2026)

Bo3 replays carry each player's real six sets (no stat points, so each Pokemon gets its most common
ladder spread, as tournament lists do) and both ladder ratings. Each game becomes a match-model row:
the same damage-calc, Speed, bulk and support-tool features as a tournament match, with skill as
"ladder rating" (its own column, since ladder Elo isn't tournament Elo).

Rule, fixed before looking at results: settings (how far back Bo3 goes, how much a tournament match
counts relative to a Bo3 game, regularization) are picked by validation on the newest quarter of the
*training* tournaments; the held-out week is touched once. Bo3 ships only if held-out log loss
improves with a 95% paired-bootstrap interval above zero.

    python labs/bo3_match_lab.py build     # feature rows -> .cache/regmc_bo3_rows.pkl (slow, ~15 min)
    python labs/bo3_match_lab.py           # the comparison
"""
import datetime as dt
import math
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src import match_model as M
from src.analysis import build_members
from src.dex import load_dex
from src.formats import CURRENT
from src.replays import _sets_for, load_records
from src.stats import parse_spread
from src.usage import load_usage, typical_spread

ROWS = M.CACHE_DIR / f"{CURRENT.regulation}_bo3_rows.pkl"
WINDOWS = (7, 14, 21, 30, 45, None)        # days of Bo3 before the cut (None: all of it)
TOURNAMENT_WEIGHTS = (1.0, 3.0, 10.0)      # one tournament match counts as this many Bo3 games
CS = (0.001, 0.003, 0.01, 0.03)
_dex = _usage = None
_cache: dict = {}


def _init():
    global _dex, _usage
    _dex, _usage = load_dex(CURRENT.regulation), load_usage(CURRENT.id, recent=False)


def _side(rec, p):
    sets = _sets_for(rec, p, _dex, _usage)
    for s in sets:  # sheets publish no nature or stat points: the most common ladder spread
        entry = s.battle_form(_dex).name if _usage.entry(s.battle_form(_dex).name) else s.species
        spreads = _usage.section(entry, "spreads")
        if spreads:
            nature, _ = parse_spread(next(iter(spreads)))
            s.nature = nature or s.nature
        s.sps = typical_spread(_usage, s, _dex) or s.sps
    mega = (rec.get("mega") or {}).get(p)
    key = (tuple((s.species, s.item, s.ability, tuple(s.moves)) for s in sets), mega)
    if key not in _cache:
        megas = [i for i, s in enumerate(sets) if s.is_mega(_dex)]
        pick = next((i for i in megas if mega and mega.startswith(sets[i].species.split("-")[0])), None)
        if pick is None and megas:
            pick = megas[0]
        mem = build_members(sets, _dex, evolve=pick)
        _cache[key] = (mem, M.side_profile(mem))
    return _cache[key]


def _row(rec):
    try:
        (ma, pa), (mb, pb) = _side(rec, "p1"), _side(rec, "p2")
        if len(ma) < 6 or len(mb) < 6:
            return None
        r1, r2 = rec["players"]["p1"]["rating"], rec["players"]["p2"]["rating"]
        row = {"date": dt.datetime.fromtimestamp(rec["uploadtime"], dt.timezone.utc).date().isoformat(),
               "player": rec["players"]["p1"]["name"], "won": int(rec["winner"] == "p1"),
               "ladder rating": (r1 - r2) / 400 * math.log(10)}
        row.update(M.matchup_features(M.pair_parts(ma, mb), ma, mb))
        for k in pa:
            row[k] = pa[k] - pb[k]
        return row
    except Exception:  # a sheet the dex can't read
        return None


def _work(recs):
    _init()
    return [r for r in map(_row, recs) if r]


def build(workers: int = 2):
    keep = ("format", "uploadtime", "players", "winner", "preview", "sheets", "mega")
    recs = [{k: r.get(k) for k in keep} for r in load_records(f"{CURRENT.id}bo3")
            if r.get("sheets") and set(r["sheets"]) == {"p1", "p2"} and r["winner"] in ("p1", "p2")
            and not r.get("forfeit") and all(r["players"][p].get("rating") for p in ("p1", "p2"))]
    print(len(recs), "rated Bo3 games with both sheets", flush=True)
    t0 = time.time()
    chunks = [recs[i::workers * 8] for i in range(workers * 8)]
    with Pool(workers) as pool:
        rows = [r for part in pool.imap_unordered(_work, chunks) for r in part]
    df = pd.DataFrame(rows).sort_values("date", kind="stable").reset_index(drop=True)
    M.CACHE_DIR.mkdir(exist_ok=True)
    df.to_pickle(ROWS)
    print(f"{len(df)} rows ({df['date'].min()} to {df['date'].max()}), {time.time() - t0:.0f}s -> {ROWS}")


class WLogit:
    """match_model.Logit with sample weights."""
    def __init__(self, c): self.c = c

    def fit(self, x, y, w):
        self.s = np.sqrt((x ** 2).mean(axis=0)) + 1e-9
        z = x / self.s
        m = LogisticRegression(C=self.c, fit_intercept=False, max_iter=3000)
        m.fit(np.vstack([z, -z]), np.concatenate([y, 1 - y]), sample_weight=np.concatenate([w, w]))
        self.coef_ = m.coef_[0] / self.s
        return self

    def predict(self, x): return 1 / (1 + np.exp(-(x @ self.coef_)))


def compare():
    tour = M.add_skill(M.build_dataset(verbose=False), CURRENT.regulation)
    bo3 = pd.read_pickle(ROWS)
    tour["ladder rating"] = 0.0
    for c in M.SKILL:
        bo3[c] = 0.0
    cols = M.SKILL + ["ladder rating"] + M.FEATURES

    def fit(t, b, c, wt):
        x = np.vstack([t[cols].to_numpy(float), b[cols].to_numpy(float)])
        y = np.concatenate([t["won"].to_numpy(float), b["won"].to_numpy(float)])
        w = np.concatenate([np.full(len(t), wt), np.ones(len(b))])
        return WLogit(c).fit(x, y, w)

    def window(b, end, days):
        b = b[b["date"] < end]
        if days is None:
            return b
        start = (dt.date.fromisoformat(end) - dt.timedelta(days=days)).isoformat()
        return b[b["date"] >= start]

    tr, te = M.time_split(tour)
    train, test = tour[tr], tour[te]
    cut = test["date"].min()
    order = train.groupby("tournament")["date"].first().sort_values(kind="stable").index.tolist()
    v = train["tournament"].isin(set(order[-len(order) // 4:])).to_numpy()
    val_start = train[v]["date"].min()
    yv = train[v]["won"].to_numpy(float)
    print(f"tournaments {tour['date'].min()} to {tour['date'].max()}; Bo3 {bo3['date'].min()} to "
          f"{bo3['date'].max()}; validation from {val_start}, test from {cut}\n")

    # 1. validation inside the training period
    results = []
    for days in (0,) + WINDOWS:
        b = bo3.iloc[:0] if days == 0 else window(bo3, val_start, days)
        for wt in ((1.0,) if days == 0 else TOURNAMENT_WEIGHTS):
            for c in CS:
                p = fit(train[~v], b, c, wt).predict(train[v][cols].to_numpy(float))
                results.append({"bo3 days": "none" if days == 0 else (days or "all"), "bo3 games": len(b),
                                "tournament weight": wt, "C": c, "val log loss": M.metrics(p, yv)["log_loss"]})
    res = pd.DataFrame(results)
    best = res.loc[res.groupby("bo3 days", sort=False)["val log loss"].idxmin()]
    print("Validation (newest quarter of training tournaments), best settings per Bo3 window:")
    print(best.round(5).to_string(index=False))
    base_row = best[best["bo3 days"] == "none"].iloc[0]
    pick = best.loc[best["val log loss"].idxmin()]
    print(f"\npicked: Bo3 window {pick['bo3 days']}, tournament weight {pick['tournament weight']}, C {pick['C']}")

    # 2. the held-out week, once: tournaments-only vs the picked Bo3 setting (and, for the record, every window)
    yt = test["won"].to_numpy(float)
    base = fit(train, bo3.iloc[:0], base_row["C"], 1.0).predict(test[cols].to_numpy(float))
    lb = M._losses(base, yt)
    print(f"\nHeld-out week ({len(test):,} matches):")
    print(f"  tournaments only        log loss {lb.mean():.5f}  AUC {M.metrics(base, yt)['auc']:.4f}")
    verdict = None
    for _, r in best.iterrows():
        if r["bo3 days"] == "none":
            continue
        days = None if r["bo3 days"] == "all" else int(r["bo3 days"])
        b = window(bo3, cut, days)
        p = fit(train, b, r["C"], r["tournament weight"]).predict(test[cols].to_numpy(float))
        lo, hi = M._bootstrap_gain(lb, M._losses(p, yt))
        tag = "  <- picked by validation" if r["bo3 days"] == pick["bo3 days"] else ""
        print(f"  + Bo3 {str(r['bo3 days']):>4} days ({len(b):,} games, weight {r['tournament weight']:g}) "
              f"log loss {M._losses(p, yt).mean():.5f}  AUC {M.metrics(p, yt)['auc']:.4f}  "
              f"gain {lo:+.5f} to {hi:+.5f}{tag}")
        if tag:
            verdict = lo > 0
    if pick["bo3 days"] == "none":
        verdict = False
    print("\nVerdict:", "include Bo3" if verdict else "don't include Bo3 (not clearly better on held-out matches)")


if __name__ == "__main__":
    build() if sys.argv[1:] == ["build"] else compare()
