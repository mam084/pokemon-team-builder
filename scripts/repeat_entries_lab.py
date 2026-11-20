"""
repeat_entries_lab.py - should a player's repeat tournament entries count once in the teammate model?

29% of Reg M-C tournament team sheets repeat a six the same player already entered (one six appears
18 times). The teammate model (src/synergy.py) counts each sheet, so one player who enters the same
off-meta team at several events can create a strong "players pair it" pull on their own (Mega
Feraligatr + Empoleon 3.4x came from one player's team entered twice).

Same task and split as src/evaluate.py / scripts/synergy_lab.py: the model is fitted on the oldest
tournaments plus replays uploaded before the tuning tournaments, and ranks the hidden member of every
held-out team (newest tournaments) among the recommender's candidate pool. Variants:

    every sheet      each tournament sheet counted (what shipped before)
    once             each (player, six) counted once
    repeats at 1x    the first entry at the tournament weight (3x), repeats at 1x

Reported on all held-out teams, on the held-out teams counted once per (player, six), and on queries
whose five shown members include a Pokemon on few fit-period tournament teams. Paired bootstrap over
held-out teams.

    python scripts/repeat_entries_lab.py
"""

from __future__ import annotations

import pickle
import sys
import time
from collections import Counter
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
RARE = 15          # "few tournament teams": on fewer than this many fit-period sheets
BOOT = 2000


def ts(date: str) -> float:
    return datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()


def entry_key(t: dict, dex) -> tuple:
    return ((t.get("player") or "").lower(), tuple(sorted({root_of(p.species, dex) or "" for p in t["sets"]})))


def main():
    t0 = time.time()
    dex = load_dex("regmc")
    usage = load_usage(FMT)
    teams = load_tournament_teams("regmc", dex)
    train, test = split_by_date(teams)
    pairs_from, tune_teams = split_by_date(train, 0.4)
    fit_cut = ts(min(t["date"] for t in tune_teams))
    keys = Counter(entry_key(t, dex) for t in pairs_from)
    print(f"tournaments: fit {len(pairs_from)} sheets ({len(keys)} distinct player+six), "
          f"test {len(test)} sheets ({len({entry_key(t, dex) for t in test})} distinct)")

    if CACHE.exists():
        test_q = pickle.loads(CACHE.read_bytes())
    else:
        usage.cooc = Cooccurrence([t["sets"] for t in pairs_from], dex)
        usage.teammates = None
        test_q = build_queries(test, dex, usage)
        CACHE.write_bytes(pickle.dumps(test_q))
    print(f"queries: {len(test_q)} ({time.time() - t0:.0f}s)")

    records = recent_records([r for f in (FMT, FMT + "bo3") for r in load_records(f)], end=fit_cut - 1)
    l_rows = replay_rows(records, dex)

    # tournament rows per variant (pairs_from is in date order; the first entry of a six keeps full weight)
    ordered = sorted(pairs_from, key=lambda t: t["date"])
    seen: set = set()
    first, repeat = [], []
    for t in ordered:
        k = entry_key(t, dex)
        (repeat if k in seen else first).append(t)
        seen.add(k)
    variants = {
        "every sheet": tournament_rows(ordered, dex, TOURNAMENT_WEIGHT),
        "once": tournament_rows(first, dex, TOURNAMENT_WEIGHT),
        "repeats at 1x": tournament_rows(first, dex, TOURNAMENT_WEIGHT) + tournament_rows(repeat, dex, 1.0),
    }

    # per-query context (the five shown), team index and dedupe flag, aligned with test_q
    ctxs, team_ix, distinct = [], [], []
    seen_test: set = set()
    for n, t in enumerate(test):
        k = entry_key(t, dex)
        new = k not in seen_test
        seen_test.add(k)
        for i, _ in enumerate(t["sets"]):
            ctxs.append([r for p in t["sets"][:i] + t["sets"][i + 1:] if (r := root_of(p.species, dex))])
            team_ix.append(n)
            distinct.append(new)
    assert len(ctxs) == len(test_q)
    team_ix, distinct = np.array(team_ix), np.array(distinct)
    fit_count = Counter(r for t in pairs_from for r in {root_of(p.species, dex) for p in t["sets"]})
    rare = np.array([any(fit_count[r] < RARE for r in c) for c in ctxs])

    def ranks(model: TeammateModel) -> np.ndarray:
        out = []
        for q, ctx in zip(test_q, ctxs):
            if q.hidden_group is None:
                out.append(0.0)
                continue
            s = model.scores(ctx)
            t = q.table.sort_values("root", kind="stable")
            vals = np.array([s[model.index[r]] if r in model.index else s.min() for r in t["root"]])
            vals = np.where(q.mega, vals - 1e-9, vals)
            best = np.maximum.reduceat(vals, q.starts)
            out.append(1.0 / int((best >= best[q.hidden_group]).sum()))
        return np.array(out)

    rr = {}
    for name, rows in variants.items():
        t1 = time.time()
        model = TeammateModel(build_vocab(rows + l_rows)).fit(rows + l_rows, l2=L2)
        rr[name] = ranks(model)
        print(f"  fitted {name}: {len(rows)} tournament rows ({time.time() - t1:.0f}s)")

    rng = np.random.default_rng(0)
    n_teams = len(test)
    boots = [rng.integers(0, n_teams, n_teams) for _ in range(BOOT)]

    def report(label: str, mask: np.ndarray):
        print(f"\n{label}: {int(mask.sum())} queries")
        base = rr["every sheet"]
        for name, r in rr.items():
            line = f"  {name:14s} MRR {r[mask].mean():.4f}  top1 {(r[mask] == 1).mean():.3f}"
            if name != "every sheet":
                d = r - base
                per_team = np.bincount(team_ix[mask], d[mask], minlength=n_teams)
                cnt = np.bincount(team_ix[mask], minlength=n_teams)
                diffs = [per_team[b].sum() / max(cnt[b].sum(), 1) for b in boots]
                lo, hi = np.percentile(diffs, [2.5, 97.5])
                line += f"  diff {d[mask].mean():+.4f} (95% {lo:+.4f} to {hi:+.4f})"
            print(line)

    report("all held-out teams", np.ones(len(test_q), bool))
    report("held-out teams, each player+six once", distinct)
    report(f"queries whose five include a Pokemon on <{RARE} fit-period sheets", rare)


if __name__ == "__main__":
    main()
