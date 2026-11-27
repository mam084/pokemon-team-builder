"""
recommend.py

Recommends the next Pokemon for a Champions team.

Earlier versions summed raw teammate co-occurrence, which mostly re-ranked
the most popular Pokemon and ignored what the team actually needed. This
version scores every legal candidate on five explainable signals, each scaled
to 0-1, and combines them with user-adjustable weights:

    synergy   how much more often the candidate appears next to the current
              members than chance would predict. This is a *whole-team*
              score: the mean of log2(lift) over every current member, so a
              candidate that fits two members beats one that fits only one.
              Lift is shrunk toward 1 for rare Pokemon, and mapped to 0-1 so
              that "no relationship" (lift 1) scores 0.33 and lift >= 4 with
              everyone scores 1.
    defense   does it resist / ignore the types the team is weak to?
    offense   does it hit popular Pokemon the team can't hit super effectively?
    roles     does it commonly bring a missing job (Fake Out, speed control...)?
    meta      overall usage - a prior that proven Pokemon tend to be good

Every score comes with a plain-English "why", so the output can be checked
rather than taken on faith. Without usage data the synergy/meta terms drop
out and roles are judged from the full learnset instead of common moves.
"""

from __future__ import annotations

import json
from pathlib import Path

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis import ROLES, Member, defense_matrix, meta_form, provides_role
from src.dex import Dex, to_id
from src.team import MAX_MEGAS
from src.plan import LABELS, SETTERS, enabler_score, plan_score, plan_users, profile_from, team_plans
from src.type_chart import ALL_TYPES, ability_defensive_multiplier, move_type
from src.usage import UsageData

# Tuned on 4,003 real tournament teams and validated on 1,546 newer ones (5-signal grid, then a
# line search for plan)
# (src/evaluate.py, results in data/evaluation/<regulation>.json). Offense and roles got
# zero weight: they didn't help predict what players actually bring, so they
# only shape the "why" text unless you raise them in the app.
# Tuned with tournament pairings in the synergy signal (pairings from the oldest teams, tuned
# on the next, tested on the newest 30%: MRR 0.556, top-10 76.9%; ladder-only synergy: 0.539).
DEFAULT_WEIGHTS = {"synergy": 0.8, "defense": 0.0, "offense": 0.0, "roles": 0.0, "meta": 0.2, "plan": 0.0}


def _tuned_weights() -> dict:
    """The weights the latest evaluation tuned (data/evaluation/<regulation>.json, refreshed monthly),
    so Popular picks follows the newest data; the constants above are the fallback."""
    from src.formats import CURRENT
    path = Path(__file__).resolve().parent.parent / "data" / "evaluation" / f"{CURRENT.regulation}.json"
    try:
        tuned = json.loads(path.read_text())["tuned_weights"]
    except (OSError, ValueError, KeyError):
        return DEFAULT_WEIGHTS
    return {k: float(tuned.get(k, 0.0)) for k in DEFAULT_WEIGHTS}


DEFAULT_WEIGHTS = _tuned_weights()
# The plan signal (weather / Trick Room / Tailwind / terrain fit, src/plan.py) only helps a
# little at a small weight and hurts beyond it (MRR falls from ~0.48 to 0.44 at 0.3):
# tournament players mostly bring proven meta Pokemon. So it gets the small tuned weight in
# "popular" mode, and drives the exploration modes, whose weights are a design choice rather
# than fitted: synergy (lift is already popularity-adjusted), defense to stop type stacking,
# and plan to build around the core's mechanics.
EXPLORE_WEIGHTS = {"synergy": 0.40, "defense": 0.25, "offense": 0.05, "roles": 0.05, "meta": 0.0, "plan": 0.25}

# How much the recommender leans on popularity:
#   popular  tuned defaults; the candidate pool is the usage top 80
#   neutral  popularity gets no weight, and every Pokemon with usage data is a candidate
#            (teammate lift is already popularity-adjusted, so rare picks compete fairly)
#   hidden   like neutral, without Pokemon on 3%+ of ladder teams
FIT_SCALE = 1.5  # learned fit (summed log-odds) -> 0..1: +1.5 -> 0.73, +3 -> 0.88
POPULAR_FIT_SCALE = 3.0  # Popular picks adds the pick rate, so its logits run wider
HIDDEN_MAX = 3.0  # Hidden gems leaves out Pokemon on this % of ladder teams or more
MODES = {"neutral": "Neutral", "popular": "Popular picks", "hidden": "Hidden gems"}


@dataclass
class TeamNeeds:
    weak_types: dict[str, float]          # type -> how badly the team needs a resist (0-1)
    unhit_meta: list[tuple[str, list[str], float]]  # (name, its types, usage %) the team can't hit SE
    missing_roles: list[str]


_PREVALENCE: dict[tuple, dict[str, float]] = {}


def attack_prevalence(usage: UsageData, dex: Dex, n: int = 60) -> dict[str, float]:
    """
    How much the meta attacks with each type (mean 1.0): usage-weighted share of the
    top Pokemon's sets running damaging moves of that type. Fire > 1 means a Fire
    weakness gets hit more often than an average weakness would.
    """
    key = (id(usage), id(dex), n)
    if key not in _PREVALENCE:
        totals = {t: 0.0 for t in ALL_TYPES}
        for name, pct in usage.ranked(n):
            ability = meta_form(name, usage, dex)[1]
            for move_id, move_pct in usage.section(name, "moves").items():
                mv = dex.moves.get(to_id(move_id))
                if mv and mv["category"] != "Status" and (mv["basePower"] or 0) > 0:
                    totals[move_type(mv, ability).lower()] += pct * move_pct / 100
        mean = sum(totals.values()) / len(totals) or 1.0
        _PREVALENCE[key] = {t: v / mean for t, v in totals.items()}
    return _PREVALENCE[key]


def team_needs(members: list[Member], dex: Dex, usage: UsageData | None, doubles: bool, meta_n: int = 25,
               weight_by_meta: bool = False) -> TeamNeeds:
    """With weight_by_meta, each weakness counts in proportion to how often the meta
    attacks with that type (a Fire weakness matters more than a Bug weakness)."""
    weak_types: dict[str, float] = {}
    if members:
        matrix = defense_matrix(members)
        for atk_type, values in matrix.iterrows():
            weak = (values > 1).sum() + (values >= 4).sum() * 0.5
            covered = (values < 1).sum()
            need = max(0.0, weak - covered)
            if need > 0:
                weak_types[atk_type.lower()] = float(need)
    if weak_types and weight_by_meta and usage is not None:
        prevalence = attack_prevalence(usage, dex)
        weak_types = {t: v * prevalence.get(t, 1.0) for t, v in weak_types.items()}
    if weak_types:
        top = max(weak_types.values())
        weak_types = {t: v / top for t, v in weak_types.items()}

    unhit = []
    if usage is not None:
        for name, pct in usage.ranked(meta_n):
            form, ability = meta_form(name, usage, dex)
            if form is None:
                continue
            types = [t.lower() for t in form.types]
            hit = any(
                ability_defensive_multiplier(types, move_type(mv, m.ability_id).lower(), ability) >= 2
                for m in members for mv in m.coverage_moves
            )
            if not hit:
                unhit.append((form.name, types, pct))

    missing = []
    for role in ROLES:
        if role.doubles_only and not doubles:
            continue
        if role.key in {"protect", "setup"}:
            continue  # nearly everything can learn these; not a reason to pick a Pokemon
        move_ids = {mv["id"] for m in members for mv in m.moves}
        ability_ids = {m.ability_id for m in members}
        spread = any(mv["spread"] for m in members for mv in m.damaging_moves)
        if not provides_role(role.key, move_ids, ability_ids, spread):
            missing.append(role.key)
    return TeamNeeds(weak_types, unhit, missing)


def _odds(pull: float) -> str:
    """A learned pull (log-odds) as 'how many times likelier', capped so rare pairs don't read as 40x."""
    x = math.exp(pull)
    return "10x+" if x >= 10 else f"{x:.1f}x"


def _root(species) -> str:
    """Team-sheet identity: Megas and battle-only formes count as their base Pokemon."""
    if species.battle_only:
        return to_id(species.battle_only[0])
    return to_id(species.base_species) if species.is_mega else species.id


_PROFILE_CACHE: dict[tuple, tuple] = {}


def _candidate_profile(name: str, dex: Dex, usage: UsageData | None):
    """Battle form, ability, move ids and STAB-ish attacking types a candidate brings (cached)."""
    key = (name, id(dex), id(usage))
    if key not in _PROFILE_CACHE:
        _PROFILE_CACHE[key] = _build_profile(name, dex, usage)
    return _PROFILE_CACHE[key]


def _build_profile(name: str, dex: Dex, usage: UsageData | None):
    species = dex.get_species(name)
    if usage is not None and usage.entry(name):
        form, ability = meta_form(name, usage, dex)
        move_ids = {to_id(m) for m, pct in usage.section(name, "moves").items() if pct >= 25}
        abilities = {ability}
        plan_abilities = {to_id(a) for a, pct in usage.section(name, "abilities").items() if pct >= 20} | {ability}
    else:
        form, ability = species, to_id(species.abilities[0])
        move_ids = set(species.learnset)
        abilities = {to_id(a) for a in species.abilities}
        plan_abilities = abilities
    form = form or species
    if form.is_mega:
        plan_abilities = {to_id(form.abilities[0])}
    atk_types = {t.lower() for t in form.types}
    for mid in move_ids:
        mv = dex.moves.get(mid)
        if mv and mv["category"] != "Status" and (mv["basePower"] or 0) >= 60 and usage is not None:
            atk_types.add(move_type(mv, ability).lower())
    spread = any(dex.moves.get(mid, {}).get("spread") and dex.moves[mid]["category"] != "Status" for mid in move_ids)
    plan_profile = profile_from(form, plan_abilities, move_ids, dex)
    return form, ability, move_ids, abilities, atk_types, spread, plan_profile


_PLAN_KEY = {label: key for key, label in LABELS.items()}


def _role_moves(role_key: str, move_ids: set[str], abilities: set[str], dex: Dex) -> frozenset:
    """The candidate's common moves that fill a role it was credited for, or nothing when its
    ability fills it (Intimidate, Drizzle...). The builder makes sure the set it adds carries one."""
    role = next(r for r in ROLES if r.key == role_key)
    if abilities & role.abilities:
        return frozenset()
    if role_key == "spread":
        return frozenset(m for m in move_ids if dex.moves.get(m, {}).get("spread")
                         and dex.moves[m]["category"] != "Status")
    return frozenset(move_ids & role.moves)


def recommend(
    members: list[Member],
    dex: Dex,
    usage: UsageData | None,
    doubles: bool = True,
    weights: dict | None = None,
    top_n: int | None = 12,
    pool_size: int = 80,
    raw: bool = False,
    mode: str = "popular",
    anchor: str | None = None,
    anchor_weight: float = 1.0,
    anchor_only: bool = False,
) -> pd.DataFrame:
    """
    Rank candidates for the next slot. With raw=True, return every candidate
    (unsorted, with a "root" column and the un-blended component scores) so
    callers such as src/evaluate.py can re-rank under any weights cheaply.
    anchor: a member (species) whose pairings count anchor_weight times, so a team built around
    a rarely used core keeps pairing with it instead of with its popular teammates.
    anchor_only: the teammate pull comes from the anchor alone (scaled by team size, so it sits on the
    same scale as the whole team's), ignoring how a candidate pairs with the other members.
    """
    base_weights = DEFAULT_WEIGHTS if mode == "popular" else EXPLORE_WEIGHTS
    weights = {**base_weights, **(weights or {})}
    if usage is None:
        weights["synergy"] = weights["meta"] = 0.0
    if mode in ("neutral", "hidden"):
        weights["meta"] = 0.0
        pool_size = 10_000
    total_w = sum(weights.values()) or 1.0

    explore = mode != "popular"
    needs = team_needs(members, dex, usage, doubles, weight_by_meta=explore)
    # Usage stats key Megas by their Mega name, so look members up by battle form.
    team_species = [m.form.name for m in members]
    on_team = {m.form.num for m in members}  # Species Clause: by Pokedex number
    megas_on_team = sum(1 for m in members if m.form.is_mega)
    plans = team_plans(members, dex)

    # Once a plan has its core (2+ members already playing into it), stop piling on more of
    # the same and patch the core's weak spots instead - an Ice team needs a Fire answer.
    glue = None
    if explore and plans:
        cores = [(plan_users(members, p, dex), p) for p in plans if not p.needed]
        users, plan_core = max(cores, key=lambda x: x[0]) if cores else (0, None)
        if users >= 2:
            glue = plan_core
            weights["plan"] *= 0.4
            weights["defense"] *= 1.8
            total_w = sum(weights.values()) or 1.0

    # Candidate pool: the usage leaderboard if we have one, else every legal Pokemon.
    if usage is not None:
        pool = [name for name, _ in usage.ranked(pool_size)]
    else:
        pool = [s.name for s in dex.selectable_species()]
    pool = [p for p in pool if dex.get_species(p) and dex.get_species(p).num not in on_team]
    if mode == "hidden" and usage is not None:  # gems: leave common Pokémon out, not just marked down
        pool = [p for p in pool if not usage.is_common(p, dex, HIDDEN_MAX)]

    max_usage = max((usage.usage(p) for p in pool), default=1.0) if usage else 1.0
    # Learned teammate model (src/synergy.py), when this format has one: synergy is its pull
    # toward your whole team, and popularity its learned pick rate. Lift is the fallback.
    tm = usage.teammates if usage is not None else None
    if tm is not None:
        team_roots = [dex.sheet_id(m.form) for m in members]
        team_ids = [tm.index[r] for r in team_roots if r in tm.index]
        fit_vec = tm.W[team_ids].sum(0) if team_ids else np.zeros(len(tm.vocab))
        anchor_root = dex.sheet_id(dex.get_species(anchor)) if anchor and dex.get_species(anchor) else None
        if anchor_root in tm.index and anchor_only:
            fit_vec = len(team_ids) * tm.W[tm.index[anchor_root]]
        elif anchor_root in tm.index and anchor_weight != 1.0:
            fit_vec = fit_vec + (anchor_weight - 1.0) * tm.W[tm.index[anchor_root]]
        conf = tm.confidence()
        b_mid = float(np.median(tm.b))
        root_label = {dex.sheet_id(m.form): (m.pset.species if m.pset is not None else m.label) for m in members}
    rows = []
    for name in pool:
        form, ability, move_ids, abilities, atk_types, spread, plan_profile = _candidate_profile(name, dex, usage)
        cand_types = [t.lower() for t in form.types]
        reasons = []
        parts: dict[str, str] = {}  # the same reasons by kind, for the app's cards
        credited: list[tuple[str, frozenset]] = []  # (claim, moves that deliver it) - see _role_moves

        synergy = 0.0
        tm_i = tm.index.get(dex.sheet_id(form)) if tm is not None else None
        if tm is not None and tm_i is not None:
            # the summed pull from every member (log-odds), squashed so 0.5 = no pull either way;
            # exploring damps Pokemon few teams use, whose pulls rest on little data
            fit = float(fit_vec[tm_i]) if tm_i is not None else 0.0
            if explore and tm_i is not None:
                fit *= float(conf[tm_i])
            elif tm_i is not None:  # Popular picks: the full model, pick rate included (tests best)
                fit += float(tm.b[tm_i]) - b_mid
            scale = FIT_SCALE if explore else POPULAR_FIT_SCALE
            synergy = 1 / (1 + math.exp(-fit / scale)) if team_ids else 0.0
            if tm_i is not None and team_ids:
                pulls = sorted(((float(tm.W[j, tm_i]), tm.vocab[j]) for j in team_ids), reverse=True)
                good = [(w, r) for w, r in pulls if w >= 0.4][:3]
                bad = [(w, r) for w, r in pulls if w <= -0.7][-2:]
                if good:
                    reasons.append("players pair it with " + ", ".join(
                        f"{root_label.get(r, r)} ({_odds(w)})" for w, r in good))
                    parts["fit"] = reasons[-1]
                if bad:
                    reasons.append("rarely run next to " + ", ".join(
                        f"{root_label.get(r, r)} ({_odds(w)})" for w, r in bad))
                    parts["clash"] = reasons[-1]
        elif tm is not None:
            # new to the model (e.g. just released): no evidence either way - neutral, not last
            synergy = 0.5 if team_ids else 0.0
            if team_ids:
                reasons.append("too new or rare for teammate data yet")
                parts["fit"] = reasons[-1]
        # synergy (fallback): mean log2(lift) across the whole team, mapped so lift 1 -> 0.33, lift 4 -> 1
        elif usage is not None and team_species:
            pairs = {m: usage.pair_lift(m, name) for m in team_species if usage.entry(m)}
            if pairs:
                mean_log = sum(math.log2(lift) for lift, _ in pairs.values()) / len(pairs)
                synergy = min(1.0, max(0.0, (mean_log + 1) / 3))
                strong = sorted(((lift, m) for m, (lift, known) in pairs.items() if known and lift >= 1.5),
                                reverse=True)
                if strong:
                    reasons.append("paired often with " + ", ".join(f"{m} ({lift:.1f}x)" for lift, m in strong[:3]))
                    parts["fit"] = reasons[-1]

        # defense: weighted share of the team's weak types it resists, minus ones it's also weak to
        defense = 0.0
        if needs.weak_types:
            gain = 0.0
            covered = []
            for t, w in sorted(needs.weak_types.items(), key=lambda kv: -kv[1]):
                mult = ability_defensive_multiplier(cand_types, t, ability)
                if mult < 1:
                    gain += w
                    by_ability = mult == 0 and ability_defensive_multiplier(cand_types, t) > 0
                    label = t.title()
                    if by_ability and dex.abilities.get(ability):
                        label += f" (immune: {dex.abilities[ability]['name']})"
                    covered.append(label)
                elif mult > 1:
                    gain -= w * 0.75
            defense = max(0.0, gain / sum(needs.weak_types.values()))
            if covered:
                verb = f"covers your {glue.label} core's weak spots:" if glue else "resists"
                reasons.append(f"{verb} " + ", ".join(covered[:4]))
                parts["cover"] = reasons[-1]

        # offense: share of (usage-weighted) unhit meta Pokemon it hits super effectively
        offense = 0.0
        if needs.unhit_meta:
            hit = [(n, p) for n, types, p in needs.unhit_meta
                   if any(ability_defensive_multiplier(types, t) >= 2 for t in atk_types)]
            offense = sum(p for _, p in hit) / sum(p for _, _, p in needs.unhit_meta)
            if hit:
                reasons.append("hits " + ", ".join(n for n, _ in hit[:3]) + " super effectively")
                parts["hits"] = reasons[-1]

        # roles: share of missing roles it fills
        roles = 0.0
        if needs.missing_roles:
            filled = [r for r in needs.missing_roles if provides_role(r, move_ids, abilities, spread)]
            roles = len(filled) / len(needs.missing_roles)
            for r in filled:
                credit = _role_moves(r, move_ids, abilities, dex)
                if credit:
                    credited.append((next(x.label for x in ROLES if x.key == r), credit))
            if filled:
                labels = {r.key: r.label for r in ROLES}
                reasons.append("adds " + ", ".join(labels[r] for r in filled[:3]))
                parts["adds"] = reasons[-1]

        # plan: how well it plays into the team's weather / Trick Room / Tailwind / terrain
        plan, plan_why = plan_score(plan_profile, plans, members, dex)
        start, start_why, starts = enabler_score(plan_profile, members, plans, dex)
        if start > plan:
            plan, plan_why = start, start_why
            setter_abilities, setter_moves = SETTERS[_PLAN_KEY[starts]]
            if not plan_profile.abilities & setter_abilities and move_ids & setter_moves:
                credited.insert(0, (starts, frozenset(move_ids & setter_moves)))
        else:
            starts = ""
        if plan_why:
            reasons.insert(0, plan_why)
            parts["plan"] = plan_why

        meta = (usage.usage(name) / max_usage) if usage is not None else 0.0

        score = (weights["synergy"] * synergy + weights["defense"] * defense + weights["offense"] * offense
                 + weights["roles"] * roles + weights["meta"] * meta + weights["plan"] * plan) / total_w
        note = ""
        extra_mega = form.is_mega and megas_on_team >= MAX_MEGAS
        if extra_mega:
            note = f"Mega Stone #{megas_on_team + 1} - more than two leaves you short on options"
            score *= 0.8
        elif form.is_mega and megas_on_team:
            note = "second Mega Stone: you pick which one Mega Evolves each game"
        rows.append({
            "pokemon": name, "form": form.name, "types": "/".join(form.types), "score": round(score * 100, 1),
            "synergy": round(synergy, 4), "defense": round(defense, 2), "offense": round(offense, 2),
            "roles": round(roles, 2), "meta": round(meta, 2), "plan": round(plan, 2),
            "why": "; ".join(reasons) or "solid all-round pick", "note": note, "parts": parts,
            "extra_mega": bool(extra_mega), "starts": starts, "credited": credited,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.attrs["glue"] = glue.label if glue else None
    df.attrs["weights"] = dict(weights)  # as actually applied (glue mode shifts them)
    df.attrs["weak_types"] = sorted(needs.weak_types, key=lambda t: -needs.weak_types[t])[:4]
    df["root"] = [_root(dex.get_species(n)) for n in df["pokemon"]]
    if raw:
        return df
    # Garchomp and Garchomp-Mega-Z are one team-sheet Pokemon: keep its best-scoring form.
    attrs = dict(df.attrs)
    df = df.sort_values("score", ascending=False).drop_duplicates("root").drop(columns=["root", "extra_mega"])
    df = (df.head(top_n) if top_n else df).reset_index(drop=True)
    df.attrs.update(attrs)
    return df


__all__ = ["DEFAULT_WEIGHTS", "EXPLORE_WEIGHTS", "MODES", "TeamNeeds", "team_needs", "recommend", "ALL_TYPES"]
