"""Do builder picks carry what they were credited for? Tested on held-out tournament sets (Nov 2026).

The recommender credits a pick for Tailwind, Pivoting, Wide Guard... when the move is on 25%+ of its
ladder sets, but the set the builder added was the top four moves, so 19% of those claims weren't on
the added set (Corviknight "for its Tailwind" with no Tailwind). src.builder.carry_credited swaps the
credited move in for the least-used move no claim needs.

Test: tournament team sheets publish moves. For every member of every team in the newest week, give the
other five to the recommender (ladder usage only, no tournament data), take its credits for the hidden
Pokemon, and compare the plain popular set and the carried set with the moves that player really ran.

    python scripts/set_fit_lab.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from src.analysis import build_members
from src.builder import carry_credited
from src.dex import load_dex, to_id
from src.evaluate import load_tournament_teams
from src.formats import CURRENT
from src.recommend import recommend
from src.team import MAX_MEGAS
from src.usage import load_usage

CUT = "2026-11-12"   # the held-out week used across the README


def main():
    reg = CURRENT.regulation
    dex, usage = load_dex(reg), load_usage(CURRENT.id, tournament_pairs=False, recent=False)
    teams = [t for t in load_tournament_teams(reg, dex, usage=usage) if t["date"] >= CUT]
    print(f"{len(teams)} held-out teams from {CUT}")
    rows = []   # (team index, plain matched, carried matched, carried-keep-protect matched, added real, dropped real)
    for ti, t in enumerate(teams):
        for i, hidden in enumerate(t["sets"]):
            rest = t["sets"][:i] + t["sets"][i + 1:]
            recs = recommend(build_members(rest, dex), dex, usage, top_n=None, mode="neutral")
            hid = dex.sheet_id(hidden.battle_form(dex) or dex.get_species(hidden.species))
            match = [r for _, r in recs.iterrows() if dex.sheet_id(dex.get_species(r["pokemon"])) == hid]
            if not match or not match[0]["credited"]:
                continue
            megas = sum(p.is_mega(dex) for p in rest)
            plain = usage.popular_set(hidden.species, dex, taken_items={p.item for p in rest if p.item},
                                      allow_mega=megas < MAX_MEGAS, team=rest)
            if plain is None:
                continue
            real = {to_id(m) for m in hidden.moves}
            out = [ti]
            for keep in (False, True):
                carried, _ = carry_credited(plain, match[0]["credited"], usage, dex, keep_protect=keep)
                out.append(carried)
            p_ids = [to_id(m) for m in plain.moves]
            c_ids = [to_id(m) for m in out[2].moves]   # shipped variant: keeps Protect
            added = [m for m in c_ids if m not in p_ids]
            dropped = [m for m in p_ids if m not in c_ids]
            rows.append({
                "team": ti, "plain": len(real & set(p_ids)),
                "carry": len(real & {to_id(m) for m in out[1].moves}),
                "carry_keep": len(real & set(c_ids)),
                "changed": bool(added),
                "added_real": sum(m in real for m in added), "dropped_real": sum(m in real for m in dropped),
                "n_changed": len(added),
            })
    changed = [r for r in rows if r["changed"]]
    print(f"{len(rows)} hidden members with credits; the carried set differs for {len(changed)}")
    for key, label in (("plain", "popular set (top 4 moves)"), ("carry", "carried, may drop Protect"),
                       ("carry_keep", "carried, keeps Protect (shipped)")):
        print(f"  {label:36s} moves matching the real set: {np.mean([r[key] for r in changed]):.3f} / 4")
    n = sum(r["n_changed"] for r in changed)
    print(f"  swapped-in moves the player really ran: {sum(r['added_real'] for r in changed) / n:.1%}; "
          f"swapped-out moves they ran: {sum(r['dropped_real'] for r in changed) / n:.1%} ({n} swaps)")

    # paired bootstrap over teams
    by_team = {}
    for r in changed:
        by_team.setdefault(r["team"], []).append(r)
    keys = list(by_team)
    rng = random.Random(0)
    for key in ("carry", "carry_keep"):
        gains = []
        for _ in range(2000):
            sample = [r for k in (rng.choice(keys) for _ in keys) for r in by_team[k]]
            gains.append(np.mean([r[key] - r["plain"] for r in sample]))
        point = np.mean([r[key] - r["plain"] for r in changed])
        lo, hi = np.percentile(gains, [2.5, 97.5])
        print(f"  gain {key:10s}: {point:+.3f} moves per changed set (95% {lo:+.3f} to {hi:+.3f})")


if __name__ == "__main__":
    main()
