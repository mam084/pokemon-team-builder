"""Team builder fixes, tested on the held-out week (Nov 2026).

Every model the builder uses (teammate model, the recommender's tournament pairings, match model, the
score's reference teams) is fitted on data from before the newest week. For each Pokemon that anchored
held-out teams with both winners (60%+ of games) and losers (40% or less), build three teams around it
and count how many of the five others each group shared ("lean to winners" = winners - losers).

Compared: before; the speed-mode fix (no credit for starting Tailwind on a Trick Room team or the
reverse); and that plus the core's pairings counted twice (src/builder.ANCHOR_WEIGHT). Also reported:
how many picks pair with the core, and how many teams run both Trick Room and Tailwind.

    python labs/builder_lab.py
"""
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from src import match_model as M
import src.builder as B
import src.plan as P
from src.builder import build_teams
from src.cooccurrence import Cooccurrence
from src.dex import load_dex
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.matchup import build_archetypes
from src.team_check import _teammates_before, _train_model
from src.team_rating import combined, meta_sides, percentile, teammate_fit, learned_vs_meta
from src.usage import load_usage

MIN_TEAMS = 6   # a core needs this many held-out teams to compare against


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
    usage.teammates = tm                                            # recommender synergy: pre-cut
    usage.cooc = Cooccurrence([t["sets"] for t in before], dex)     # tournament pairings: pre-cut
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
    from src.analysis import build_members
    from src.plan import team_plans

    # cores: each held-out team's Mega (else every member), with enough winners and losers to compare
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
    print(f"held-out week from {cut}: {len(held)} teams, {len(cores)} cores with {MIN_TEAMS}+ winners and losers\n")

    rows = []
    t0 = time.time()
    opposite = dict(P.OPPOSITE)
    variants = [("before", 1.0, False), ("fix + core x2", 2.0, True)]
    gaps = {}
    for mode in ("popular", "neutral"):
        for name, anchor, fix in variants:
            B.ANCHOR_WEIGHT, P.OPPOSITE = anchor, (opposite if fix else {})
            win_o, lose_o, scores, pair, clash = [], [], [], [], []
            for core in cores:
                built = build_teams(core, dex, usage, mode=mode, archetypes=archetypes, regulation=None)
                if not built:
                    continue
                core_num = dex.get_species(core).num
                sets = [{dex.get_species(p.species).num for p in b.sets} - {core_num} for b in built]
                win_o.append(np.mean([max(len(s & w) for s in sets) for w in groups[core]["win"]]))
                lose_o.append(np.mean([max(len(s & w) for s in sets) for w in groups[core]["lose"]]))
                scores.append(np.mean([percentile(score_of(b.sets), ref) for b in built]))
                croot = dex.sheet_id(dex.get_species(core))
                for b in built:
                    ids = [tm.index.get(dex.sheet_id(p.battle_form(dex))) for p in b.sets[1:]]
                    if croot in tm.index:
                        pair.append(np.mean([tm.W[tm.index[croot], i] > 0 for i in ids if i is not None]))
                    keys = {pl.key for pl in team_plans(build_members(b.sets, dex), dex) if not pl.needed}
                    clash.append({"trickroom", "tailwind"} <= keys)
            gap = np.array(win_o) - np.array(lose_o)
            rng = np.random.default_rng(0)
            boots = [gap[rng.integers(0, len(gap), len(gap))].mean() for _ in range(2000)]
            rows.append((mode, name, gap.mean()))
            gaps[(mode, name)] = gap
            print(f"{mode:8s} {name:14s} score {np.mean(scores):5.1f} | winners {np.mean(win_o):.2f} losers {np.mean(lose_o):.2f} "
                  f"lean {gap.mean():+.3f} ({np.percentile(boots, 2.5):+.3f} to {np.percentile(boots, 97.5):+.3f}) | "
                  f"pair with core {np.mean(pair):.0%} | TR+Tailwind {np.mean(clash):.0%}  [{time.time() - t0:.0f}s]", flush=True)
    for mode in ("popular", "neutral"):
        d = gaps[(mode, "fix + core x2")] - gaps[(mode, "before")]
        rng = np.random.default_rng(1)
        b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
        print(f"PAIRED {mode}: lean change {d.mean():+.3f} (95% {np.percentile(b, 2.5):+.3f} to {np.percentile(b, 97.5):+.3f}), "
              f"better for {np.mean(d > 0):.0%} of cores, worse for {np.mean(d < 0):.0%}")
    return rows


if __name__ == "__main__":
    main()
