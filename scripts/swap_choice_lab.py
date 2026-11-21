"""
swap_choice_lab.py - when a player replaces one Pokemon, would the app have suggested what they chose?

Real swaps come from rated ladder and Bo3 replays: a player's next team differs from the last by exactly
one Pokemon (scripts/swap_quality_lab.py). The teammate model is fitted only on teams from before the
newest 30% of games and judged on swaps made after that, so it never saw them. For each swap (old member
X, the other five R, new member Y), every candidate the app could offer is ranked by each method, and we
record where Y lands. This measures whether suggestions are ones players actually find sensible; whether
they win more is scripts/swap_quality_lab.py's question.

    python scripts/swap_choice_lab.py
"""

from __future__ import annotations

import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.formats import CURRENT  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.analysis import build_members  # noqa: E402
from src.roles import job, plan_roles, set_roles  # noqa: E402
from src.plan import team_plans  # noqa: E402
from src.swaps import PLAN_ROLE  # noqa: E402
from src.synergy import (L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records,  # noqa: E402
                         replay_rows, root_of, tournament_rows)
from src.usage import load_usage  # noqa: E402
from scripts.swap_quality_lab import swaps, versions  # noqa: E402

FMT = CURRENT.id
CACHE = Path("/tmp/swap_choice_model.pkl")
BOOT = 1000


def main():
    dex, usage = load_dex(CURRENT.regulation), load_usage(FMT)
    recs = [r for f in (FMT, FMT + "bo3") for r in load_records(f)]
    times = sorted(r.get("uploadtime") or 0 for r in recs)
    cut = times[int(len(times) * 0.7)]
    # teammate model fitted on teams from before the cut only
    if CACHE.exists():
        tm = pickle.loads(CACHE.read_bytes())
    else:
        from datetime import datetime, timezone
        teams = load_tournament_teams(CURRENT.regulation, dex)
        old_t = [t for t in teams if datetime.fromisoformat(t["date"]).replace(tzinfo=timezone.utc).timestamp() < cut]
        rows = tournament_rows(old_t, dex, TOURNAMENT_WEIGHT) + replay_rows(recent_records(recs, end=cut - 1), dex)
        tm = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)
        CACHE.write_bytes(pickle.dumps(tm))
    # what players who dropped X switched to, from swaps made before the cut
    subs = defaultdict(lambda: defaultdict(int))
    for s in swaps(versions([r for r in recs if (r.get("uploadtime") or 0) < cut], dex), 1):
        subs[s["out"]][s["in"]] += 1
    # swaps whose new team was first played after the cut
    recs_after = [r for r in recs if (r.get("uploadtime") or 0) >= cut]
    rows = swaps(versions(recs_after, dex), 1)
    print(f"{len(rows)} real one-Pokemon swaps after the cut; teammate model knows {len(tm.vocab)} Pokemon")

    # candidates: the app's Neutral pool, one entry per root, with each one's most common set
    pool = []
    seen = set()
    for name, _ in usage.ranked():
        sp = dex.get_species(name)
        r = dex.sheet_id(sp) if sp else None
        if r and r not in seen:
            seen.add(r)
            pool.append((r, name))
    sets = {r: usage.popular_set(n, dex) for r, n in pool}
    sets = {r: s for r, s in sets.items() if s is not None}
    tags = {r: set_roles(s, dex) for r, s in sets.items()}
    labels = {r: {t.label for t in tg} for r, tg in tags.items()}
    types = {r: set(s.battle_form(dex).types) for r, s in sets.items()}
    jobs = {r: job(tg) for r, tg in tags.items()}
    sheet = usage.team_sheet_usage(dex)
    pop = {r: sheet.get(usage.sheet_name(sets[r].battle_form(dex).name, dex) or "", 0.0) for r in sets}
    cand = [r for r in sets if r in tm.index]

    ranks = defaultdict(list)
    same_job, players, plan_kept, plan_needed = [], [], [], []
    for s in rows:
        x, y = s["out"], s["in"]
        rest = list(s["old"]["six"] - {x})
        if x not in sets or y not in sets or y not in tm.index:
            continue
        avail = [c for c in cand if c not in s["old"]["six"]]
        if y not in avail:
            continue
        p = tm.pick_probs(rest)
        logfit = np.array([np.log(p[tm.index[c]] + 1e-9) for c in avail])
        sim = np.array([len(labels[x] & labels[c]) + 0.5 * len(types[x] & types[c]) for c in avail])
        popl = np.array([np.log(pop[c] + 0.05) for c in avail])
        jobok = np.array([jobs[c] == jobs[x] for c in avail])
        sx = subs.get(x, {})
        subl = np.array([np.log1p(sx.get(c, 0)) for c in avail])
        # the "keep the game plan" half of Same role: the team's only setter of a plan it uses stays covered
        old_sets = [sets[r] for r in s["old"]["six"] if r in sets]
        keep_ok = np.ones(len(avail), bool)
        if len(old_sets) == 6:
            live = {PLAN_ROLE[p.key] for p in team_plans(build_members(old_sets, dex), dex)
                    if not p.needed and p.key in PLAN_ROLE}
            must = (plan_roles(tags[x]) & live) - set().union(*[plan_roles(tags[r]) for r in rest if r in tags])
            if must:
                keep_ok = np.array([must <= plan_roles(tags[c]) for c in avail])
        yi = avail.index(y)
        methods = {
            "similarity (Most similar today)": sim + 1e-3 * logfit,   # ties broken by fit, as the app breaks by score
            "teammate fit": logfit,
            "popularity": popl,
            "similarity + fit": sim / max(sim.std(), 1e-9) + logfit / max(logfit.std(), 1e-9),
            "fit, same job first": logfit + 100 * jobok,
            "similarity + fit, same job first": sim / max(sim.std(), 1e-9) + logfit / max(logfit.std(), 1e-9) + 100 * jobok,
            "fit + 0.5 x past swaps": logfit + 0.5 * subl,
            "fit + 1 x past swaps": logfit + 1.0 * subl,
            "fit + 2 x past swaps": logfit + 2.0 * subl,
            "fit, plan kept first": logfit + 100 * keep_ok,
        }
        for name, v in methods.items():
            ranks[name].append(int((v > v[yi]).sum()) + 1)
        same_job.append(bool(jobok[yi]))
        plan_kept.append(bool(keep_ok[yi]))
        plan_needed.append(not keep_ok.all())
        players.append(s["player"])
    n = len(same_job)
    print(f"{n} swaps scored (both Pokemon known to the app); the real replacement had the same job as the one it "
          f"replaced in {np.mean(same_job):.0%} of them (so a same-role filter would hide it {1 - np.mean(same_job):.0%} of the time)")
    pn = np.array(plan_needed); pk = np.array(plan_kept)
    print(f"  the replaced Pokemon was the team's only setter of a plan it uses in {pn.mean():.0%} of swaps; "
          f"there the player kept the plan covered {pk[pn].mean():.0%} of the time")
    pl = sorted(set(players)); pid = {p: i for i, p in enumerate(pl)}
    groups = defaultdict(list)
    for i, p in enumerate(players):
        groups[pid[p]].append(i)
    rng = np.random.default_rng(0)
    boots = [np.concatenate([groups[k] for k in rng.integers(0, len(pl), len(pl))]) for _ in range(BOOT)]
    base = np.array(ranks["similarity (Most similar today)"])
    print(f"  {'method':36s} {'top 1':>6s} {'top 3':>6s} {'top 10':>7s}   MRR   (95%)            vs today")
    for name, rk in ranks.items():
        rk = np.array(rk)
        mrr = (1 / rk).mean()
        bs = [(1 / rk[b]).mean() for b in boots]
        d = [(1 / rk[b]).mean() - (1 / base[b]).mean() for b in boots]
        print(f"  {name:36s} {np.mean(rk == 1):6.1%} {np.mean(rk <= 3):6.1%} {np.mean(rk <= 10):7.1%}  {mrr:.3f} "
              f"({np.percentile(bs, 2.5):.3f}-{np.percentile(bs, 97.5):.3f})  {np.mean(d):+.3f} "
              f"({np.percentile(d, 2.5):+.3f} to {np.percentile(d, 97.5):+.3f})")


if __name__ == "__main__":
    main()
