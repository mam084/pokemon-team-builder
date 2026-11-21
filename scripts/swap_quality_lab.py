"""
swap_quality_lab.py - when the app says a swap makes a team better, does it?

Ground truth from players changing their own teams. Rated ladder and Bo3 replays give each player's games
in order; consecutive games with the same six form a "version". Wherever a player's next version differs
by exactly one Pokemon (a real swap) and both versions have enough games, the swap's real effect is the
change in wins above what the ratings predicted:

    observed = mean(won - expected) on the new version - the same on the old one
    expected = 1 / (1 + 10 ** ((opponent rating - own rating) / 400))

The same player is on both sides, so their skill cancels. Neither of the app's models learned from replay
outcomes (the teammate model learns who players pick; the match model learns from tournament matches),
so these results are out of sample for both.

Each scorer predicts the swap's effect as its score on the new version minus the old one (each Pokemon
gets its most common set, as in the app). Reported: the weighted correlation of predicted with observed
(weights = 1 / (1/n_old + 1/n_new), the inverse variance), and mean observed effect by predicted quintile,
with 95% intervals from resampling players.

    python scripts/swap_quality_lab.py [--min-games 5]
"""

from __future__ import annotations

import argparse
import math
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.match_model import cap_chance, trust_bounds  # noqa: E402
from src.match_model import load_model as load_match_model  # noqa: E402
from src.matchup import build_archetypes  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import root_of  # noqa: E402
from src import team_rating as R  # noqa: E402
from src.usage import load_usage  # noqa: E402

FMT = CURRENT.id
CACHE = Path("/tmp/swap_quality_scores.pkl")
BOOT = 1000


def expected(own: float, opp: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opp - own) / 400.0))


def versions(records: list[dict], dex) -> dict[str, list[dict]]:
    """player -> [{"six": frozenset(roots), "species": [...], "res": [won - expected, ...]}] in game order."""
    games = defaultdict(list)
    for r in records:
        if r.get("forfeit") or r.get("winner") not in ("p1", "p2"):
            continue
        prev, pl = r.get("preview") or {}, r.get("players") or {}
        for side, other in (("p1", "p2"), ("p2", "p1")):
            six, me, opp = prev.get(side) or [], pl.get(side) or {}, pl.get(other) or {}
            if len(six) != 6 or not me.get("name") or not me.get("rating") or not opp.get("rating"):
                continue
            roots = [root_of(s, dex) for s in six]
            if None in roots or len(set(roots)) != 6:
                continue
            res = (1.0 if r["winner"] == side else 0.0) - expected(me["rating"], opp["rating"])
            games[(r["format"], me["name"].lower())].append((r.get("uploadtime") or 0, r["id"], frozenset(roots), six, res))
    out = {}
    for key, gs in games.items():
        gs.sort()
        vs = []
        for _, _, six, species, res in gs:
            if vs and vs[-1]["six"] == six:
                vs[-1]["res"].append(res)
            else:
                vs.append({"six": six, "species": species, "res": [res]})
        out[key] = vs
    return out


def swaps(vers: dict[str, list[dict]], min_games: int) -> list[dict]:
    out = []
    for player, vs in vers.items():
        for a, b in zip(vs, vs[1:]):
            if len(a["six"] & b["six"]) == 5 and len(a["res"]) >= min_games and len(b["res"]) >= min_games:
                na, nb = len(a["res"]), len(b["res"])
                out.append({"player": player, "old": a, "new": b,
                            "out": next(iter(a["six"] - b["six"])), "in": next(iter(b["six"] - a["six"])),
                            "obs": float(np.mean(b["res"]) - np.mean(a["res"])), "w": 1.0 / (1.0 / na + 1.0 / nb)})
    return out


class Scorer:
    """The app's numbers for a six, each Pokemon on its most common set (cached by the six)."""

    def __init__(self):
        self.dex = load_dex(CURRENT.regulation)
        self.usage = load_usage(FMT)
        arch = build_archetypes(self.usage, self.dex, team_size=6)
        self.model = load_match_model(CURRENT.regulation)
        self.sides, self.weights = R.meta_sides(arch, self.usage, self.dex)
        self.ref = R.load_reference(CURRENT.regulation)
        self.sheet = self.usage.team_sheet_usage(self.dex)
        self.cache = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}

    def __call__(self, species: list[str]) -> dict | None:
        key = frozenset(species)
        if key in self.cache:
            return self.cache[key]
        sets = [s for s in (self.usage.popular_set(n, self.dex) for n in species) if s is not None]
        out = None
        if len(sets) == 6:
            chance = cap_chance(self.model, R.learned_vs_meta(sets, self.dex, self.usage, self.model,
                                                               self.sides, self.weights))
            fit = R.teammate_fit(sets, self.dex, self.usage.teammates)
            pops = [self.sheet.get(self.usage.sheet_name(p.battle_form(self.dex).name, self.dex) or p.species, 0.0)
                    for p in sets]
            out = {"chance": chance, "fit": fit,
                   "score": R.combined(fit, chance, self.ref) if fit is not None else None,
                   "popularity": float(np.mean(np.log(np.array(pops) + 0.05)))}
        self.cache[key] = out
        return out

    def save(self):
        CACHE.write_bytes(pickle.dumps(self.cache))


def wcorr(x, y, w) -> float:
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    cov = np.average((x - mx) * (y - my), weights=w)
    return float(cov / math.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)))


def report(rows: list[dict], names: list[str], label: str) -> None:
    players = sorted({r["player"] for r in rows})
    pidx = {p: i for i, p in enumerate(players)}
    by_player = defaultdict(list)
    for i, r in enumerate(rows):
        by_player[pidx[r["player"]]].append(i)
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(BOOT):
        pick = rng.integers(0, len(players), len(players))
        boots.append(np.concatenate([by_player[p] for p in pick]))
    obs = np.array([r["obs"] for r in rows])
    w = np.array([r["w"] for r in rows])
    print(f"\n{label}: {len(rows)} swaps by {len(players)} players, "
          f"mean observed effect {np.average(obs, weights=w) * 100:+.2f} pts")
    print("  scorer        corr with observed (95%)     mean observed effect by predicted quintile (low -> high), pts")
    for name in names:
        pred = np.array([r["pred"][name] for r in rows])
        c = wcorr(pred, obs, w)
        cs = [wcorr(pred[b], obs[b], w[b]) for b in boots]
        lo, hi = np.percentile(cs, [2.5, 97.5])
        q = np.quantile(pred, [0.2, 0.4, 0.6, 0.8])
        bins = np.digitize(pred, q)
        quint = [np.average(obs[bins == k], weights=w[bins == k]) * 100 if (bins == k).any() else float("nan")
                 for k in range(5)]
        print(f"  {name:12s} {c:+.3f} ({lo:+.3f} to {hi:+.3f})   " + "  ".join(f"{v:+5.1f}" for v in quint))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-games", type=int, default=5)
    args = ap.parse_args()
    score = Scorer()
    recs = [r for f in (FMT, FMT + "bo3") for r in load_records(f)]
    rows = swaps(versions(recs, score.dex), args.min_games)
    print(f"{len(recs)} games -> {len(rows)} one-Pokemon swaps with {args.min_games}+ games on each side")
    kept = []
    for n, r in enumerate(rows):
        a, b = score(r["old"]["species"]), score(r["new"]["species"])
        if not a or not b or a["score"] is None or b["score"] is None:
            continue
        r["pred"] = {k: b[k] - a[k] for k in ("score", "chance", "fit", "popularity")}
        kept.append(r)
        if n % 2000 == 0:
            score.save()
    score.save()
    names = ["score", "chance", "fit", "popularity"]
    report(kept, names, "all swaps")
    report([r for r in kept if r["player"][0].endswith("bo3")], names, "Bo3")
    report([r for r in kept if not r["player"][0].endswith("bo3")], names, "ladder (Bo1)")


if __name__ == "__main__":
    main()
