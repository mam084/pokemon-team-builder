"""How well does the builder do for off-meta cores? Held-out week of rated replays (Nov 2026).

Tournaments have too few off-meta teams to judge, so this uses ladder and Bo3 replays from the held-out
week (players rated 1300+). Each player's team is one team; its record is over its games that week.
Winners: 3+ games, 60%+ won; losers: 3+ games, 40% or less. Every model the builder uses (teammate
model, tournament pairings, sheet sets) is fitted on data from before the week.

For each Pokemon with 4+ winning and 4+ losing teams there, build three teams around it and measure how
many of the other five a winning (or losing) team shares with the closest built team. Lean = winners -
losers: does the builder steer toward what wins with that core, not just toward what's common with it?
Baseline: the core's five most common partners on rated teams from the 30 days before the week (what a
usage site's "teammates" list suggests), as one team.

Cores are grouped by ladder usage (Smogon's monthly stats from before the week).

    python labs/offmeta_lab.py
"""
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

import src.builder as B
from src.builder import build_teams
from src.cooccurrence import Cooccurrence
from src.dex import load_dex
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.replays import load_records
from src.sheet_sets import sheet_sets_from
from src.team_check import _teammates_before
from src.usage import load_usage

CUT = "2026-11-12"
MIN_RATING = 1300
MIN_GAMES = 3
MIN_TEAMS = 4
BUCKETS = [(0, 1), (1, 3), (3, 10), (10, 101)]


KEEP = ("format", "uploadtime", "players", "winner", "forfeit", "preview", "brought", "mega", "sheets", "rating")


def _records_split(cut_ts):
    """Replays before / from the cut, slimmed to what these tests use (the full records don't fit twice)."""
    before, after = [], []
    for f in CURRENT.replays:
        for r in load_records(f):
            r = {k: r[k] for k in KEEP if k in r}
            (after if (r.get("uploadtime") or 0) >= cut_ts else before).append(r)
    return before, after


def _teammates(before_recs, teams, dex):
    """src.team_check._teammates_before, from records already in memory."""
    from src.synergy import (L2, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, recent_records, replay_rows,
                             tournament_rows)
    end = datetime.strptime(CUT, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() - 1
    rows = tournament_rows([t for t in teams if t["date"] < CUT], dex, weight=TOURNAMENT_WEIGHT) + \
        replay_rows(recent_records(before_recs, end=end), dex)
    return TeammateModel(build_vocab(rows)).fit(rows, l2=L2)


def main(modes=("popular", "neutral", "hidden"), variants=None):
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    teams = load_tournament_teams(reg, dex)
    cut_ts = datetime.strptime(CUT, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    before_recs, after_recs = _records_split(cut_ts)
    usage.teammates = _teammates(before_recs, teams, dex)
    usage.cooc = Cooccurrence([t["sets"] for t in teams if t["date"] < CUT], dex)
    usage.sheet_sets = sheet_sets_from([t for t in teams if t["date"] < CUT], [r for r in before_recs if r.get("sheets")],
                                       dex, end=CUT, days=30)
    root = lambda n: dex.sheet_id(dex.get_species(n)) if dex.get_species(n) else None  # noqa: E731
    name_of = {}
    for n in usage.team_sheet_usage(dex):
        name_of.setdefault(root(n), n)
    share = {root(n): v for n, v in usage.team_sheet_usage(dex).items()}

    # held-out week: each rated player's team, its record
    rec = defaultdict(lambda: [0, 0])
    for r in after_recs:
        if r.get("forfeit"):
            continue
        for p in ("p1", "p2"):
            if (r["players"][p].get("rating") or 0) < MIN_RATING:
                continue
            roots = frozenset(x for x in (root(s) for s in r["preview"][p]) if x)
            if len(roots) != 6:
                continue
            key = (r["players"][p]["name"].lower(), roots)
            rec[key][0] += r["winner"] == p
            rec[key][1] += 1
    groups = defaultdict(lambda: {"win": [], "lose": []})
    for (_, roots), (w, n) in rec.items():
        if n < MIN_GAMES or 0.4 < w / n < 0.6:
            continue
        for x in roots:
            groups[x]["win" if w / n >= 0.6 else "lose"].append(roots - {x})
    # baseline: each core's most common partners on rated teams in the 30 days before
    partners = defaultdict(Counter)
    seen = set()
    for r in before_recs:
        if (r.get("uploadtime") or 0) < cut_ts - 30 * 86400:
            continue
        for p in ("p1", "p2"):
            if (r["players"][p].get("rating") or 0) < MIN_RATING:
                continue
            roots = frozenset(x for x in (root(s) for s in r["preview"][p]) if x)
            key = (r["players"][p]["name"].lower(), roots)
            if key in seen:
                continue
            seen.add(key)
            for x in roots:
                partners[x].update(roots - {x})
    cores = [c for c, g in groups.items() if len(g["win"]) >= MIN_TEAMS and len(g["lose"]) >= MIN_TEAMS
             and c in name_of and usage.popular_set(name_of[c], dex) is not None]
    print(f"held-out week from {CUT}: {len(rec)} rated teams, {sum(1 for v in rec.values() if v[1] >= MIN_GAMES)} with "
          f"{MIN_GAMES}+ games; {len(cores)} cores with {MIN_TEAMS}+ winning and losing teams")
    for lo, hi in BUCKETS:
        print(f"  usage {lo}-{hi}%: {sum(lo <= share.get(c, 0) < hi for c in cores)} cores")

    def overlaps(sets, core):
        w = [max(len(s & t) for s in sets) for t in groups[core]["win"]]
        l_ = [max(len(s & t) for s in sets) for t in groups[core]["lose"]]
        return np.mean(w), np.mean(l_)

    results = defaultdict(list)   # (variant, mode) -> [(core, win, lose, team1 win, team1 lose)]
    base = []
    for c in cores:
        top = {x for x, _ in partners[c].most_common(5)}
        if len(top) == 5:
            w, l_ = overlaps([top], c)
            base.append((c, w, l_))
    t0 = time.time()
    variants = variants or [("shipped", {})]
    for vname, settings in variants:
        saved = {k: getattr(B, k) for k in settings}
        for k, v in settings.items():
            setattr(B, k, v)
        for mode in modes:
            for c in cores:
                built = build_teams(name_of[c], dex, usage, mode=mode)
                if not built:
                    continue
                sets = [{root(p.species) for p in b.sets} - {c} for b in built]
                w, l_ = overlaps(sets, c)
                w1, l1 = overlaps(sets[:1], c)
                results[(vname, mode)].append((c, w, l_, w1, l1))
            print(f"  built {vname}/{mode} [{time.time() - t0:.0f}s]", flush=True)
        for k, v in saved.items():
            setattr(B, k, v)

    def row(label, items, k_w=1, k_l=2):
        for lo, hi in BUCKETS + [(0, 101)]:
            sub = [x for x in items if lo <= share.get(x[0], 0) < hi]
            if not sub:
                continue
            w = np.array([x[k_w] for x in sub])
            l_ = np.array([x[k_l] for x in sub])
            gap = w - l_
            rng = np.random.default_rng(0)
            b = [gap[rng.integers(0, len(gap), len(gap))].mean() for _ in range(2000)]
            tag = "all" if (lo, hi) == (0, 101) else f"{lo}-{hi}%"
            print(f"{label:34s} {tag:7s} n={len(sub):3d}  winners share {w.mean():.2f}/5  losers {l_.mean():.2f}  "
                  f"lean {gap.mean():+.3f} (95% {np.percentile(b, 2.5):+.3f} to {np.percentile(b, 97.5):+.3f})")

    print()
    row("top-5 partners (baseline, 1 team)", base)
    for (vname, mode), items in results.items():
        row(f"{vname} {mode}: best of 3", items)
        row(f"{vname} {mode}: team 1 only", items, 3, 4)
    return results, base, share


def per_game(modes=("popular", "neutral", "hidden"), min_games: int = 30, min_rating: int = 1100,
             variants=None):
    """Game-level version: in every held-out game (both players rated min_rating+, no forfeits), does a team
    that shares more Pokemon with the builder's teams for its core win more than the players' ratings predict?
    Slope of (won - rating-predicted) on shared Pokemon (0-5), in points of win chance per shared Pokemon,
    90% interval from a bootstrap over players. Baseline: shares with the core's top-5 partners."""
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, recent=False)
    teams = load_tournament_teams(reg, dex)
    cut_ts = datetime.strptime(CUT, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    before_recs, after_recs = _records_split(cut_ts)
    usage.teammates = _teammates(before_recs, teams, dex)
    usage.cooc = Cooccurrence([t["sets"] for t in teams if t["date"] < CUT], dex)
    usage.sheet_sets = sheet_sets_from([t for t in teams if t["date"] < CUT], [r for r in before_recs if r.get("sheets")],
                                       dex, end=CUT, days=30)
    from src.core_report import replay_index
    usage.edges = B.edges_from(replay_index(before_recs, dex))   # pre-week only
    root = lambda n: dex.sheet_id(dex.get_species(n)) if dex.get_species(n) else None  # noqa: E731
    name_of = {}
    for n in usage.team_sheet_usage(dex):
        name_of.setdefault(root(n), n)
    share = {root(n): v for n, v in usage.team_sheet_usage(dex).items()}
    games = []   # (player, roots, residual)
    for r in after_recs:
        if r.get("forfeit"):
            continue
        ra, rb = (r["players"][p].get("rating") or 0 for p in ("p1", "p2"))
        if min(ra, rb) < min_rating:
            continue
        for p, own, opp in (("p1", ra, rb), ("p2", rb, ra)):
            roots = frozenset(x for x in (root(s) for s in r["preview"][p]) if x)
            if len(roots) != 6:
                continue
            exp = 1 / (1 + 10 ** ((opp - own) / 400))
            games.append((r["players"][p]["name"].lower(), roots, (r["winner"] == p) - exp))
    count = Counter(x for _, roots, _ in games for x in roots)
    cores = [c for c, n in count.items() if n >= min_games and c in name_of and usage.popular_set(name_of[c], dex)]
    partners = defaultdict(Counter)
    seen = set()
    for r in before_recs:
        if (r.get("uploadtime") or 0) < cut_ts - 30 * 86400:
            continue
        for p in ("p1", "p2"):
            if (r["players"][p].get("rating") or 0) < MIN_RATING:
                continue
            roots = frozenset(x for x in (root(s) for s in r["preview"][p]) if x)
            key = (r["players"][p]["name"].lower(), roots)
            if key not in seen:
                seen.add(key)
                for x in roots:
                    partners[x].update(roots - {x})
    print(f"{len(games)} team-games in the held-out week (both players {min_rating}+); {len(cores)} cores with "
          f"{min_games}+ games")
    for lo, hi in BUCKETS:
        print(f"  usage {lo}-{hi}%: {sum(lo <= share.get(c, 0) < hi for c in cores)} cores")
    built = {"top-5 partners": {c: [{x for x, _ in partners[c].most_common(5)}] for c in cores}}
    t0 = time.time()
    variants = variants or [(m, m, {}) for m in modes]
    for label, mode, settings in variants:
        saved = {k: getattr(B, k) for k in settings}
        for k, v in settings.items():
            setattr(B, k, v)
        built[label] = {}
        for c in cores:
            bt = build_teams(name_of[c], dex, usage, mode=mode)
            built[label][c] = [{root(p.species) for p in b.sets} - {c} for b in bt]
        for k, v in saved.items():
            setattr(B, k, v)
        print(f"  built {label} [{time.time() - t0:.0f}s]", flush=True)
    core_set = set(cores)
    for label, table in built.items():
        for lo, hi in BUCKETS + [(0, 101)]:
            rows = []
            for who, roots, res in games:
                for c in roots & core_set:
                    if lo <= share.get(c, 0) < hi and table.get(c):
                        rows.append((who, max(len((roots - {c}) & s) for s in table[c]), res))
            if len(rows) < 50:
                continue
            x = np.array([o for _, o, _ in rows], float)
            y = np.array([r_ for _, _, r_ in rows])
            whos = np.array([w for w, _, _ in rows])
            slope = np.polyfit(x, y, 1)[0] if x.std() > 0 else 0.0
            uniq = np.unique(whos)
            idx = {w: np.where(whos == w)[0] for w in uniq}
            rng = np.random.default_rng(0)
            bs = []
            for _ in range(500):
                pick = np.concatenate([idx[w] for w in rng.choice(uniq, len(uniq))])
                if x[pick].std() > 0:
                    bs.append(np.polyfit(x[pick], y[pick], 1)[0])
            tag = "all" if (lo, hi) == (0, 101) else f"{lo}-{hi}%"
            print(f"{label:22s} {tag:7s} games {len(rows):6d}  avg shared {x.mean():.2f}/5  "
                  f"slope {100 * slope:+.2f} pts per shared Pokemon (90% {100 * np.percentile(bs, 5):+.2f} to "
                  f"{100 * np.percentile(bs, 95):+.2f})")


if __name__ == "__main__":
    if "--gems" in sys.argv:
        per_game(variants=[("neutral (3 neutral)", "neutral", {"NEUTRAL_GEMS": 0}),
                           ("neutral (2 + 1 gems)", "neutral", {"NEUTRAL_GEMS": 1}),
                           ("hidden", "hidden", {})])
    elif "--edge" in sys.argv:
        per_game(variants=[(f"{m} edge {w}", m, {"EDGE_WEIGHT": w}) for m in ("popular", "neutral", "hidden")
                           for w in (0.0, 2.0, 5.0)])
    elif "--per-game" in sys.argv:
        per_game()
    else:
        main()
