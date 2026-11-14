"""
swaps.py

"Your team struggles with Incineroar - swap Tsareena for Milotic."

For every member of the team and every candidate replacement, the swap is
scored with the same damage-based engine as the Matchups tab:

    overall   usage-weighted team score against the rebuilt meta teams
    focus     (when a threat is chosen) your best pairing against that threat:
              how many hits you need to KO it vs. it needs to KO you, plus Speed

Swaps are ranked by the focus improvement first (if any), then by the overall
change, and a swap is only offered if it doesn't make the overall matchup
meaningfully worse (more than MAX_OVERALL_LOSS). Each replacement uses its
popular set, with an item that keeps Item Clause; a team may hold two Mega
Stones (scored with whichever Mega Evolves best in each matchup).

With same_role, a replacement must do the same broad job (Support / Attacker /
Hybrid, from roles.job) and keep any team-defining role - weather, terrain or
Trick Room - that only the outgoing member provides.

Speed: pair scores are cached by set, and per-meta-team score rows are cached
per member, so ~6 x 80 candidate swaps x ~10 meta teams evaluate in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis import Member, build_members, mega_variants
from src.dex import Dex, to_id
from src.plan import team_plans
from src.matchup import Archetype, _set_key, best_attack, opponent_members, pair_score
from src.recommend import _root
from src.roles import job, plan_roles, set_roles
from src.team import MAX_MEGAS, PokemonSet
from src.usage import UsageData

MAX_OVERALL_LOSS = 0.05


PLAN_ROLE = {"rain": "Rain setter", "sun": "Sun setter", "sand": "Sand setter", "snow": "Snow setter",
             "trickroom": "Trick Room setter", "psychicterrain": "Terrain setter",
             "grassyterrain": "Terrain setter", "electricterrain": "Terrain setter"}


@dataclass
class _Field:
    theirs: list[Member]
    trick_room: bool
    weather: str | None
    weight: float


class SwapEngine:
    def __init__(self, archetypes: list[Archetype], usage: UsageData, dex: Dex, doubles: bool = True):
        self.usage, self.dex, self.doubles = usage, dex, doubles
        self.fields = [
            _Field(opponent_members(a.members, usage, dex), a.trick_room, a.weather, a.popularity)
            for a in archetypes
        ]
        self._rows: dict[tuple, list[np.ndarray]] = {}

    def rows(self, m: Member) -> list[np.ndarray]:
        """Pair scores of one member against each meta team's members (cached by set)."""
        key = _set_key(m)
        if key not in self._rows:
            self._rows[key] = [
                np.array([pair_score(m, b, f.trick_room, self.doubles, f.weather) for b in f.theirs])
                for f in self.fields
            ]
        return self._rows[key]

    def overall(self, team: list[PokemonSet] | list[Member]) -> float:
        """Usage-weighted score vs the meta teams. Given PokemonSets, a team with two Mega
        Stones is scored with whichever Mega Evolves best against each meta team."""
        if not team or not self.fields:
            return 0.0
        if isinstance(team[0], Member):
            versions = [team]
        else:
            versions = [members for _, members in mega_variants(team, self.dex)]
        version_rows = [[self.rows(m) for m in members] for members in versions]
        total = weights = 0.0
        for i, f in enumerate(self.fields):
            if not f.theirs:
                continue
            best = None
            for all_rows in version_rows:
                matrix = np.vstack([r[i] for r in all_rows])
                score = matrix.max(axis=0).mean() - (-matrix).max(axis=1).mean()
                best = score if best is None else max(best, score)
            total += best * f.weight
            weights += f.weight
        return total / weights if weights else 0.0


def _answer(members: list[Member], threat: Member, doubles: bool) -> tuple[float, str]:
    best, label = -9.0, ""
    for m in members:
        s = pair_score(m, threat, doubles=doubles)
        if s > best:
            best, label = s, m.label
    return best, label


def suggest_swaps(team: list[PokemonSet], dex: Dex, usage: UsageData, engine: SwapEngine,
                  focus: str | None = None, pool: list[str] | None = None, top_n: int = 8,
                  same_role: bool = False) -> pd.DataFrame:
    members = build_members(team, dex)
    # roles the team is actually built around (a Rain Dance nobody uses doesn't count)
    live_plans = {PLAN_ROLE[p.key] for p in team_plans(members, dex) if not p.needed and p.key in PLAN_ROLE}
    if len(members) < 2:
        return pd.DataFrame()
    base_overall = engine.overall(team)
    threat = None
    if focus:
        opp = opponent_members([focus], usage, dex)
        threat = opp[0] if opp else None
    base_focus = _answer(members, threat, engine.doubles)[0] if threat else 0.0

    roots_on_team = {_root(m.form) for m in members}
    if pool is None:
        pool = [name for name, _ in usage.ranked(80)]
    candidates = [n for n in pool if dex.get_species(n) and _root(dex.get_species(n)) not in roots_on_team]

    rows = []
    for i, out_set in enumerate(team):
        rest = team[:i] + team[i + 1:]
        rest_members = members[:i] + members[i + 1:]
        taken = {p.item for p in rest if p.item}
        rest_megas = sum(p.is_mega(dex) for p in rest)
        out_tags = set_roles(out_set, dex, engine.doubles)
        out_job = job(out_tags)
        # a plan role only this member provides (the team's only snow setter, say) must be kept
        must_keep = (plan_roles(out_tags) & live_plans) - set().union(*[plan_roles(set_roles(p, dex, engine.doubles))
                                                          for p in rest])
        seen_roots = set()
        for name in candidates:
            root = _root(dex.get_species(name))
            if root in seen_roots:
                continue
            seen_roots.add(root)
            pset = usage.popular_set(name, dex, taken_items=taken, allow_mega=rest_megas < MAX_MEGAS)
            if pset is None:
                continue
            in_tags = set_roles(pset, dex, engine.doubles)
            in_job = job(in_tags)
            if same_role and (in_job != out_job or not must_keep <= plan_roles(in_tags)):
                continue
            new_member = build_members([pset], dex)
            if not new_member:
                continue
            new_members = rest_members[:i] + new_member + rest_members[i:]
            overall = engine.overall(rest[:i] + [pset] + rest[i:])
            if overall < base_overall - MAX_OVERALL_LOSS:
                continue
            focus_gain, key_calc = 0.0, ""
            if threat is not None:
                new_focus, _ = _answer(new_members, threat, engine.doubles)
                focus_gain = new_focus - base_focus
                if focus_gain <= 0:
                    continue
                pct, move = best_attack(new_member[0], threat, engine.doubles)
                taken_pct, _ = best_attack(threat, new_member[0], engine.doubles)
                key_calc = f"{move} {pct:.0f}% to {threat.label}; takes {taken_pct:.0f}%"
            elif overall <= base_overall:
                continue
            rows.append({
                "swap out": out_set.nickname or out_set.species,
                "swap in": pset.species,
                "out job": out_job,
                "in job": in_job,
                "shared roles": ", ".join(t.label for t in in_tags
                                          if t.label in {o.label for o in out_tags})[:80],
                "slot": i,
                "overall": round(overall, 2),
                "overall change": round(overall - base_overall, 2),
                "vs threat": round(focus_gain, 1) if threat is not None else None,
                "key calc": key_calc,
                "set": f"{pset.item or 'no item'} · {', '.join(pset.moves)}",
                "_set": pset,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    sort = ["vs threat", "overall change"] if threat is not None else ["overall change"]
    df = df.sort_values(sort, ascending=False)
    # one suggestion per incoming Pokemon (its best slot), then the best few
    df = df.drop_duplicates("swap in").head(top_n).reset_index(drop=True)
    df.attrs["base_overall"] = base_overall
    df.attrs["base_focus"] = base_focus
    return df


def mode_pool(usage: UsageData, mode: str) -> list[str]:
    """Candidate replacements for a recommendation mode."""
    if mode == "popular":
        return [n for n, _ in usage.ranked(80)]
    return [n for n, _ in usage.ranked()]


__all__ = ["SwapEngine", "suggest_swaps", "mode_pool", "to_id"]
