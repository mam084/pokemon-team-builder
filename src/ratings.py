"""
ratings.py

Player skill ratings from Limitless results, so the match model can tell "this
team won" apart from "this player won".

An Elo rating per player, updated match by match in date / round order over
every Limitless match (with or without team lists). Every match gets each
player's rating *before* it was played, so a rating never sees the result it
is used to predict. New players start at 1500 and move faster (a bigger K)
until they have a few games:

    K = K_BASE * (1 + NEW_BOOST / (1 + games played))

K_BASE is chosen to predict best on the older tournaments only.

    python -m src.ratings      # tune K on the training period, print accuracy
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from src.formats import CURRENT

TOURNAMENT_DIR = Path(__file__).resolve().parent.parent / "data" / "tournaments"
START = 1500.0
K_BASE = 32.0   # tuned on the older tournaments (python -m src.ratings)
NEW_BOOST = 1.0


def expected(diff: float) -> float:
    """P(win) for a rating difference, standard Elo scale."""
    return 1 / (1 + 10 ** (-diff / 400))


def ordered_matches(regulation: str) -> list[dict]:
    """Every decided match, oldest first (by tournament date, then phase, then round)."""
    teams = json.loads((TOURNAMENT_DIR / f"{regulation}.json").read_text())["teams"]
    dates = {t["tournament"]: t["date"] for t in teams}
    matches = json.loads((TOURNAMENT_DIR / f"{regulation}_matches.json").read_text())["matches"]
    decided = [m for m in matches if m["winner"] in (m["p1"], m["p2"]) and m["tournament"] in dates]
    for m in decided:
        m["date"] = dates[m["tournament"]]
    return sorted(decided, key=lambda m: (m["date"], m["tournament"], m.get("phase") or 0, m.get("round") or 0))


def run(matches: list[dict], k_base: float = K_BASE, new_boost: float = NEW_BOOST) -> list[dict]:
    """Pre-match ratings for every match: [{..., r1, r2, g1, g2}] in the same order."""
    rating: dict[str, float] = defaultdict(lambda: START)
    games: dict[str, int] = defaultdict(int)
    out = []
    for m in matches:
        a, b = m["p1"], m["p2"]
        ra, rb, ga, gb = rating[a], rating[b], games[a], games[b]
        out.append({**m, "r1": ra, "r2": rb, "g1": ga, "g2": gb})
        score = 1.0 if m["winner"] == a else 0.0
        e = expected(ra - rb)
        rating[a] = ra + k_base * (1 + new_boost / (1 + ga)) * (score - e)
        rating[b] = rb + k_base * (1 + new_boost / (1 + gb)) * ((1 - score) - (1 - e))
        games[a], games[b] = ga + 1, gb + 1
    return out


def log_loss(rows: list[dict]) -> float:
    total = 0.0
    for r in rows:
        p = min(max(expected(r["r1"] - r["r2"]), 1e-6), 1 - 1e-6)
        total += -math.log(p if r["winner"] == r["p1"] else 1 - p)
    return total / len(rows)


def tune(regulation: str = CURRENT.regulation, train_share: float = 0.7) -> dict:
    """Pick K_BASE / NEW_BOOST by log loss on the older tournaments only."""
    matches = ordered_matches(regulation)
    tournaments = list(dict.fromkeys(m["tournament"] for m in matches))
    train_t = set(tournaments[: round(len(tournaments) * train_share)])
    best = None
    for k in (8, 12, 16, 24, 32, 48):
        for boost in (0, 1, 3, 6):
            rows = [r for r in run(matches, k, boost) if r["tournament"] in train_t]
            loss = log_loss(rows)
            if best is None or loss < best[0]:
                best = (loss, k, boost)
    return {"train_log_loss": round(best[0], 5), "k_base": best[1], "new_boost": best[2]}


if __name__ == "__main__":
    print(tune())
