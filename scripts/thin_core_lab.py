"""
thin_core_lab.py - when is a Pokemon's data too thin for the builder's picks around it?

The teammate model (src/synergy.py) keeps, for each Pokemon, how many weighted teams it was fitted on
(`counts`: tournament sheets at 3x plus each ladder player's team once, weighted by rating). Its pulls
for a rarely seen Pokemon stay near 0, so picks around it fall back on popularity (Popular picks) or
type fit, roles and game plan (Neutral, Hidden gems).

Same split as src/evaluate.py: the model is fitted on the oldest tournaments plus replays from before
the tuning tournaments; every member of every held-out team is hidden in turn and ranked from the
other five. Queries are grouped by the evidence behind the least-seen of the five shown, so the bins
say how well the builder finds real teammates around a Pokemon with that much data. The app's
thin-data note (src/core_report.THIN_EVIDENCE) uses the count where accuracy falls away.

    python scripts/thin_core_lab.py     (reuses scripts/repeat_entries_lab.py's query cache)
"""

from __future__ import annotations

import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cooccurrence import Cooccurrence  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import build_queries, load_tournament_teams, split_by_date  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import (L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records,  # noqa: E402
                         replay_rows, root_of, tournament_rows)
from src.usage import load_usage  # noqa: E402

FMT = "gen9championsvgc2026regmc"
CACHE = Path("/tmp/repeat_entries_lab_queries.pkl")
BINS = [0, 100, 200, 400, 800, 1600, 1e9]
BOOT = 2000


def main():
    dex = load_dex("regmc")
    usage = load_usage(FMT)
    teams = load_tournament_teams("regmc", dex)
    train, test = split_by_date(teams)
    pairs_from, tune_teams = split_by_date(train, 0.4)
    cut = datetime.fromisoformat(min(t["date"] for t in tune_teams)).replace(tzinfo=timezone.utc).timestamp()
    if CACHE.exists():
        test_q = pickle.loads(CACHE.read_bytes())
    else:
        usage.cooc, usage.teammates = Cooccurrence([t["sets"] for t in pairs_from], dex), None
        test_q = build_queries(test, dex, usage)
        CACHE.write_bytes(pickle.dumps(test_q))
    records = recent_records([r for f in (FMT, FMT + "bo3") for r in load_records(f)], end=cut - 1)
    rows = tournament_rows(pairs_from, dex, TOURNAMENT_WEIGHT) + replay_rows(records, dex)
    model = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)
    count = dict(zip(model.vocab, model.counts))

    rr, least, team_ix, ctxs = [], [], [], []
    for n, t in enumerate(test):
        for i, _ in enumerate(t["sets"]):
            team_ix.append(n)
            ctxs.append([r for p in t["sets"][:i] + t["sets"][i + 1:] if (r := root_of(p.species, dex))])
            least.append(min(count.get(r, 0.0) for r in ctxs[-1]))
    for q, ctx in zip(test_q, ctxs):
        if q.hidden_group is None:
            rr.append(0.0)
            continue
        s = model.scores(ctx)
        tab = q.table.sort_values("root", kind="stable")
        vals = np.array([s[model.index[r]] if r in model.index else s.min() for r in tab["root"]])
        best = np.maximum.reduceat(vals, q.starts)
        rr.append(1.0 / int((best >= best[q.hidden_group]).sum()))
    rr, least, team_ix = np.array(rr), np.array(least), np.array(team_ix)

    rng = np.random.default_rng(0)
    boots = [rng.integers(0, len(test), len(test)) for _ in range(BOOT)]
    print(f"all held-out queries: {len(rr)}, MRR {rr.mean():.3f}, top 10 {(rr >= 0.1).mean():.1%}")
    print("least-seen of the five shown (weighted teams) | queries | MRR (95%) | top 10")
    for lo, hi in zip(BINS, BINS[1:]):
        m = (least >= lo) & (least < hi)
        if not m.any():
            continue
        s = np.bincount(team_ix[m], rr[m], minlength=len(test))
        c = np.bincount(team_ix[m], minlength=len(test))
        b = [s[x].sum() / max(c[x].sum(), 1) for x in boots]
        lo95, hi95 = np.percentile(b, [2.5, 97.5])
        print(f"  {lo:>5.0f}-{hi if hi < 1e9 else float('inf'):>5.0f} | {int(m.sum()):5d} | "
              f"{rr[m].mean():.3f} ({lo95:.3f}-{hi95:.3f}) | {(rr[m] >= 0.1).mean():.1%}")


if __name__ == "__main__":
    main()
