"""
evaluate.py

How good are the recommendations? This checks them against teams real
players brought to tournaments (Limitless team lists, data/tournaments/).

Task - "complete the team": take a real six, hide one member, give the other
five (with their real sets) to the recommender, and see where the hidden
Pokemon lands in its ranking. Repeat for every member of every team.

    Hit@k  share of hidden Pokemon ranked in the top k
    MRR    mean of 1 / rank (0 when the Pokemon isn't in the candidate pool)

Because the recommender returns its five component scores separately, any
set of weights can be re-scored without recomputing them, which makes a grid
search over weights cheap. To avoid tuning on the answers, tournaments are
split by date: weights are tuned on the older 70% and every number reported
is measured on the newest 30% (a forward-in-time test).

Baselines on the same test set:
    popularity  rank by Smogon usage alone
    synergy     teammate co-occurrence lift alone (closest to the old recommender)
    random      expected Hit@k = k / pool size
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis import build_members
from src.dex import Dex, to_id
from src.recommend import DEFAULT_WEIGHTS, _root, recommend
from src.team import PokemonSet
from src.usage import UsageData

TOURNAMENT_DIR = Path(__file__).resolve().parent.parent / "data" / "tournaments"
SIGNALS = list(DEFAULT_WEIGHTS)
KS = (1, 5, 10)


@dataclass
class Query:
    tournament: str
    date: str
    hidden_root: str
    hidden_name: str
    table: pd.DataFrame      # raw recommender output for the other five


def load_tournament_teams(regulation: str, dex: Dex, path: Path | None = None) -> list[dict]:
    """Tournament teams as {date, tournament, placing, sets: [PokemonSet x6]}; unknown species are skipped."""
    path = path or TOURNAMENT_DIR / f"{regulation}.json"
    if not path.exists():
        return []
    teams = []
    for row in json.loads(path.read_text())["teams"]:
        sets = []
        for mon in row["team"]:
            species = dex.get_species(mon["species"])
            if species is None:
                break
            base = species
            if species.is_mega or species.battle_only:  # team sheets list the base forme
                base = dex.get_species(species.battle_only[0] if species.battle_only else species.base_species)
            item = mon["item"] if dex.get_item(mon["item"]) else ""
            ability = mon["ability"] if to_id(mon["ability"]) in {to_id(a) for a in base.abilities} else base.abilities[0]
            moves = [dex.get_move(m)["name"] for m in mon["moves"] if dex.get_move(m)]
            nature = mon["nature"] if dex.get_nature(mon["nature"]) else "Serious"
            sets.append(PokemonSet(species=base.name, item=item, ability=ability, nature=nature, moves=moves))
        if len(sets) == 6 and len({to_id(s.species) for s in sets}) == 6:
            teams.append({**{k: row[k] for k in ("date", "tournament", "placing", "players")}, "sets": sets})
    return teams


def build_queries(teams: list[dict], dex: Dex, usage: UsageData, doubles: bool = True,
                  pool_size: int = 80) -> list[Query]:
    queries = []
    for team in teams:
        for i, hidden in enumerate(team["sets"]):
            rest = team["sets"][:i] + team["sets"][i + 1:]
            table = recommend(build_members(rest, dex), dex, usage, doubles=doubles, raw=True,
                              pool_size=pool_size)
            hidden_species = dex.get_species(hidden.species)
            queries.append(Query(team["tournament"], team["date"], _root(hidden_species), hidden.species, table))
    return queries


def rank_of(query: Query, weights: dict) -> int | None:
    """1-based rank of the hidden Pokemon under these weights (None if not a candidate)."""
    t = query.table
    if t.empty:
        return None
    total = sum(weights.values()) or 1.0
    score = sum(weights[s] * t[s] for s in SIGNALS) / total
    score = np.where(t["second_mega"], score * 0.8, score)
    best = pd.Series(score, index=t.index).groupby(t["root"]).max().sort_values(ascending=False)
    if query.hidden_root not in best.index:
        return None
    return int(best.index.get_loc(query.hidden_root)) + 1


def metrics(queries: list[Query], weights: dict) -> dict:
    ranks = [rank_of(q, weights) for q in queries]
    n = len(ranks) or 1
    out = {f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
    out["mrr"] = sum(1 / r for r in ranks if r) / n
    out["in_pool"] = sum(1 for r in ranks if r is not None) / n
    return out


def split_by_date(teams: list[dict], test_share: float = 0.3) -> tuple[list[dict], list[dict]]:
    tournaments = sorted({(t["date"], t["tournament"]) for t in teams})
    cut = int(len(tournaments) * (1 - test_share))
    test_ids = {tid for _, tid in tournaments[cut:]}
    return [t for t in teams if t["tournament"] not in test_ids], [t for t in teams if t["tournament"] in test_ids]


def weight_grid(levels=(0.0, 0.5, 1.0)):
    for combo in itertools.product(levels, repeat=len(SIGNALS)):
        if any(combo):
            yield dict(zip(SIGNALS, combo))


def tune(queries: list[Query]) -> tuple[dict, dict]:
    """Best weights by MRR on the given (training) queries."""
    best_w, best_m = None, None
    for w in weight_grid():
        m = metrics(queries, w)
        if best_m is None or m["mrr"] > best_m["mrr"]:
            best_w, best_m = w, m
    total = sum(best_w.values())
    return {k: round(v / total, 3) for k, v in best_w.items()}, best_m


def evaluate(regulation: str, dex: Dex, usage: UsageData, doubles: bool = True,
             max_teams: int | None = None, path: Path | None = None) -> dict:
    teams = load_tournament_teams(regulation, dex, path)
    if max_teams:
        teams = teams[-max_teams:]
    train, test = split_by_date(teams)
    train_q = build_queries(train, dex, usage, doubles)
    test_q = build_queries(test, dex, usage, doubles)
    pool = int(np.median([q.table["root"].nunique() for q in test_q])) if test_q else 0

    tuned, train_metrics = tune(train_q)
    models = {
        "tuned weights": tuned,
        "default weights": DEFAULT_WEIGHTS,
        "synergy only": {s: float(s == "synergy") for s in SIGNALS},
        "popularity only": {s: float(s == "meta") for s in SIGNALS},
    }
    results = {name: metrics(test_q, w) for name, w in models.items()}
    results["random"] = {**{f"hit@{k}": min(1.0, k / pool) if pool else 0.0 for k in KS},
                         "mrr": float(np.mean([1 / r for r in range(1, pool + 1)])) if pool else 0.0,
                         "in_pool": 1.0}
    return {
        "regulation": regulation,
        "usage_month": usage.info.get("month"),
        "teams": len(teams),
        "train_teams": len(train), "test_teams": len(test),
        "train_tournaments": len({t["tournament"] for t in train}),
        "test_tournaments": len({t["tournament"] for t in test}),
        "test_dates": [min((t["date"] for t in test), default=""), max((t["date"] for t in test), default="")],
        "queries": len(test_q),
        "candidate_pool": pool,
        "tuned_weights": tuned,
        "train_mrr": round(train_metrics["mrr"], 4),
        "results": {name: {k: round(v, 4) for k, v in m.items()} for name, m in results.items()},
    }
