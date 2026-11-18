"""
team_check.py

The match model is judged one match at a time (src/match_model.py), but the app uses it to *rank
teams*, and the swap search keeps applying the best swap until none is left. This checks both on
the held-out week, with everything fitted only on data from before it:

1. Ranking real teams: score every team from the held-out tournaments by its win chance vs the
   meta teams, then see how those teams actually did, by quarter. Done with and without the
   trust bounds (src/match_model.trust_bounds), which must not rank real teams worse.
2. The search: from a few starting teams, keep applying the best swap. Without bounds it walked
   to ~66% (four Wide Guard users) while the best real team scores ~58%; with bounds it should
   stop at the best real team's score instead of extrapolating past it.
3. What swaps are judged by: the team score (teammate fit plus win chance, src/team_rating.py) vs
   win chance alone, ranking the same held-out teams (teammate model also fitted before the cut).
   And where the team-score search ends up: how many real tournament teams share 5+ of its six.

    python -m src.team_check      # writes data/evaluation/<reg>_team_check.json
"""

from __future__ import annotations

import json
import random
import time

import numpy as np

from src import match_model as M
from src.formats import CURRENT
from src.matchup import build_archetypes

EVAL_DIR = M.EVAL_DIR
REFERENCE_TEAMS = 1200   # real teams from before the cut that set the bounds
STARTS = 3               # meta teams the search starts from
MAX_STEPS = 12


def _train_model(df):
    tr, te = M.time_split(df)
    feats = M.SKILL + M.FEATURES
    _, c, w = M._choose(df[tr], feats, [])
    fit = M.Logit(c, 0, w).fit(M._design(df[tr], [], feats), df[tr]["won"].to_numpy(float))
    return {"model": {"features": feats, "species": [], "coef": [float(b) for b in fit.coef_]}}, tr, te


def _quarters(chances: np.ndarray, wins: np.ndarray, games: np.ndarray) -> list[dict]:
    order = np.argsort(chances)
    out = []
    for idx in np.array_split(order, 4):
        out.append({"predicted": round(float(chances[idx].mean()), 4),
                    "actual": round(float(wins[idx].sum() / games[idx].sum()), 4),
                    "teams": int(len(idx)), "games": int(games[idx].sum())})
    return out


def _teammates_before(cut: str, teams, dex):
    """The learned teammate model refitted on tournaments and replays from before the cut."""
    import datetime as dt

    from src.replays import load_records
    from src.synergy import (L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records, replay_rows,
                             tournament_rows)
    end = dt.datetime.fromisoformat(cut).replace(tzinfo=dt.timezone.utc).timestamp() - 1
    recs = recent_records([r for f in CURRENT.replays for r in load_records(f)], end=end)
    rows = tournament_rows([t for t in teams if t["date"] < cut], dex, weight=TOURNAMENT_WEIGHT) + replay_rows(recs, dex)
    return TeammateModel(build_vocab(rows)).fit(rows, l2=L2)


def _climb(team, engine, dex, usage, pool) -> tuple[float, int, list[str], list]:
    from src.swaps import suggest_swaps
    seen = set()
    for step in range(MAX_STEPS):
        key = tuple(sorted(p.species for p in team))
        if key in seen:
            break
        seen.add(key)
        df = suggest_swaps(team, dex, usage, engine, pool=pool, top_n=1, same_role=False)
        if df.empty:
            return engine.win_chance(team), step, [p.species for p in team], team
        r = df.iloc[0]
        team = team[:int(r["slot"])] + [r["_set"]] + team[int(r["slot"]) + 1:]
    return engine.win_chance(team), MAX_STEPS, [p.species for p in team], team


def run(regulation: str = CURRENT.regulation, format_id: str = CURRENT.id, verbose: bool = True) -> dict:
    from scipy.stats import spearmanr

    from src.dex import load_dex
    from src.evaluate import load_tournament_teams
    from src.swaps import SwapEngine, mode_pool
    from src.team_rating import combined, meta_sides, raw_pushes, teammate_fit
    from src.usage import load_usage

    start = time.time()
    dex, usage = load_dex(regulation), load_usage(format_id, recent=False)
    df = M.add_skill(M.build_dataset(regulation, format_id, verbose=False), regulation)
    model, tr, te = _train_model(df)
    cut = str(df[te]["date"].min())
    test_t = set(df[te]["tournament"])
    archetypes = build_archetypes(usage, dex, team_size=6)
    sides, weights = meta_sides(archetypes, usage, dex)

    teams = [t for t in load_tournament_teams(regulation, dex, usage=usage) if len(t["sets"]) == 6]
    before = [t for t in teams if t["date"] < cut]
    random.Random(0).shuffle(before)
    tm = _teammates_before(cut, teams, dex)
    pushes, ref_chances, ref_fits = [], [], []
    for t in before[:REFERENCE_TEAMS]:
        pushes += raw_pushes(t["sets"], dex, usage, model, sides)
        ref_chances.append(_vs_meta(t["sets"], dex, usage, model, sides, weights))
        ref_fits.append(teammate_fit(t["sets"], dex, tm))
    guarded = dict(model, trust=M.trust_bounds(pushes, ref_chances))
    ok = [f is not None for f in ref_fits]
    fits_arr, ch_arr = np.array([f for f in ref_fits if f is not None]), np.array(ref_chances)[ok]
    ref = {"fit_mean": float(fits_arr.mean()), "fit_sd": float(fits_arr.std()),
           "chance_mean": float(ch_arr.mean()), "chance_sd": float(ch_arr.std())}
    ref["combined_sorted"] = sorted(combined(f, c, ref) for f, c in zip(fits_arr, ch_arr))
    if verbose:
        print(f"bounds from {len(ref_chances)} teams before {cut}: best real team "
              f"{max(ref_chances):.1%}, {time.time() - start:.0f}s", flush=True)

    # 1. ranking the held-out week's real teams
    held = [t for t in teams if t["tournament"] in test_t and t["wins"] + t["losses"] > 0]
    wins = np.array([t["wins"] for t in held], float)
    games = np.array([t["wins"] + t["losses"] for t in held], float)
    ranking = {}
    for name, m in (("without bounds", model), ("with bounds", guarded)):
        ch = np.array([_vs_meta(t["sets"], dex, usage, m, sides, weights) for t in held])
        ranking[name] = {"spearman": round(float(spearmanr(ch, wins / games).correlation), 4),
                         "quarters": _quarters(ch, wins, games), "max": round(float(ch.max()), 4),
                         "_chances": ch}
    changed = np.abs(ranking["with bounds"]["_chances"] - ranking["without bounds"]["_chances"]) > 0.001
    # 3. team score (fit + win chance) vs win chance alone, on the same held-out teams
    win = ranking["with bounds"]["_chances"]
    fit = np.array([teammate_fit(t["sets"], dex, tm) for t in held], dtype=float)
    has = ~np.isnan(fit)
    score = np.array([combined(f, c, ref) for f, c in zip(fit[has], win[has])])
    rate = wins[has] / games[has]
    rho = lambda x, idx: float(spearmanr(x[idx], rate[idx]).correlation)  # noqa: E731
    rng = np.random.default_rng(0)
    draws = [rng.integers(0, has.sum(), has.sum()) for _ in range(1000)]
    gains = [rho(score, d) - rho(win[has], d) for d in draws]
    objective = {"teams": int(has.sum()),
                 "win chance": {"spearman": round(rho(win[has], slice(None)), 4),
                                "quarters": _quarters(win[has], wins[has], games[has])},
                 "team score": {"spearman": round(rho(score, slice(None)), 4),
                                "quarters": _quarters(score, wins[has], games[has])},
                 "gain_ci": [round(float(np.percentile(gains, 2.5)), 4), round(float(np.percentile(gains, 97.5)), 4)]}
    for r in ranking.values():
        r.pop("_chances")
    if verbose:
        print(f"ranked {len(held)} held-out teams, {time.time() - start:.0f}s", flush=True)

    # 2. the swap search, from the most popular meta teams
    pool = mode_pool(usage, "neutral", dex)
    real_sets = [frozenset(dex.get_species(p.species).num for p in t["sets"]) for t in teams]
    search = []
    for a in archetypes[:STARTS]:
        team = [p for p in (usage.popular_set(n, dex) for n in a.members) if p is not None]
        row = {"start": a.name}
        for name, m in (("without bounds", model), ("with bounds", guarded)):
            engine = SwapEngine(archetypes, usage, dex, True)
            engine.attach_model(m)
            first = engine.win_chance(team)
            end, steps, final, _ = _climb(team, engine, dex, usage, pool)
            row[name] = {"from": round(first, 4), "to": round(end, 4), "swaps": steps, "team": final}
        # the app's search: judged by team score (bounds on, teammate model from before the cut)
        engine = SwapEngine(archetypes, usage, dex, True)
        engine.attach_model(guarded)
        engine.attach_rating(ref, tm)
        first = engine.rating(team, engine.win_chance(team))
        end_win, steps, final, final_sets = _climb(team, engine, dex, usage, pool)
        nums = frozenset(dex.get_species(n).num for n in final)
        row["team score"] = {"from": round(first[1]), "to": round(engine.rating(final_sets, end_win)[1]),
                             "win": round(end_win, 4), "swaps": steps, "team": final,
                             "real_5of6": sum(len(nums & r) >= 5 for r in real_sets)}
        search.append(row)
        if verbose:
            print(f"  {a.name}: {row['without bounds']['to']:.1%} without bounds, "
                  f"{row['with bounds']['to']:.1%} with, {time.time() - start:.0f}s", flush=True)

    return {"regulation": regulation, "cut": cut, "test_dates": [cut, str(df[te]["date"].max())],
            "reference_teams": len(ref_chances), "best_real_team": round(max(ref_chances), 4),
            "held_out_teams": len(held), "changed_share": round(float(changed.mean()), 4),
            "ranking": ranking, "objective": objective, "search": search}


def _vs_meta(sets, dex, usage, model, sides, weights) -> float:
    from src.team_rating import learned_vs_meta
    return learned_vs_meta(sets, dex, usage, model, sides, weights)


if __name__ == "__main__":
    report = run()
    out = EVAL_DIR / f"{report['regulation']}_team_check.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"-> {out}")
