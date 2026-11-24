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
    hand-set    the weights the recommender used before this evaluation
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
from src.recommend import _root, recommend
from src.team import PokemonSet
from src.cooccurrence import Cooccurrence
from src.usage import UsageData, typical_spread

TOURNAMENT_DIR = Path(__file__).resolve().parent.parent / "data" / "tournaments"
SIGNALS = ["synergy", "defense", "offense", "roles", "meta", "plan"]
# The tuned weights of the lift-based recommender, before the learned teammate model.
LIFT_WEIGHTS = {"synergy": 0.762, "defense": 0.0, "offense": 0.0, "roles": 0.0, "meta": 0.19, "plan": 0.048}
# The weights the recommender shipped with before this evaluation existed (chosen by hand).
HAND_SET_WEIGHTS = {"synergy": 0.30, "defense": 0.25, "offense": 0.15, "roles": 0.15, "meta": 0.15, "plan": 0.0}
KS = (1, 5, 10)


@dataclass
class Query:
    tournament: str
    date: str
    hidden_root: str
    hidden_name: str
    table: pd.DataFrame      # raw recommender output for the other five

    def __post_init__(self):
        # Pre-arrange the table for fast re-ranking: rows sorted by root, so a
        # weighted score's per-Pokemon max is one np.maximum.reduceat call.
        t = self.table
        if t.empty:
            self.components = np.zeros((0, len(SIGNALS)))
            self.mega, self.starts, self.hidden_group = np.zeros(0, bool), np.zeros(0, int), None
            return
        t = t.sort_values("root", kind="stable")
        self.components = t[SIGNALS].to_numpy(dtype=float)
        self.mega = t["extra_mega"].to_numpy(dtype=bool)
        roots = t["root"].to_numpy()
        self.starts = np.flatnonzero(np.r_[True, roots[1:] != roots[:-1]])
        group_roots = roots[self.starts]
        hits = np.flatnonzero(group_roots == self.hidden_root)
        self.hidden_group = int(hits[0]) if len(hits) else None


REGIONAL = {"Alolan": "Alola", "Galarian": "Galar", "Hisuian": "Hisui", "Paldean": "Paldea"}
SPECIAL_NAMES = {
    "Eternal Flower Floette": "Floette-Eternal",
    "Floette": "Floette-Eternal",          # only the Eternal Flower forme is legal (and has a Mega)
    "Paldean Tauros Aqua Breed": "Tauros-Paldea-Aqua",
    "Paldean Tauros Blaze Breed": "Tauros-Paldea-Blaze",
    "Paldean Tauros Combat Breed": "Tauros-Paldea-Combat",
}


def normalize_species(name: str, dex: Dex) -> str:
    """Limitless display names ("Hisuian Arcanine", "Wash Rotom") -> Showdown names."""
    if dex.get_species(name):
        return name
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]
    first, _, rest = name.partition(" ")
    if first in REGIONAL:
        return f"{rest}-{REGIONAL[first]}"
    if rest == "Rotom":  # Wash / Heat / Mow / Frost / Fan Rotom
        return f"Rotom-{first}"
    return name


def load_tournament_teams(regulation: str, dex: Dex, path: Path | None = None,
                          usage: UsageData | None = None, keep=None) -> list[dict]:
    """Tournament teams as {date, tournament, placing, player, wins, losses, sets: [PokemonSet x6]};
    unknown species are skipped. Team lists don't publish stat points, so with usage given
    each set gets its Pokemon's most common ladder spread (an estimate). `keep(row)` picks rows first."""
    path = path or TOURNAMENT_DIR / f"{regulation}.json"
    if not path.exists():
        return []
    teams = []
    for row in json.loads(path.read_text())["teams"]:
        if keep is not None and not keep(row):
            continue
        sets = []
        for mon in row["team"]:
            species = dex.get_species(normalize_species(mon["species"], dex))
            if species is None:
                break
            base = species
            if species.is_mega or species.battle_only:  # team sheets list the base forme
                base = dex.get_species(species.battle_only[0] if species.battle_only else species.base_species)
            item = mon["item"] if dex.get_item(mon["item"]) else ""
            ability = mon["ability"] if to_id(mon["ability"]) in {to_id(a) for a in base.abilities} else base.abilities[0]
            moves = [dex.get_move(m)["name"] for m in mon["moves"] if dex.get_move(m)]
            nature = mon["nature"] if dex.get_nature(mon["nature"]) else "Serious"
            pset = PokemonSet(species=base.name, item=item, ability=ability, nature=nature, moves=moves)
            if usage is not None:
                pset.sps = typical_spread(usage, pset, dex) or pset.sps
            sets.append(pset)
        if len(sets) == 6 and len({to_id(s.species) for s in sets}) == 6:
            teams.append({**{k: row.get(k) for k in ("date", "tournament", "placing", "players", "player",
                                                      "wins", "losses")}, "sets": sets})
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
    """1-based rank of the hidden Pokemon under these weights (None if not a candidate).
    Ties count against it (a tie with 3 others ranks it below them), so results are never optimistic."""
    if query.hidden_group is None:
        return None
    w = np.array([weights[s] for s in SIGNALS], dtype=float)
    score = query.components @ w / (w.sum() or 1.0)
    score = np.where(query.mega, score * 0.8, score)
    best = np.maximum.reduceat(score, query.starts)
    return int((best >= best[query.hidden_group]).sum())


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


GRID_SIGNALS = ["synergy", "defense", "offense", "roles", "meta"]
PLAN_STEPS = (0.05, 0.1, 0.15, 0.2, 0.3)


def weight_grid(levels=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """Full grid over the five original signals (plan fixed at 0)."""
    for combo in itertools.product(levels, repeat=len(GRID_SIGNALS)):
        if any(combo):
            yield {**dict(zip(GRID_SIGNALS, combo)), "plan": 0.0}


def tune(queries: list[Query]) -> tuple[dict, dict]:
    """Best weights by MRR on the given (training) queries: a grid over the five
    original signals, then a line search adding the plan signal on top."""
    best_w, best_m = None, None
    for w in weight_grid():
        m = metrics(queries, w)
        if best_m is None or m["mrr"] > best_m["mrr"]:
            best_w, best_m = w, m
    scale = sum(best_w.values())
    for step in PLAN_STEPS:
        w = {**best_w, "plan": step * scale}
        m = metrics(queries, w)
        if m["mrr"] > best_m["mrr"]:
            best_w, best_m = w, m
    total = sum(best_w.values())
    return {k: round(v / total, 3) for k, v in best_w.items()}, best_m


def _holdout_teammates(production, pairs_from: list[dict], train: list[dict], dex: Dex):
    """A teammate model fitted only on data older than the tuning tournaments."""
    from datetime import datetime, timezone
    from src.replays import load_records
    from src.synergy import (L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records, replay_rows,
                             tournament_rows)
    if not train:
        return None
    cut = datetime.fromisoformat(min(t["date"] for t in train)).replace(tzinfo=timezone.utc).timestamp()
    records = recent_records([r for f in production.formats for r in load_records(f)], end=cut - 1)
    rows = tournament_rows(pairs_from, dex, weight=TOURNAMENT_WEIGHT) + replay_rows(records, dex)
    model = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)
    model.formats = production.formats
    return model


def evaluate(regulation: str, dex: Dex, usage: UsageData, doubles: bool = True,
             max_teams: int | None = None, path: Path | None = None) -> dict:
    teams = load_tournament_teams(regulation, dex, path)
    if max_teams:
        teams = teams[-max_teams:]
    train, test = split_by_date(teams)
    # Synergy also learns from tournament pairings (src/cooccurrence.py). To keep the test
    # honest, those pairings come only from the oldest tournaments; the weights are tuned on
    # the next ones and tested on the newest - never on teams the pairings saw.
    pairs_from, train = split_by_date(train, 0.4) if usage.cooc is not None else ([], train)
    saved_cooc, saved_tm = usage.cooc, usage.teammates
    usage.cooc = Cooccurrence([t["sets"] for t in pairs_from], dex) if pairs_from else None
    # The learned teammate model (src/synergy.py) the same way: refitted on the oldest
    # tournaments plus replays uploaded before the tuning tournaments, never on test teams.
    usage.teammates = _holdout_teammates(saved_tm, pairs_from, train, dex) if saved_tm is not None else None
    lift_q = None
    try:
        train_q = build_queries(train, dex, usage, doubles)
        test_q = build_queries(test, dex, usage, doubles)
        if usage.teammates is not None:  # the same test with lift synergy, for comparison
            usage.teammates = None
            lift_q = build_queries(test, dex, usage, doubles)
    finally:
        usage.cooc, usage.teammates = saved_cooc, saved_tm
    pool = int(np.median([q.table["root"].nunique() for q in test_q])) if test_q else 0

    tuned, train_metrics = tune(train_q)
    models = {
        "tuned weights": tuned,
        "hand-set weights": HAND_SET_WEIGHTS,
        "synergy only": {s: float(s == "synergy") for s in SIGNALS},
        "popularity only": {s: float(s == "meta") for s in SIGNALS},
    }
    results = {name: metrics(test_q, w) for name, w in models.items()}
    if lift_q is not None:
        results["before: lift synergy"] = metrics(lift_q, LIFT_WEIGHTS)
    results["random"] = {**{f"hit@{k}": min(1.0, k / pool) if pool else 0.0 for k in KS},
                         "mrr": float(np.mean([1 / r for r in range(1, pool + 1)])) if pool else 0.0,
                         "in_pool": 1.0}
    return {
        "regulation": regulation,
        "usage_month": usage.info.get("month"),
        "teams": len(teams),
        "pairing_teams": len(pairs_from), "train_teams": len(train), "test_teams": len(test),
        "train_tournaments": len({t["tournament"] for t in train}),
        "test_tournaments": len({t["tournament"] for t in test}),
        "test_dates": [min((t["date"] for t in test), default=""), max((t["date"] for t in test), default="")],
        "queries": len(test_q),
        "candidate_pool": pool,
        "tuned_weights": tuned,
        "train_mrr": round(train_metrics["mrr"], 4),
        "results": {name: {k: round(v, 4) for k, v in m.items()} for name, m in results.items()},
    }
