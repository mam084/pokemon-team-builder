"""
team_rating.py

One number for "how good does this team look", used to order the auto-builder's teams.

Tested on the held-out week of tournaments (scripts/app_vs_results.py), with models fitted only
on earlier data. Two of the app's signals tracked real results beyond the players' Elo:

- teammate fit: how naturally each member sits next to the other five, by the learned teammate
  model (mean log P(member | rest)). Strongest single signal.
- learned win chance vs the meta teams (src/match_model.py), usage-weighted.

Their equal-weight sum (each as a z-score against real tournament teams) did best: teams in its
top quarter won 55.9% of games vs 45.2% for the bottom quarter. The damage-calc score vs the meta,
which the builder used to sort by, was the weakest of the app's signals.

The z-scores and percentiles are against tournament teams from the current regulation, saved by
`python -m src.team_rating` (data/evaluation/<regulation>_team_rating.json), along with the
match model's trust bounds: how far real teams' scores vs the meta reach (src/match_model.py).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np

from src.analysis import mega_variants
from src.dex import Dex
from src.formats import CURRENT
from src.match_model import load_model as load_match_model
from src.match_model import cap_chance, contributions, predict_match, team_side, trust_bounds
from src.matchup import build_archetypes, opponent_members
from src.synergy import root_of

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"
SAMPLE = 1200   # tournament teams used for the reference distribution


def teammate_fit(sets, dex: Dex, tm) -> float | None:
    """Mean log P(member | the other five) by the learned teammate model."""
    if tm is None:
        return None
    roots = [r for s in sets if (r := root_of(s.species, dex))]
    probs = [x["prob"] for x in tm.fit_check(roots) if x["prob"]]
    return float(np.mean(np.log(probs))) if probs else None


def meta_sides(archetypes, usage, dex: Dex) -> tuple[list[dict], np.ndarray]:
    sides = [team_side(opponent_members(a.members, usage, dex),
                       [s for s in (usage.popular_set(m, dex) for m in a.members) if s], dex, usage, None, meta=0.0)
             for a in archetypes]
    w = np.array([a.popularity for a in archetypes], float)
    return sides, w / w.sum()


def learned_vs_meta(sets, dex: Dex, usage, model: dict, sides: list[dict], weights: np.ndarray) -> float:
    """Usage-weighted learned win chance against the meta teams (best Mega choice per opponent),
    kept inside what real teams reach when the model has trust bounds."""
    mine = [team_side(m, sets, dex, usage, None, meta=0.0) for _, m in mega_variants(sets, dex)]
    chances = np.array([max(predict_match(model, a, b) for a in mine) for b in sides])
    return cap_chance(model, float(chances @ weights))


def raw_pushes(sets, dex: Dex, usage, model: dict, sides: list[dict]) -> list[dict[str, float]]:
    """Unclipped feature pushes of one team vs each meta team (its best Mega choice per opponent)."""
    mine = [team_side(m, sets, dex, usage, None, meta=0.0) for _, m in mega_variants(sets, dex)]
    out = []
    for b in sides:
        options = [dict(contributions(model, a, b, clip=False)) for a in mine]
        out.append(max(options, key=lambda d: sum(d.values())))
    return out


def load_reference(regulation: str = CURRENT.regulation) -> dict | None:
    path = EVAL_DIR / f"{regulation}_team_rating.json"
    return json.loads(path.read_text()) if path.exists() else None


def combined(fit: float, chance: float, ref: dict) -> float:
    return (fit - ref["fit_mean"]) / ref["fit_sd"] + (chance - ref["chance_mean"]) / ref["chance_sd"]


def percentile(score: float, ref: dict) -> float:
    """Share of real tournament teams this one rates above (0-100)."""
    s = np.asarray(ref["combined_sorted"])
    return float(100 * np.searchsorted(s, score) / len(s))


def build_reference(regulation: str = CURRENT.regulation, format_id: str = CURRENT.id) -> dict:
    from src.dex import load_dex
    from src.evaluate import load_tournament_teams
    from src.synergy import load_model as load_teammates
    from src.usage import load_usage

    dex, usage = load_dex(regulation), load_usage(format_id)
    tm, model = load_teammates(regulation), load_match_model(regulation, trust=False)  # bounds come from raw scores
    teams = load_tournament_teams(regulation, dex, usage=usage)
    random.Random(0).shuffle(teams)
    sides, weights = meta_sides(build_archetypes(usage, dex, team_size=6), usage, dex)
    fits, chances, pushes = [], [], []
    for t in teams[:SAMPLE]:
        f = teammate_fit(t["sets"], dex, tm)
        if f is None:
            continue
        fits.append(f)
        chances.append(learned_vs_meta(t["sets"], dex, usage, model, sides, weights))
        pushes += raw_pushes(t["sets"], dex, usage, model, sides)
    trust = trust_bounds(pushes, chances)
    fits, chances = np.array(fits), np.array(chances)
    ref = {"teams": int(len(fits)), "fit_mean": float(fits.mean()), "fit_sd": float(fits.std()),
           "chance_mean": float(chances.mean()), "chance_sd": float(chances.std()), "trust": trust}
    ref["combined_sorted"] = sorted(round(combined(f, c, ref), 4) for f, c in zip(fits, chances))
    return ref


if __name__ == "__main__":
    ref = build_reference()
    path = EVAL_DIR / f"{CURRENT.regulation}_team_rating.json"
    path.write_text(json.dumps(ref))
    print(f"{ref['teams']} tournament teams -> {path}")
