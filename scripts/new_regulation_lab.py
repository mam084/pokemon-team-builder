#!/usr/bin/env python3
"""
new_regulation_lab.py - how good are the recommendations in a new regulation's first days,
before Smogon publishes its stats and before tournaments pile up?

Simulated on Reg M-C: every variant only sees data from before the held-out week
(tournaments from 2026-11-13 on, the cut the other tests use), and is scored on hiding one
Pokémon from each held-out tournament team (MRR, hit@1, in the candidate pool), with the
production weights.

  full data    Smogon's October stats + the 14-day replay rescale + teammate model fitted on 30
               days of replays and every earlier tournament: what the app has today
  last reg     Reg M-B's Smogon stats and nothing else: what the app could show on day one
  M-B + N days Reg M-B's stats rescaled to the last N days of replay team shares (apply_recent),
               teammate model fitted on those N days
  replays N    usage built from the last N days of replays (src/replay_usage.py, M-B sets for
               Pokémon that carry over), teammate model fitted on those N days

    python scripts/new_regulation_lab.py [--teams 500] [--days 2 4 7 14]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cooccurrence import Cooccurrence  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import build_queries, load_tournament_teams, rank_of  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.replay_usage import usage_from_replays  # noqa: E402
from src.replays import load_records, recent_usage  # noqa: E402
from src.synergy import L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records, replay_rows, \
    tournament_rows  # noqa: E402
from src.usage import UsageData  # noqa: E402

CUT = "2026-11-13"
PREV = "gen9championsvgc2026regmb"
OUT = Path(__file__).resolve().parent.parent / "data" / "evaluation" / "new_regulation_lab.json"
SYN = {"synergy": 1.0, "defense": 0.0, "offense": 0.0, "roles": 0.0, "meta": 0.0, "plan": 0.0}
POP = {"synergy": 0.0, "defense": 0.0, "offense": 0.0, "roles": 0.0, "meta": 1.0, "plan": 0.0}


def fresh(format_id: str) -> UsageData:
    """A private copy (load_usage is cached, and the variants below change their usage)."""
    from src.usage import USAGE_DIR
    usage = UsageData(json.loads((USAGE_DIR / f"{format_id}.json").read_text()))
    usage.link_cosmetic(load_dex(CURRENT.regulation))
    return usage


def fit_model(rows, formats):
    model = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)
    model.formats = formats
    return model


def ranks(queries, weights) -> np.ndarray:
    return np.array([1.0 / r if (r := rank_of(q, weights)) else 0.0 for q in queries])


def team_boot(a: np.ndarray, b: np.ndarray, groups: np.ndarray, reps: int = 2000) -> tuple[float, float, float]:
    """Mean difference a - b in reciprocal rank, 95% interval by resampling teams."""
    ids = np.unique(groups)
    per = {g: (a[groups == g] - b[groups == g]).mean() for g in ids}
    vals = np.array([per[g] for g in ids])
    rng = np.random.default_rng(0)
    boots = [vals[rng.integers(0, len(vals), len(vals))].mean() for _ in range(reps)]
    return float(vals.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=500)
    ap.add_argument("--days", type=int, nargs="+", default=[2, 4, 7, 14])
    args = ap.parse_args()

    fmt = CURRENT
    dex = load_dex(fmt.regulation)
    cut = datetime.fromisoformat(CUT).replace(tzinfo=timezone.utc).timestamp()
    teams = load_tournament_teams(fmt.regulation, dex)
    before = [t for t in teams if t["date"] < CUT]
    test = [t for t in teams if t["date"] >= CUT]
    random.Random(0).shuffle(test)
    test = test[: args.teams]
    groups = np.repeat(np.arange(len(test)), [len(t["sets"]) for t in test])
    records = [r for f in fmt.replays for r in load_records(f) if (r.get("uploadtime") or 0) < cut]
    prev = fresh(PREV)
    print(f"{len(test)} held-out teams, {len(records)} replays before {CUT}")

    variants: dict[str, UsageData] = {}

    # today's app, refitted on data before the cut
    full = fresh(fmt.id)
    recent = recent_usage(records, dex)
    if recent:
        full.apply_recent(recent, dex)
    full.cooc = Cooccurrence([t["sets"] for t in before], dex)
    full.teammates = fit_model(tournament_rows(before, dex, weight=TOURNAMENT_WEIGHT)
                               + replay_rows(recent_records(records, end=cut - 1), dex), fmt.replays)
    variants["full data"] = full
    variants["last reg"] = fresh(PREV)

    for n in args.days:
        window = recent_records(records, end=cut - 1, days=n)
        model = fit_model(replay_rows(window, dex), fmt.replays)
        shares = recent_usage(window, dex, days=n, min_rating=0)
        mb = fresh(PREV)
        if shares:
            mb.apply_recent(shares, dex)
        mb.teammates = model
        variants[f"M-B + {n} days"] = mb
        built = usage_from_replays(window, dex, fmt.id, prev=prev)
        if built:
            ru = UsageData(built)
            ru.link_cosmetic(dex)
            ru.teammates = model
            variants[f"replays {n} days"] = ru
            print(f"{n} days: {len(window)} replays, {built['info']['teams']} teams, {len(built['pokemon'])} Pokémon")

    results, rr = {}, {}
    for name, usage in variants.items():
        q = build_queries(test, dex, usage, doubles=True)
        syn, pop = ranks(q, SYN), ranks(q, POP)
        best = syn  # the production weights: synergy (teammate model, or ladder pair lift without one)
        rr[name] = best
        results[name] = {"mrr": round(float(best.mean()), 4),
                         "hit@1": round(float((best == 1).mean()), 4),
                         "in_pool": round(float(np.mean([rank_of(x, SYN) is not None for x in q])), 4),
                         "popularity mrr": round(float(pop.mean()), 4)}
        print(name, results[name])

    diffs = {}
    for n in args.days:
        a, b = f"replays {n} days", f"M-B + {n} days"
        if a in rr and b in rr:
            diffs[f"{a} vs {b}"] = team_boot(rr[a], rr[b], groups)
        if a in rr:
            diffs[f"{a} vs last reg"] = team_boot(rr[a], rr["last reg"], groups)
            diffs[f"{a} vs full data"] = team_boot(rr[a], rr["full data"], groups)
    for k, v in diffs.items():
        print(f"{k}: {v[0]:+.4f} (95% {v[1]:+.4f} to {v[2]:+.4f})")
    OUT.write_text(json.dumps({"cut": CUT, "teams": len(test), "queries": int(len(groups)), "results": results,
                               "differences": {k: [round(x, 4) for x in v] for k, v in diffs.items()}}, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
