"""
validate.py

Does the matchup score predict who wins? Checked on real tournament matches.

For every Limitless match where both players' team lists are known, the two
teams are scored against each other with the same pair scores the Matchups tab
uses (damage calcs both ways plus Speed). A logistic curve P(win) = 1 / (1 +
e^(-k * score)) is fitted on the older 70% of matches and judged on the newest
30%, against simple baselines:

- coin flip (50%)
- popularity: the team whose Pokemon are used more on the ladder wins
- vs-meta score: the team with the better score against the rebuilt meta wins

Team lists don't carry stat points, so each set gets its Pokemon's most common
ladder spread (usage.typical_spread). Each side Mega Evolves its first Mega
Stone, as the meta teams do.

Player skill dominates single matches, so even a perfect team model can't get
close to 100%; the question is whether the score adds real signal.

    python -m src.validate            # prints the report and writes data/evaluation/<reg>_matches.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"

import numpy as np

from src.analysis import build_members
from src.formats import CURRENT
from src.dex import Dex, load_dex
from src.evaluate import TOURNAMENT_DIR, load_tournament_teams, split_by_date
from src.matchup import best_bring, build_archetypes, pair_matrix, team_score
from src.swaps import SwapEngine
from src.usage import UsageData, load_usage


def match_rows(regulation: str, dex: Dex, usage: UsageData, doubles: bool = True,
               bring: int = 4, max_matches: int | None = None) -> list[dict]:
    teams = {(t["tournament"], t["player"]): t for t in load_tournament_teams(regulation, dex, usage=usage)}
    path = TOURNAMENT_DIR / f"{regulation}_matches.json"
    if not path.exists():
        return []
    matches = json.loads(path.read_text())["matches"]
    engine = SwapEngine(build_archetypes(usage, dex), usage, dex, doubles)
    members: dict = {}
    meta: dict = {}

    def side(key):
        if key not in members:
            sets = teams[key]["sets"]
            megas = [i for i, p in enumerate(sets) if p.is_mega(dex)]
            members[key] = build_members(sets, dex, evolve=megas[0] if megas else None)
            meta[key] = engine.overall(sets)
        return members[key]

    rows = []
    for m in matches:
        a, b = (m["tournament"], m["p1"]), (m["tournament"], m["p2"])
        if a not in teams or b not in teams or m["winner"] not in (m["p1"], m["p2"]):
            continue
        ma, mb = side(a), side(b)
        matrix = pair_matrix(ma, mb, doubles=doubles)
        reverse = pair_matrix(mb, ma, doubles=doubles)
        won = int(m["winner"] == m["p1"])

        def skill(key, result):  # record in the player's *other* matches of that event
            t = teams[key]
            games = (t["wins"] or 0) + (t["losses"] or 0) - 1
            return ((t["wins"] or 0) - result) / games if games > 0 else 0.5

        rows.append({
            "skill": skill(a, won) - skill(b, 1 - won),
            "tournament": m["tournament"], "date": teams[a]["date"],
            "h2h": team_score(matrix),
            "bring": best_bring(matrix, bring)[1] - best_bring(reverse, bring)[1],
            "meta": meta[a] - meta[b],
            "pop": float(np.mean([usage.species_usage(p.species, dex) for p in teams[a]["sets"]])
                         - np.mean([usage.species_usage(p.species, dex) for p in teams[b]["sets"]])),
            "won": won,
        })
        if max_matches and len(rows) >= max_matches:
            break
    return rows


def fit_logistic(x: np.ndarray, y: np.ndarray, steps: int = 200) -> float:
    """One-parameter logistic fit (no intercept: the score is antisymmetric) by Newton's method."""
    k = 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-k * x))
        grad = np.sum((y - p) * x)
        hess = -np.sum(p * (1 - p) * x * x)
        if hess == 0:
            break
        step = grad / hess
        k -= step
        if abs(step) < 1e-9:
            break
    return float(k)


def judge(x: np.ndarray, y: np.ndarray, k: float) -> dict:
    p = np.clip(1 / (1 + np.exp(-k * x)), 1e-6, 1 - 1e-6)
    decided = x != 0
    return {
        "accuracy": float(np.mean((x[decided] > 0) == (y[decided] == 1))) if decided.any() else 0.5,
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((p - y) ** 2)),
    }


def calibration(x: np.ndarray, y: np.ndarray, k: float, bins: int = 5) -> list[dict]:
    order = np.argsort(x)
    out = []
    for chunk in np.array_split(order, bins):
        out.append({"score": round(float(x[chunk].mean()), 2),
                    "predicted": round(float(np.mean(1 / (1 + np.exp(-k * x[chunk])))), 3),
                    "actual": round(float(y[chunk].mean()), 3), "matches": int(len(chunk))})
    return out


def validate(regulation: str = CURRENT.regulation, format_id: str = CURRENT.id,
             max_matches: int | None = None) -> dict:
    dex, usage = load_dex(regulation), load_usage(format_id, recent=False)  # past games: no later data
    rows = match_rows(regulation, dex, usage, max_matches=max_matches)
    if not rows:
        return {}
    # forward in time: fit on older tournaments, judge on the newest 30%
    fit_rows, test_rows = split_by_date(rows, 0.3)
    report = {"regulation": regulation, "matches": len(rows), "fit_matches": len(fit_rows),
              "test_matches": len(test_rows),
              "test_dates": [min(r["date"] for r in test_rows), max(r["date"] for r in test_rows)],
              "models": {}}
    y_fit = np.array([r["won"] for r in fit_rows], float)
    y_test = np.array([r["won"] for r in test_rows], float)
    for name, col in [("team vs team (bring 4)", "bring"), ("team vs team (all 6)", "h2h"),
                      ("score vs the meta", "meta"), ("popularity", "pop")]:
        x_fit = np.array([r[col] for r in fit_rows], float)
        x_test = np.array([r[col] for r in test_rows], float)
        k = fit_logistic(x_fit, y_fit)
        report["models"][name] = {"k": round(k, 4), **{m: round(v, 4) for m, v in judge(x_test, y_test, k).items()},
                                  "calibration": calibration(x_test, y_test, k)}
    report["models"]["coin flip"] = {"k": 0.0, "accuracy": 0.5, "log_loss": round(math.log(2), 4), "brier": 0.25}
    return report


def win_chance(score: float, k: float) -> float:
    return 1 / (1 + math.exp(-k * score))


if __name__ == "__main__":
    out = validate()
    if out:
        path = EVAL_DIR / f"{out['regulation']}_matches.json"
        path.write_text(json.dumps(out, indent=1))
        for name, m in out["models"].items():
            print(f"{name:26s} acc {m['accuracy']:.3f}  log loss {m['log_loss']:.4f}  brier {m['brier']:.4f}")
        print(f"-> {path}")
