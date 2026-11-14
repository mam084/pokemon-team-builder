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
popular set, with an item that keeps Item Clause and a non-Mega set if the
rest of the team already has its Mega.

Speed: pair scores are cached by set, and per-meta-team score rows are cached
per member, so ~6 x 80 candidate swaps x ~10 meta teams evaluate in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis import Member, build_members
from src.dex import Dex, to_id
from src.matchup import Archetype, _set_key, best_attack, opponent_members, pair_score
from src.recommend import _root
from src.team import PokemonSet
from src.usage import UsageData

MAX_OVERALL_LOSS = 0.05


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

    def overall(self, members: list[Member]) -> float:
        if not members or not self.fields:
            return 0.0
        all_rows = [self.rows(m) for m in members]
        total = weights = 0.0
        for i, f in enumerate(self.fields):
            if not f.theirs:
                continue
            matrix = np.vstack([r[i] for r in all_rows])
            score = matrix.max(axis=0).mean() - (-matrix).max(axis=1).mean()
            total += score * f.weight
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
                  focus: str | None = None, pool: list[str] | None = None, top_n: int = 8) -> pd.DataFrame:
    members = build_members(team, dex)
    if len(members) < 2:
        return pd.DataFrame()
    base_overall = engine.overall(members)
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
        rest_has_mega = any(p.is_mega(dex) for p in rest)
        seen_roots = set()
        for name in candidates:
            root = _root(dex.get_species(name))
            if root in seen_roots:
                continue
            seen_roots.add(root)
            pset = usage.popular_set(name, dex, taken_items=taken, allow_mega=not rest_has_mega)
            if pset is None:
                continue
            new_member = build_members([pset], dex)
            if not new_member:
                continue
            new_members = rest_members[:i] + new_member + rest_members[i:]
            overall = engine.overall(new_members)
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
