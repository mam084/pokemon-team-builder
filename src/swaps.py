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

from collections import OrderedDict

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis import Member, build_members, mega_variants
from src.dex import Dex, to_id
from src.plan import team_plans
from src.matchup import (Archetype, Support, _set_key, best_attack, opponent_members, pair_parts, pair_score,
                         scores_from_parts, side_support)
from src.recommend import HIDDEN_MAX, _root
from src.roles import job, plan_roles, set_roles
from src.team import MAX_MEGAS, PokemonSet
from src.usage import UsageData

MAX_OVERALL_LOSS = 0.05
MAX_WIN_LOSS = 0.5  # win-chance points a threat fix may cost overall
MAX_SCORE_LOSS = 0.15  # the same for the team rating (z units: about half a point of win chance)


PLAN_ROLE = {"rain": "Rain setter", "sun": "Sun setter", "sand": "Sand setter", "snow": "Snow setter",
             "trickroom": "Trick Room setter", "psychicterrain": "Terrain setter",
             "grassyterrain": "Terrain setter", "electricterrain": "Terrain setter"}


@dataclass
class _Field:
    theirs: list[Member]
    trick_room: bool
    weather: str | None
    weight: float
    support: Support


ROWS_MAX = 3000   # ~40 MB: every candidate's rows plus recent visitors' own sets


class SwapEngine:
    def __init__(self, archetypes: list[Archetype], usage: UsageData, dex: Dex, doubles: bool = True):
        self.usage, self.dex, self.doubles = usage, dex, doubles
        self.fields = [
            _Field(theirs, a.trick_room, a.weather, a.popularity, side_support(theirs))
            for a in archetypes
            for theirs in [opponent_members(a.members, usage, dex)]
        ]
        self._rows: OrderedDict[tuple, list[dict]] = OrderedDict()

    def rows(self, m: Member) -> list[dict]:
        """Raw pair parts of one member against each meta team's members (cached by set, least recently
        used dropped past ROWS_MAX, ~13 KB each); support is applied per team in overall(), since it
        depends on the teammates."""
        key = _set_key(m)
        hit = self._rows.get(key)
        if hit is not None:
            try:
                self._rows.move_to_end(key)
            except KeyError:
                pass
            return hit
        rows = [pair_parts([m], f.theirs, self.doubles, f.weather) for f in self.fields]
        self._rows[key] = rows
        while len(self._rows) > ROWS_MAX:
            try:
                self._rows.popitem(last=False)
            except KeyError:
                break
        return rows

    def attach_model(self, model: dict | None) -> None:
        """Use the learned match model (src/match_model.py) for win chances vs the meta teams."""
        from src.match_model import team_side
        self.model = model
        self.sides = [] if model is None else [
            team_side(f.theirs, [m.pset for m in f.theirs if m.pset is not None], self.dex, self.usage, self)
            for f in self.fields]

    def attach_rating(self, ref: dict | None, teammates) -> None:
        """Judge swaps by the team rating (src/team_rating.py): teammate fit plus the win chance vs
        the meta. On the held-out week it tracked real results better than win chance alone
        (scripts/app_vs_results.py)."""
        self.rating_ref, self.teammates = ref, teammates

    def rating(self, team: list[PokemonSet], win: float | None) -> tuple[float, float] | None:
        """(combined rating, percentile among tournament teams), or None without the models."""
        if getattr(self, "rating_ref", None) is None or getattr(self, "teammates", None) is None:
            return None
        from src.team_rating import rate
        return rate(team, self.dex, self.teammates, win, self.rating_ref)

    def win_chance(self, team: list[PokemonSet], meta: float | None = None) -> float | None:
        """Usage-weighted learned win chance against the meta teams (best Mega per opponent)."""
        if getattr(self, "model", None) is None or not team:
            return None
        from src.match_model import predict_match, team_side
        versions = [members for _, members in mega_variants(team, self.dex)]
        meta = self.overall(team) if meta is None else meta
        mine = [(team_side(members, team, self.dex, self.usage, self, meta=meta), [self.rows(m) for m in members])
                for members in versions]
        total = weights = 0.0
        for i, (f, theirs) in enumerate(zip(self.fields, self.sides)):
            if not f.theirs:
                continue
            best = max(predict_match(self.model, side,
                                     theirs, {k: np.vstack([r[i][k] for r in rows]) for k in rows[0][i]})
                       for side, rows in mine)
            total += best * f.weight
            weights += f.weight
        from src.match_model import cap_chance  # past the best real team counts as no better (trust region)
        return cap_chance(self.model, total / weights) if weights else None

    def overall(self, team: list[PokemonSet] | list[Member]) -> float:
        """Usage-weighted score vs the meta teams. Given PokemonSets, a team with two Mega
        Stones is scored with whichever Mega Evolves best against each meta team."""
        if not team or not self.fields:
            return 0.0
        if isinstance(team[0], Member):
            versions = [team]
        else:
            versions = [members for _, members in mega_variants(team, self.dex)]
        version_rows = [([self.rows(m) for m in members], side_support(members)) for members in versions]
        total = weights = 0.0
        for i, f in enumerate(self.fields):
            if not f.theirs:
                continue
            best = None
            for all_rows, ours in version_rows:
                parts = {k: np.vstack([r[i][k] for r in all_rows]) for k in all_rows[0][i]}
                matrix = scores_from_parts(parts, ours, f.support, f.trick_room)
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
                  same_role: bool = False, per_member: int | None = None) -> pd.DataFrame:
    """
    With per_member=k, returns the k best alternatives for *every* member instead of
    only swaps that improve the team: what else could do this Pokemon's job, and
    how much better or worse the team would be with it.
    """
    members = build_members(team, dex)
    # roles the team is actually built around (a Rain Dance nobody uses doesn't count)
    live_plans = {PLAN_ROLE[p.key] for p in team_plans(members, dex) if not p.needed and p.key in PLAN_ROLE}
    if len(members) < 2:
        return pd.DataFrame()
    base_overall = engine.overall(team)
    base_win = engine.win_chance(team, meta=base_overall)  # None without a learned model
    base_rating = engine.rating(team, base_win)            # None without the team rating models
    threat = None
    if focus:
        opp = opponent_members([focus], usage, dex)
        threat = opp[0] if opp else None
    base_focus = _answer(members, threat, engine.doubles)[0] if threat else 0.0

    nums_on_team = {m.form.num for m in members}  # Species Clause: by Pokedex number
    if pool is None:
        pool = [name for name, _ in usage.ranked(80)]
    candidates = [n for n in pool if dex.get_species(n) and dex.get_species(n).num not in nums_on_team]

    tm = usage.teammates  # learned teammate model: how usual each newcomer is next to the rest
    rows = []
    for i, out_set in enumerate(team):
        rest = team[:i] + team[i + 1:]
        rest_members = members[:i] + members[i + 1:]
        fit_probs = tm.pick_probs([dex.sheet_id(m.form) for m in rest_members]) if tm is not None else None
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
            pset = usage.popular_set(name, dex, taken_items=taken, allow_mega=rest_megas < MAX_MEGAS, team=rest)
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
            new_team = rest[:i] + [pset] + rest[i:]
            overall = engine.overall(new_team)
            win = engine.win_chance(new_team, meta=overall) if base_win is not None else None
            rating = engine.rating(new_team, win) if base_rating is not None else None
            # judged on the team rating when there is one, else the learned win chance, else the calc score
            if rating is not None:
                change, max_loss = rating[0] - base_rating[0], MAX_SCORE_LOSS
            elif win is not None:
                change, max_loss = (win - base_win) * 100, MAX_WIN_LOSS
            else:
                change, max_loss = overall - base_overall, MAX_OVERALL_LOSS
            if change < -max_loss and not per_member:
                continue
            focus_gain, key_calc = 0.0, ""
            if threat is not None:
                new_focus, _ = _answer(new_members, threat, engine.doubles)
                focus_gain = new_focus - base_focus
                if focus_gain <= 0 and not per_member:
                    continue
                pct, move = best_attack(new_member[0], threat, engine.doubles)
                taken_pct, _ = best_attack(threat, new_member[0], engine.doubles)
                key_calc = f"{move} {pct:.0f}% to {threat.label}; takes {taken_pct:.0f}%"
            elif change <= 0 and not per_member:
                continue
            fit = None
            if fit_probs is not None:
                k = tm.index.get(dex.sheet_id(pset.battle_form(dex)))
                fit = float(fit_probs[k]) if k is not None else 0.0
            out_labels, in_labels = {t.label for t in out_tags}, {t.label for t in in_tags}
            out_types = set(out_set.battle_form(dex).types)
            similarity = len(out_labels & in_labels) + 0.5 * len(out_types & set(pset.battle_form(dex).types))
            rows.append({
                "similarity": similarity,
                "fit": fit,
                "swap out": out_set.nickname or out_set.species,
                "swap in": pset.species,
                "out job": out_job,
                "in job": in_job,
                "shared roles": ", ".join(t.label for t in in_tags
                                          if t.label in {o.label for o in out_tags})[:80],
                "slot": i,
                "overall": round(overall, 2),
                "overall change": round(overall - base_overall, 2),
                "win chance": round(win, 4) if win is not None else None,
                "win change": round((win - base_win) * 100, 2) if win is not None else None,
                "rating change": round(change, 4) if rating is not None else None,
                "score": round(rating[1]) if rating is not None else None,
                "score change": round(rating[1] - base_rating[1]) if rating is not None else None,
                "vs threat": round(focus_gain, 1) if threat is not None else None,
                "key calc": key_calc,
                "set": f"{pset.item or 'no item'} · {', '.join(pset.moves)}",
                "_set": pset,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    main = ("rating change" if base_rating is not None else
            "win change" if base_win is not None else "overall change")
    sort = ["vs threat", main] if threat is not None else [main]
    df = df.sort_values(sort, ascending=False)
    if per_member:
        # per member: the best upgrade, then the most similar Pokemon (shared roles and types)
        # A Pokemon that would improve any slot (one the model rates highly on its own) is
        # suggested once, for the slot where it gains most - so every member gets its own idea.
        groups = {slot: g for slot, g in df.groupby("slot", sort=True)}
        order = sorted(groups, key=lambda slot: -groups[slot].iloc[0][sort[0]])
        used, best_rows = set(), {}
        for slot in order:
            g = groups[slot]
            fresh = g[~g["swap in"].isin(used)]
            row = (fresh if not fresh.empty else g).iloc[[0]]
            used.add(row["swap in"].iloc[0])
            best_rows[slot] = row.assign(pick="Best upgrade")
        picks = []
        for slot in sorted(groups):
            best = best_rows[slot]
            rest = groups[slot][groups[slot]["swap in"] != best["swap in"].iloc[0]]
            rest = rest.sort_values(["similarity"] + sort, ascending=False)  # the same job: shared roles, types
            picks += [best, rest.head(per_member - 1).assign(pick="Most similar")]
        df = pd.concat(picks).reset_index(drop=True)
    else:
        # one suggestion per incoming Pokemon (its best slot), then the best few
        df = df.drop_duplicates("swap in").head(top_n).reset_index(drop=True)
    df.attrs["base_overall"] = base_overall
    df.attrs["base_win"] = base_win
    df.attrs["base_score"] = base_rating[1] if base_rating is not None else None
    df.attrs["base_focus"] = base_focus
    return df




def mode_pool(usage: UsageData, mode: str, dex: Dex | None = None) -> list[str]:
    """Candidate replacements for a recommendation mode. Swaps rank by matchup score alone,
    so Hidden gems can't just mark popular picks down - it leaves common Pokémon out."""
    if mode == "popular":
        return [n for n, _ in usage.ranked(80)]
    ranked = [n for n, _ in usage.ranked()]
    if mode == "hidden" and dex is not None:
        return [n for n in ranked if not usage.is_common(n, dex, HIDDEN_MAX)]
    return ranked


__all__ = ["HIDDEN_MAX", "SwapEngine", "suggest_swaps", "mode_pool", "to_id"]
