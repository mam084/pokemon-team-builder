"""
synergy_lab.py - does a learned teammate model (src/synergy.py) beat lift-based synergy?

Same task and split as src/evaluate.py ("complete the team" on tournament teams; newest 30%
of tournaments is the test). The learned model is fitted only on data from before the
tuning tournaments (older tournaments + replays uploaded before then), the blend with the
recommender's other signals is tuned on the next tournaments, and everything is reported
on the newest ones.

    python labs/synergy_lab.py [--fast]
"""

from __future__ import annotations

import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cooccurrence import Cooccurrence  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import SIGNALS, build_queries, load_tournament_teams, split_by_date  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import TeammateModel, build_vocab, replay_rows, root_of, tournament_rows  # noqa: E402
from src.usage import load_usage  # noqa: E402

FMT = "gen9championsvgc2026regmc"
CACHE = Path("/tmp/synergy_lab_queries.pkl")


def ts(date: str) -> float:
    return datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()


def rank_metrics(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {"mrr": round(sum(1 / r for r in ranks if r) / n, 4),
            **{f"hit@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 4) for k in (1, 5, 10)}}


def query_ranks(queries, extra: dict, weights: dict, w_new: float, popularity_new: bool = False):
    """Blend the recommender's components (weights) with a new synergy column (w_new)."""
    ranks = []
    for q in queries:
        if q.hidden_group is None:
            ranks.append(None)
            continue
        w = np.array([weights[s] for s in SIGNALS], dtype=float)
        base = q.components @ w
        col = extra[id(q)]
        score = base + w_new * col
        score = np.where(q.mega, score * 0.8, score)
        best = np.maximum.reduceat(score, q.starts)
        ranks.append(int((best >= best[q.hidden_group]).sum()))
    return ranks


def main(fast: bool = False):
    t0 = time.time()
    dex = load_dex("regmc")
    usage = load_usage(FMT)
    teams = load_tournament_teams("regmc", dex)
    train, test = split_by_date(teams)
    pairs_from, tune_teams = split_by_date(train, 0.4)
    fit_cut = ts(min(t["date"] for t in tune_teams))
    print(f"tournaments: fit {len(pairs_from)}, tune {len(tune_teams)}, test {len(test)}; "
          f"fit cutoff {datetime.fromtimestamp(fit_cut, timezone.utc).date()}")

    # The recommender's current component scores for every query (cached: ~10 min to build)
    if CACHE.exists():
        tune_q, test_q = pickle.loads(CACHE.read_bytes())
    else:
        usage.cooc = Cooccurrence([t["sets"] for t in pairs_from], dex)
        tune_q = build_queries(tune_teams, dex, usage)
        test_q = build_queries(test, dex, usage)
        CACHE.write_bytes(pickle.dumps((tune_q, test_q)))
    print(f"queries: tune {len(tune_q)}, test {len(test_q)} ({time.time() - t0:.0f}s)")

    # Fit data: older tournaments + replays uploaded before the tuning tournaments
    t_rows = tournament_rows(pairs_from, dex)
    records = [r for f in (FMT, FMT + "bo3") for r in load_records(f) if (r["uploadtime"] or 0) < fit_cut]
    l_rows = replay_rows(records, dex)
    print(f"fit rows: {len(t_rows)} tournament teams, {len(l_rows)} ladder teams "
          f"(from {len(records)} replays)")

    def team_roots(q_team_sets):
        return [r for p in q_team_sets if (r := root_of(p.species, dex))]

    # rebuild the context (the five shown) for each query from the teams
    def contexts(team_list):
        out = []
        for t in team_list:
            for i, _ in enumerate(t["sets"]):
                out.append(team_roots(t["sets"][:i] + t["sets"][i + 1:]))
        return out

    tune_ctx, test_ctx = contexts(tune_teams), contexts(test)
    assert len(tune_ctx) == len(tune_q) and len(test_ctx) == len(test_q)

    def column(model: TeammateModel, queries, ctxs, kind: str):
        """Per-query array aligned with q.components rows: the model's score for each candidate."""
        out = {}
        for q, ctx in zip(queries, ctxs):
            t = q.table.sort_values("root", kind="stable")
            if kind == "fit":
                s = model.fit_scores(ctx)
            else:
                s = model.scores(ctx)
            vals = np.array([s[model.index[r]] if r in model.index else (s.min() if kind == "full" else 0.0)
                             for r in t["root"]])
            out[id(q)] = vals
        return out

    variants = {
        "tournaments only": t_rows,
        "ladder only": l_rows,
        "tournaments + ladder": t_rows + l_rows,
    }
    if fast:
        variants = {"tournaments + ladder": t_rows + l_rows}
    tuned = {"synergy": 0.762, "defense": 0.0, "offense": 0.0, "roles": 0.0, "meta": 0.19, "plan": 0.048}
    zero = {s: 0.0 for s in SIGNALS}
    syn_only = {**zero, "synergy": 1.0}
    print("\nbaselines on test:")
    print("  current tuned blend:", rank_metrics(query_ranks(test_q, {id(q): 0 for q in test_q}, tuned, 0)))
    print("  current synergy only:", rank_metrics(query_ranks(test_q, {id(q): 0 for q in test_q}, syn_only, 0)))

    results = {}
    for name, rows in variants.items():
        for l2 in ([20.0] if fast else [5.0, 20.0, 80.0]):
            t1 = time.time()
            vocab = build_vocab(rows)
            model = TeammateModel(vocab).fit(rows, l2=l2, epochs=40 if fast else 60)
            full_tune, full_test = column(model, tune_q, tune_ctx, "full"), column(model, test_q, test_ctx, "full")
            fit_tune, fit_test = column(model, tune_q, tune_ctx, "fit"), column(model, test_q, test_ctx, "fit")
            alone = rank_metrics(query_ranks(test_q, full_test, zero, 1.0))
            # blend: tune the new column's weight next to the current signals (on tune queries)
            best = None
            for base_name, base_w in (("tuned", tuned), ("no synergy", {**tuned, "synergy": 0.0})):
                for col_name, col_tune, col_test in (("full", full_tune, full_test), ("fit", fit_tune, fit_test)):
                    for w_new in (0.05, 0.2, 0.8, 2.0, 5.0, 20.0):
                        m_tune = rank_metrics(query_ranks(tune_q, col_tune, base_w, w_new))
                        if best is None or m_tune["mrr"] > best[0]:
                            best = (m_tune["mrr"], base_name, col_name, w_new, col_test, base_w)
            mrr_tune, base_name, col_name, w_new, col_test, base_w = best
            blend = rank_metrics(query_ranks(test_q, col_test, base_w, w_new))
            results[(name, l2)] = (alone, blend, (base_name, col_name, w_new))
            print(f"\n{name}, l2={l2} (vocab {len(vocab)}, {time.time() - t1:.0f}s)")
            print("  learned model alone:", alone)
            print(f"  blended ({base_name} + {col_name} x{w_new}, tune MRR {mrr_tune}):", blend)
    return results


if __name__ == "__main__":
    main(fast="--fast" in sys.argv)
