"""
wide_guard_lab.py - is the win model giving Wide Guard too much credit? (Nov 26)

The shipped match model counts how many of your Pokemon carry Wide Guard (minus theirs) and learned about
+1.8 win-chance points per copy (90% +0.4 to +3.3). Having the move isn't using it: it only does something
against spread attacks, and only when it's clicked on the right turn. Variants, each replacing the
"tool: Wide Guard" column (every other feature unchanged):

- shipped: count per Pokemon
- no credit: the column zeroed
- has it: min(count, 1), so a second copy earns nothing
- vs spread: (has it) x (share of the opponent's six with a damaging spread move), minus the same for the
  other side, so it's worth nothing against a team with nothing to block
- count vs spread: count x the opponent's spread share

Same procedure as src/match_model.train_and_report and labs/win_model_lab.py: L2 logistic on skill + team
features, both orientations, C by forward-chaining CV inside the oldest 70% of tournaments, judged once on
the newest 30%, paired bootstrap over test matches against the shipped setup. Also prints the Wide Guard
points and how many matches each version tells apart.

    python labs/wide_guard_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import match_model as M  # noqa: E402
from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.usage import load_usage  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from win_model_lab import run  # noqa: E402

COL = "tool: Wide Guard"
SPREAD = {"allAdjacentFoes", "allAdjacent"}


def side_info(regulation: str) -> dict:
    """(tournament, player) -> (Wide Guard users, share of the six with a damaging spread move)."""
    dex, usage = load_dex(regulation), load_usage(CURRENT.id, recent=False)
    teams = {(t["tournament"], t["player"]): t for t in load_tournament_teams(regulation, dex, usage=usage)}
    out = {}
    for k, ms in M._sides(teams, dex).items():
        wg = sum("Wide Guard" in M.tools_of(m) for m in ms)
        spread = sum(any(mv.get("target") in SPREAD and mv.get("category") != "Status" for mv in m.moves)
                     for m in ms)
        out[k] = (float(wg), spread / max(len(ms), 1))
    return out


def variant(df, info, f):
    out = df.copy()
    a = [info.get((t, p)) for t, p in zip(df["tournament"], df["p1"])]
    b = [info.get((t, p)) for t, p in zip(df["tournament"], df["p2"])]
    ok = np.array([x is not None and y is not None for x, y in zip(a, b)])
    vals = np.array([f(x, y) - f(y, x) if o else 0.0 for x, y, o in zip(a, b, ok)])
    out.loc[ok, COL] = vals[ok]
    return out


def main():
    reg = CURRENT.regulation
    df = M.add_skill(M.build_dataset(reg, CURRENT.id, verbose=False), reg)
    info = side_info(reg)
    y = df["won"].to_numpy(float)
    tr, te = M.time_split(df)
    features = M.SKILL + M.FEATURES + ([COL] if COL not in M.FEATURES else [])   # the pre-Nov 26 feature set
    logit = lambda c: M.Logit(c)  # noqa: E731
    variants = {
        "shipped: count per Pokemon": df,
        "no credit": variant(df, info, lambda me, opp: 0.0),
        "has it (0/1)": variant(df, info, lambda me, opp: min(me[0], 1.0)),
        "vs spread: has it x opp spread": variant(df, info, lambda me, opp: min(me[0], 1.0) * opp[1]),
        "count x opp spread": variant(df, info, lambda me, opp: me[0] * opp[1]),
    }
    spread = np.array([v[1] for v in info.values()])
    users = np.array([v[0] for v in info.values()])
    print(f"sides: {len(info)}; with Wide Guard {np.mean(users > 0):.1%}, two+ {np.mean(users > 1):.2%}; "
          f"opponent spread share mean {spread.mean():.2f} (sd {spread.std():.2f})")
    res = [run(d, features, logit, name, tr, te, y) for name, d in variants.items()]
    yt = y[te]
    base = M._losses(res[0]["p"], yt)
    rng = np.random.default_rng(0)
    idx = [rng.integers(0, len(yt), len(yt)) for _ in range(2000)]
    print(f"\ntrain {int(tr.sum())} matches, test {int(te.sum())} (newest 30%)")
    print(f"{'variant':32s} {'CV loss':>8s} {'test loss':>9s}  vs shipped (loss drop, 95%)       "
          f"WG coef x unit  differs in")
    for r, d in zip(res, variants.values()):
        l = M._losses(r["p"], yt)
        diff = base - l
        dd = [diff[i].mean() for i in idx]
        differs = float((d.loc[tr, COL] != 0).mean())
        unit = float(np.abs(d.loc[tr & (d[COL] != 0), COL]).mean()) if differs else 0.0
        print(f"{r['label']:32s} {r['cv']:.5f} {l.mean():9.5f}  {diff.mean():+.5f} ({np.percentile(dd, 2.5):+.5f} "
              f"to {np.percentile(dd, 97.5):+.5f})  {r['coef'][COL] * unit * 25:+6.2f} pts  {differs:.0%}")


if __name__ == "__main__":
    main()
