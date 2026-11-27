"""Builder: variety across the three teams (DIVERSITY_WEIGHT), tested on the held-out week (Nov 2026).

Same test as labs/threat_builder_lab.py: every model is fitted before the newest week; for each Pokemon
that anchored held-out teams with both winners (60%+ of games) and losers (40% or less), build three
teams around it and count how many of the five others each group shared ("lean" = winners - losers).
Also the team score's percentile (teammate fit + learned win chance), the learned win chance alone
(the "On paper" lens, no popularity in it), and how many different partners the three teams use (out of 15). Variants:
DIVERSITY_WEIGHT, score points a pick loses per earlier team that already has it.

Why: the fill is greedy, so the same top picks win every slot (around Baxcalibur, all three Popular teams
shared Ninetales-Alola, Rillaboom and Incineroar), and cores that need two steps to show up (Sneasler ->
Kingambit -> Basculegion) never form.

    python labs/diversity_lab.py
"""

import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from src import match_model as M
import src.builder as B
from src.builder import build_teams
from src.cooccurrence import Cooccurrence
from src.dex import load_dex
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.matchup import build_archetypes
from src.replays import load_records
from src.sheet_sets import sheet_sets_from
from src.team_check import _teammates_before, _train_model
from src.team_rating import combined, meta_sides, percentile, teammate_fit, learned_vs_meta
from src.usage import load_usage

MIN_TEAMS = 6


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    df = M.add_skill(M.build_dataset(verbose=False), reg)
    model, tr, te = _train_model(df)
    cut = str(df[te]["date"].min())
    teams = [t for t in load_tournament_teams(reg, dex, usage=usage) if len(t["sets"]) == 6]
    before = [t for t in teams if t["date"] < cut]
    held = [t for t in teams if t["date"] >= cut and t["wins"] + t["losses"] >= 4]
    tm = _teammates_before(cut, teams, dex)
    usage.teammates = tm
    usage.cooc = Cooccurrence([t["sets"] for t in before], dex)
    cut_ts = datetime.strptime(cut, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    bo3 = [r for f in CURRENT.replays for r in load_records(f) if (r.get("uploadtime") or 0) < cut_ts and r.get("sheets")]
    sheets = sheet_sets_from(before, bo3, dex, end=cut, days=30)
    archetypes = build_archetypes(usage, dex, team_size=6)
    sides, weights = meta_sides(archetypes, usage, dex)
    random.Random(0).shuffle(before)
    fits, chances = [], []
    for t in before[:1200]:
        f = teammate_fit(t["sets"], dex, tm)
        if f is not None:
            fits.append(f)
            chances.append(learned_vs_meta(t["sets"], dex, usage, model, sides, weights))
    fits, chances = np.array(fits), np.array(chances)
    ref = {"fit_mean": float(fits.mean()), "fit_sd": float(fits.std()),
           "chance_mean": float(chances.mean()), "chance_sd": float(chances.std())}
    ref["combined_sorted"] = sorted(combined(f, c, ref) for f, c in zip(fits, chances))
    score_of = lambda sets: combined(teammate_fit(sets, dex, tm),  # noqa: E731
                                     learned_vs_meta(sets, dex, usage, model, sides, weights), ref)

    groups = defaultdict(lambda: {"win": [], "lose": []})
    for t in held:
        rate = t["wins"] / (t["wins"] + t["losses"])
        if 0.4 < rate < 0.6:
            continue
        names = {dex.get_species(p.species).num: p.species for p in t["sets"]}
        for num, name in names.items():
            groups[name]["win" if rate >= 0.6 else "lose"].append(set(names) - {num})
    cores = [c for c, g in groups.items() if len(g["win"]) >= MIN_TEAMS and len(g["lose"]) >= MIN_TEAMS
             and usage.popular_set(c, dex) is not None]
    print(f"held-out week from {cut}: {len(held)} teams, {len(cores)} cores\n", flush=True)

    variants = [("weight 0", 0.0), ("weight 5", 5.0), ("weight 10", 10.0), ("weight 20", 20.0)]
    gaps, chance_d = {}, {}
    t0 = time.time()
    usage.sheet_sets = sheets
    for mode in ("popular", "neutral", "hidden"):
        for name, wgt in variants:
            B.DIVERSITY_WEIGHT = wgt
            win_o, lose_o, scores, papers, variety = [], [], [], [], []
            for core in cores:
                built = build_teams(core, dex, usage, mode=mode, archetypes=archetypes, regulation=None)
                if not built:
                    win_o.append(np.nan); lose_o.append(np.nan); papers.append(np.nan)
                    continue
                core_num = dex.get_species(core).num
                sets = [{dex.get_species(p.species).num for p in b.sets} - {core_num} for b in built]
                win_o.append(np.mean([max(len(s & w_) for s in sets) for w_ in groups[core]["win"]]))
                lose_o.append(np.mean([max(len(s & l_) for s in sets) for l_ in groups[core]["lose"]]))
                scores.append(np.mean([percentile(score_of(b.sets), ref) for b in built]))
                papers.append(np.mean([learned_vs_meta(b.sets, dex, usage, model, sides, weights) for b in built]))
                variety.append(len(set().union(*sets)))
            gap = np.array(win_o) - np.array(lose_o)
            gaps[(mode, name)], chance_d[(mode, name)] = gap, np.array(papers)
            g = gap[~np.isnan(gap)]
            rng = np.random.default_rng(0)
            boots = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(2000)]
            print(f"{mode:8s} {name:10s} score {np.mean(scores):5.1f} | on paper {np.nanmean(papers):.4f} | "
                  f"lean {g.mean():+.3f} ({np.percentile(boots, 2.5):+.3f} to {np.percentile(boots, 97.5):+.3f}) | "
                  f"partners {np.mean(variety):.1f}/15  [{time.time() - t0:.0f}s]", flush=True)
    for mode in ("popular", "neutral", "hidden"):
        for name, _ in variants[1:]:
            for label, table in (("lean", gaps), ("on paper", chance_d)):
                d = table[(mode, name)] - table[(mode, "weight 0")]
                d = d[~np.isnan(d)]
                rng = np.random.default_rng(1)
                b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
                print(f"PAIRED {mode:8s} {name:10s} {label:8s} vs weight 0: {d.mean():+.4f} "
                      f"(95% {np.percentile(b, 2.5):+.4f} to {np.percentile(b, 97.5):+.4f})")


if __name__ == "__main__":
    main()
