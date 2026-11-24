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

Speed: pair scores are cached by set, per-meta-team score rows are cached per
member, and each candidate team is scored against all meta teams at once (one
stack of numpy arrays, bit-identical to scoring them one at a time), so ~6 x 80
candidate swaps x ~10 meta teams evaluate in about a second.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from itertools import combinations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis import Member, build_members, mega_variants
from src.dex import Dex, to_id
from src.plan import team_plans
from src.matchup import (SPEED_BONUS, SPEED_SUPPORT, SUPPORT, Archetype, Support, _set_key, best_attack,
                         opponent_members, pair_parts, pair_score, side_support)
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


ROWS_MAX = 3000   # ~45 MB: every candidate's rows plus recent visitors' own sets


class SwapEngine:
    def __init__(self, archetypes: list[Archetype], usage: UsageData, dex: Dex, doubles: bool = True):
        self.usage, self.dex, self.doubles = usage, dex, doubles
        self.fields = [
            _Field(theirs, a.trick_room, a.weather, a.popularity, side_support(theirs))
            for a in archetypes
            for theirs in [opponent_members(a.members, usage, dex)]
        ]
        # Meta teams of the same size are scored together, as one stack of numpy arrays (see _Group)
        sizes: dict[int, list[int]] = {}
        for i, f in enumerate(self.fields):
            if f.theirs:
                sizes.setdefault(len(f.theirs), []).append(i)
        self.groups = [_Group(idx, [self.fields[i] for i in idx]) for idx in sizes.values()]
        self._rows: OrderedDict[tuple, tuple[list[dict], list[dict]]] = OrderedDict()

    def _entry(self, m: Member) -> tuple[list[dict], list[dict]]:
        key = _set_key(m)
        hit = self._rows.get(key)
        if hit is not None:
            try:
                self._rows.move_to_end(key)
            except KeyError:
                pass
            return hit
        rows = [pair_parts([m], f.theirs, self.doubles, f.weather) for f in self.fields]
        # the same numbers stacked per group of meta teams: {part: (meta teams, 1, their size)}
        blocks = [{k: np.stack([rows[i][k] for i in g.idx]) for k in rows[g.idx[0]]} for g in self.groups]
        hit = (rows, blocks)
        self._rows[key] = hit
        while len(self._rows) > ROWS_MAX:
            try:
                self._rows.popitem(last=False)
            except KeyError:
                break
        return hit

    def rows(self, m: Member) -> list[dict]:
        """Raw pair parts of one member against each meta team's members (cached by set, least recently
        used dropped past ROWS_MAX, ~15 KB each); support is applied per team in overall(), since it
        depends on the teammates."""
        return self._entry(m)[0]

    def _stacks(self, members: list[Member]) -> list[dict]:
        """A team's pair parts per group of meta teams: {part: (meta teams, len(members), their size)}."""
        blocks = [self._entry(m)[1] for m in members]
        return [{k: np.concatenate([b[gi][k] for b in blocks], axis=1) for k in blocks[0][gi]}
                for gi in range(len(self.groups))]

    def versions(self, team: list[PokemonSet] | list[Member]) -> list[list[Member]]:
        """One member list per choice of Mega Evolution (see analysis.mega_variants)."""
        if team and isinstance(team[0], Member):
            return [team]
        return [members for _, members in mega_variants(team, self.dex)]

    def attach_model(self, model: dict | None) -> None:
        """Use the learned match model (src/match_model.py) for win chances vs the meta teams."""
        from src.match_model import team_side
        self.model = model
        self.sides = [] if model is None else [
            team_side(f.theirs, [m.pset for m in f.theirs if m.pset is not None], self.dex, self.usage, self)
            for f in self.fields]
        self._theirs_x = None if model is None else [
            np.array([_side_vector(model, self.sides[i]) for i in g.idx]) for g in self.groups]

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

    def rating_parts(self, team: list[PokemonSet], win: float | None) -> tuple[float, float, float] | None:
        """(combined rating, percentile, teammate fit): the rating with its fit half, so a swap can say
        which of the two signals backs it."""
        if getattr(self, "rating_ref", None) is None or getattr(self, "teammates", None) is None or win is None:
            return None
        from src.team_rating import combined, percentile, teammate_fit
        fit = teammate_fit(team, self.dex, self.teammates)
        if fit is None:
            return None
        score = combined(fit, win, self.rating_ref)
        return score, percentile(score, self.rating_ref), fit

    def win_chance(self, team: list[PokemonSet], meta: float | None = None,
                   versions: list[list[Member]] | None = None) -> float | None:
        """Usage-weighted learned win chance against the meta teams (best Mega per opponent).

        Same numbers as match_model.predict_match per meta team, computed for all meta teams at once."""
        if getattr(self, "model", None) is None or not team:
            return None
        from src.match_model import cap_chance, team_side
        versions = self.versions(team) if versions is None else versions
        meta = self.overall(team, versions=versions) if meta is None else meta
        best: dict[int, float] = {}
        for members in versions:
            mine = _side_vector(self.model, team_side(members, team, self.dex, self.usage, self, meta=meta))
            for g, parts, theirs_x in zip(self.groups, self._stacks(members), self._theirs_x):
                for i, p in zip(g.idx, _predict_batch(self.model, mine, theirs_x, parts)):
                    best[i] = p if i not in best else max(best[i], p)
        total = weights = 0.0
        for i, f in enumerate(self.fields):
            if not f.theirs:
                continue
            total += best[i] * f.weight
            weights += f.weight
        # past the best real team counts as no better (trust region)
        return cap_chance(self.model, total / weights) if weights else None

    def overall(self, team: list[PokemonSet] | list[Member], versions: list[list[Member]] | None = None) -> float:
        """Usage-weighted score vs the meta teams. Given PokemonSets, a team with two Mega
        Stones is scored with whichever Mega Evolves best against each meta team."""
        if not team or not self.fields:
            return 0.0
        versions = self.versions(team) if versions is None else versions
        best: dict[int, np.float64] = {}
        for members in versions:
            ours = side_support(members)
            for g, parts in zip(self.groups, self._stacks(members)):
                matrix = _scores_batch(parts, ours, g.reflect, g.light_screen, g.intimidate, g.tailwind,
                                       g.trick_room_tool, g.trick_room)
                scores = matrix.max(axis=1).mean(axis=1) - (-matrix).max(axis=2).mean(axis=1)
                for i, score in zip(g.idx, scores):
                    best[i] = score if i not in best else max(best[i], score)
        total = weights = 0.0
        for i, f in enumerate(self.fields):
            if not f.theirs:
                continue
            total += best[i] * f.weight
            weights += f.weight
        return total / weights if weights else 0.0


# --------------------------------------------------------------------------
# All meta teams at once
# --------------------------------------------------------------------------
# A swap search scores ~450 candidate teams against every meta team. Done one meta team at a time,
# that was ~30,000 small numpy calls per team; stacked, it's a few dozen. Every number is computed
# with the same operations in the same order as scores_from_parts and match_model.contributions, so
# results are identical to the last bit (tests/test_core.py checks it).
class _Group:
    """Meta teams with the same number of Pokemon, and their support as arrays shaped (teams, 1, 1)."""

    def __init__(self, idx: list[int], fields: list[_Field]):
        self.idx = idx
        col = lambda xs: np.array(xs, dtype=bool).reshape(-1, 1, 1)
        self.reflect = col([f.support.reflect for f in fields])
        self.light_screen = col([f.support.light_screen for f in fields])
        self.intimidate = col([f.support.intimidate for f in fields])
        self.tailwind = col([f.support.tailwind for f in fields])
        self.trick_room_tool = col([f.support.trick_room for f in fields])
        self.trick_room = col([f.trick_room for f in fields])


def _scores_batch(parts: dict[str, np.ndarray], ours: Support, reflect, light_screen, intimidate, tailwind,
                  trick_room_tool, trick_room, strength: float | None = None) -> np.ndarray:
    """scores_from_parts for a stack of meta teams: parts are (teams, ours, theirs); the meta teams'
    support arrays are (teams, 1, 1)."""
    from src.matchup import _hits
    strength = SUPPORT if strength is None else strength
    cut = 1 - strength / 3
    a_phys, b_phys = parts["a_phys"] > 0, parts["b_phys"] > 0
    a_factor = np.where(np.where(a_phys, reflect, light_screen), cut, 1.0)
    a_factor = a_factor * np.where(intimidate & a_phys, cut, 1.0)  # x 1.0 where they have no Intimidate
    b_factor = np.where(b_phys, ours.reflect, ours.light_screen)
    b_factor = np.where(b_factor, cut, 1.0)
    if ours.intimidate:
        b_factor = b_factor * np.where(b_phys, cut, 1.0)
    a_pct = parts["a_pct"] * a_factor
    b_pct = parts["b_pct"] * b_factor
    score = np.clip(np.log2(_hits(b_pct) / _hits(a_pct)), -3.0, 3.0)
    p_tw_a = SPEED_SUPPORT if ours.tailwind else 0.0
    p_tw_b = np.where(tailwind, SPEED_SUPPORT, 0.0)
    p_tr = np.where(trick_room, 1.0, 1 - (1 - (SPEED_SUPPORT if ours.trick_room else 0.0)) *
                    (1 - np.where(trick_room_tool, SPEED_SUPPORT, 0.0)))
    speed = np.zeros_like(score)
    for tw_a, pa in ((2, p_tw_a), (1, 1 - p_tw_a)):
        for tw_b, pb in ((2, p_tw_b), (1, 1 - p_tw_b)):
            for tr, pt in ((True, p_tr), (False, 1 - p_tr)):
                weight = pa * pb * pt
                if not np.any(weight):
                    continue
                diff = parts["a_spe"] * tw_a - parts["b_spe"] * tw_b
                sign = np.sign(diff) * (-1 if tr else 1)
                # a zero weight adds +-0.0, which leaves every sum unchanged
                speed += weight * SPEED_BONUS * sign
    return score + speed


_COMBOS: dict[tuple[int, int], np.ndarray] = {}


def _bring_batch(m: np.ndarray, n: int = 4) -> np.ndarray:
    """match_model._bring per meta team: m is (teams, rows, cols). The best n-of-rows score; the
    tie-break there only picks between equal scores, so the best score is the answer."""
    if m.shape[1] <= n:
        return m.max(axis=1).mean(axis=1) - (-m).max(axis=2).mean(axis=1)
    combos = _COMBOS.setdefault((m.shape[1], n), np.array(list(combinations(range(m.shape[1]), n))))
    sub = m[:, combos]                                # (teams, combos, n, their team)
    score = sub.max(axis=2).mean(axis=2) - (-sub).max(axis=3).mean(axis=2)
    return score.max(axis=1)


_MATCHUP_FEATURES = ["matchup score", "bring-4 score", "best damage (mean %)", "OHKOs", "2HKOs",
                     "outspeeds (share)"]


def _side_vector(model: dict, side: dict) -> np.ndarray:
    """One team's side of match_model.contributions' feature row, in the model's column order:
    meta score, popularity / 10 and profile where it has them, species counts, zero elsewhere."""
    m = model["model"]
    row = {"score vs meta": side["meta"], **side["profile"]}
    x = [row.get(f, 0.0) if f not in ("skill (Elo)", "experience") and f not in _MATCHUP_FEATURES else 0.0
         for f in m["features"]]
    index = {s: i for i, s in enumerate(m["species"])}
    sp = [0.0] * len(index)
    for s in side["species"]:
        if s in index:
            sp[index[s]] += 1
    return np.array(x + sp + [side["popularity"]], dtype=float)


def _predict_batch(model: dict, mine: np.ndarray, theirs: np.ndarray, parts: dict[str, np.ndarray]) -> list[float]:
    """match_model.predict_match(model, my side, each meta team's side, parts) for a stack of meta teams."""
    from src.match_model import _NO_SUPPORT, _hits
    m = model["model"]
    feats = m["features"]
    k = len(feats) + len(m["species"])
    no = np.zeros((1, 1, 1), dtype=bool)
    base = _scores_batch(parts, _NO_SUPPORT, no, no, no, no, no, no, strength=0.0)
    a_hits, b_hits = _hits(parts["a_pct"]), _hits(parts["b_pct"])
    matchup = {
        "matchup score": base.max(axis=1).mean(axis=1) - (-base).max(axis=2).mean(axis=1),
        "bring-4 score": _bring_batch(base) - _bring_batch(-base.transpose(0, 2, 1)),
        "best damage (mean %)": (np.minimum(parts["a_pct"], 150).max(axis=2).mean(axis=1)
                                 - np.minimum(parts["b_pct"], 150).max(axis=1).mean(axis=1)) / 100,
        "OHKOs": ((a_hits <= 1).sum(axis=(1, 2)) - (b_hits <= 1).sum(axis=(1, 2))).astype(float) / 6,
        "2HKOs": ((a_hits <= 2).sum(axis=(1, 2)) - (b_hits <= 2).sum(axis=(1, 2))).astype(float) / 6,
        "outspeeds (share)": ((parts["a_spe"] > parts["b_spe"]).mean(axis=(1, 2))
                              - (parts["a_spe"] < parts["b_spe"]).mean(axis=(1, 2))),
    }
    x = mine[None, :k] - theirs[:, :k]              # profile, meta score and species: mine minus theirs
    pop = (mine[k] - theirs[:, k]) / 10
    if "popularity" in feats:
        x[:, feats.index("popularity")] = pop
    for name, values in matchup.items():
        if name in feats:
            x[:, feats.index(name)] = values
    c = np.array(m["coef"], dtype=float)[None, :] * x
    bounds = (model.get("trust") or {}).get("features")
    if bounds:
        names = feats + [f"species: {s}" for s in m["species"]]
        lo = np.array([bounds[n][0] if n in bounds else -np.inf for n in names])
        hi = np.array([bounds[n][1] if n in bounds else np.inf for n in names])
        c = np.minimum(np.maximum(c, lo), hi)
    t = model.get("trust")
    out = []
    for row in c.tolist():
        total = sum(row)   # Python's sum, like predict_match (compensated since 3.12; the zeros add nothing)
        if t:
            total = min(max(total, t["total"][0]), t["total"][1])
        out.append(1 / (1 + math.exp(-total)))
    return out


def _answer(members: list[Member], threat: Member, doubles: bool) -> tuple[float, str]:
    best, label = -9.0, ""
    for m in members:
        s = pair_score(m, threat, doubles=doubles)
        if s > best:
            best, label = s, m.label
    return best, label


PLAYERS_PICK = "Players' pick"


def backing(fit_change: float, win_change: float) -> str:
    """Which signals a swap's score change rests on: "both", "fit only", "win model only" or "neither"."""
    if fit_change >= 0 and win_change >= 0:
        return "both"
    if fit_change >= 0:
        return "fit only"
    if win_change >= 0:
        return "win model only"
    return "neither"


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
    base_parts = engine.rating_parts(team, base_win)       # None without the team rating models
    base_rating = base_parts[:2] if base_parts else None
    ref = getattr(engine, "rating_ref", None)
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
            versions = engine.versions(new_team)
            overall = engine.overall(new_team, versions=versions)
            win = engine.win_chance(new_team, meta=overall, versions=versions) if base_win is not None else None
            parts = engine.rating_parts(new_team, win) if base_rating is not None else None
            rating = parts[:2] if parts else None
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
                # which half of the team score backs it (labs/swap_quality_lab.py): in real games,
                # swaps where fit and win chance both rose won more; win-chance-only ones showed no edge
                "backing": backing((parts[2] - base_parts[2]) / ref["fit_sd"],
                                   (win - base_win) / ref["chance_sd"]) if parts else None,
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
        # Players' pick: what players with the other five most often run here (labs/swap_choice_lab.py:
        # it finds the replacement real players chose 3.5x as often as ranking by shared roles and types).
        # Like Best upgrade, each Pokemon is offered for one member at most (where players run it most),
        # so a team-wide favourite doesn't fill every slot.
        rests = {slot: groups[slot][groups[slot]["swap in"] != best_rows[slot]["swap in"].iloc[0]]
                       .sort_values(["fit"] + sort, ascending=False, na_position="last") for slot in groups}
        top_fit = {slot: (r["fit"].iloc[0] if len(r) and pd.notna(r["fit"].iloc[0]) else -1.0)
                   for slot, r in rests.items()}
        taken_pp, pp_rows = set(), {}
        for slot in sorted(rests, key=lambda sl: -top_fit[sl]):
            r = rests[slot]
            fresh = r[~r["swap in"].isin(taken_pp)]
            chosen = (fresh if len(fresh) >= per_member - 1 else r).head(per_member - 1)
            taken_pp.update(chosen["swap in"])
            pp_rows[slot] = chosen.assign(pick=PLAYERS_PICK)
        picks = []
        for slot in sorted(groups):
            picks += [best_rows[slot], pp_rows[slot]]
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


__all__ = ["HIDDEN_MAX", "SwapEngine", "suggest_swaps", "mode_pool", "to_id", "backing", "PLAYERS_PICK"]
