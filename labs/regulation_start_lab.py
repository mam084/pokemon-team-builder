"""
regulation_start_lab.py - does a head start from the previous regulation help the teammate model early on?

On a regulation's first days the teammate model (src/synergy.py) is fitted on a few days of replays, and
every pair's pull is shrunk toward 0 ("no relationship") until data says otherwise. Most Pokemon carry
over between regulations, so the previous regulation already says a lot about who goes with whom. Here
the pulls are shrunk toward the previous regulation's instead.

Simulation with the regulations we have: pretend Reg M-C just started. Fit on only its first N days of
replays (N = 1, 3, 7, 14, 28 from the first replay, Sept 23) with and without a head start from Reg M-B's
Smogon teammate stats, and judge every version on M-C's tournament teams (Oct 30 - Nov 20), all after
every training window: hide each member, rank it from the other five among every Pokemon either model
or the test teams know, record its rank. The head-start strength is chosen on the replays of the week
after each window, not on the tournaments.

On the real switch the head start would be the previous regulation's fitted model, which knows more than
Smogon's stats, so this likely understates it.

    python labs/regulation_start_lab.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import L2, TeammateModel, build_vocab, previous_lifts, prior_matrix, replay_rows, root_of  # noqa: E402

FMT = "gen9championsvgc2026regmc"
PREV_USAGE = Path(__file__).resolve().parent.parent / "data" / "usage" / "gen9championsvgc2026regmb.json"
DAY = 86400
BOOT = 1000


class PriorModel(TeammateModel):
    """TeammateModel whose pulls are shrunk toward W0 instead of 0 (W0 = 0 is the shipped model)."""

    def __init__(self, vocab, W0=None):
        super().__init__(vocab)
        self.W0 = W0

    def fit(self, rows, **kw):
        return super().fit(rows, prior=self.W0, **kw)


def previous_lifts_(dex):
    return None, previous_lifts(PREV_USAGE, dex)


def queries(teams):
    """(team index, hidden root, the other five) for every member of every team."""
    out = []
    for n, roots in enumerate(teams):
        for r in roots:
            out.append((n, r, [x for x in roots if x != r]))
    return out


def ranks(model, qs, universe):
    """Rank of the hidden member among the universe (minus the other five); unknown to the model = last."""
    out = np.empty(len(qs))
    for k, (_, hidden, ctx) in enumerate(qs):
        cand = [c for c in universe if c not in ctx]
        s = model.scores(ctx)
        vals = np.array([s[model.index[c]] if c in model.index else -np.inf for c in cand])
        h = vals[cand.index(hidden)]
        out[k] = len(cand) if not np.isfinite(h) else int((vals > h).sum()) + 1
    return out


def main():
    dex = load_dex("regmc")
    recs = [r for f in (FMT, FMT + "bo3") for r in load_records(f)]
    recs = [r for r in recs if r.get("uploadtime")]
    start = min(r["uploadtime"] for r in recs)
    _, lifts = previous_lifts_(dex)
    prev_vocab = sorted({a for a, _ in lifts} | {b for _, b in lifts})
    teams = [sorted({root_of(p.species, dex) for p in t["sets"]} - {None})
             for t in load_tournament_teams("regmc", dex)]
    teams = [t for t in teams if len(t) == 6]
    rng = np.random.default_rng(0)
    test = [teams[i] for i in rng.choice(len(teams), min(1500, len(teams)), replace=False)]
    test_q = queries(test)
    team_of = np.array([q[0] for q in test_q])
    boots = [rng.integers(0, len(test), len(test)) for _ in range(BOOT)]
    print(f"{len(recs)} M-C replays from {start}; {len(prev_vocab)} Pokemon in the M-B head start; "
          f"test: {len(test)} M-C tournament teams ({len(test_q)} queries)")

    def score(rr, mask=None):
        rr = 1.0 / rr
        per = np.bincount(team_of, rr, minlength=len(test)) / 6
        return per

    print(f"{'days':>4s} {'replays':>8s} {'variant':32s} {'top 10':>7s} {'MRR':>6s}   gain vs no head start (95%)")
    for days in (1, 3, 7, 14, 28):
        cut = start + days * DAY
        train = [r for r in recs if r["uploadtime"] < cut]
        valid = [r for r in recs if cut <= r["uploadtime"] < cut + 7 * DAY]
        rows = replay_rows(train, dex)
        vrows = replay_rows(valid, dex)
        vteams = [sorted(set(r.roots)) for r in vrows if len(set(r.roots)) == 6][:600]
        vq = queries(vteams)
        base_vocab = build_vocab(rows)
        union = sorted(set(base_vocab) | set(prev_vocab))
        universe = sorted(set(union) | {r for t in test for r in t})
        vuniverse = sorted(set(union) | {r for t in vteams for r in t})
        base = PriorModel(base_vocab).fit(rows)
        # head-start strength, chosen on the following week's replays
        best = None
        for alpha in (0.5, 1.0, 1.5):
            m = PriorModel(union, prior_matrix(union, lifts, alpha)).fit(rows)
            v = (1.0 / ranks(m, vq, vuniverse)).mean()
            if best is None or v > best[0]:
                best = (v, alpha, m)
        _, alpha, head = best
        variants = {"no head start (shipped)": base, f"M-B head start (strength {alpha})": head}
        rb = ranks(base, test_q, universe)
        base_per = score(rb)
        for name, m in variants.items():
            rr = rb if m is base else ranks(m, test_q, universe)
            per = score(rr)
            line = f"{days:4d} {len(train):8d} {name:32s} {(rr <= 10).mean():7.1%} {(1 / rr).mean():6.3f}"
            if m is not base:
                d = [(per[b] - base_per[b]).mean() for b in boots]
                line += f"   {np.mean(per - base_per):+.3f} ({np.percentile(d, 2.5):+.3f} to {np.percentile(d, 97.5):+.3f})"
            print(line, flush=True)


if __name__ == "__main__":
    main()
