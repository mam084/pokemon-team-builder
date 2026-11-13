"""
recommend.py

Recommends the next Pokemon for a Champions team.

Earlier versions summed raw teammate co-occurrence, which mostly re-ranked
the most popular Pokemon and ignored what the team actually needed. This
version scores every legal candidate on five explainable signals, each scaled
to 0-1, and combines them with user-adjustable weights:

    synergy   how much more often the candidate appears next to the current
              members than chance would predict (mean log-lift from Smogon
              teammate stats)
    defense   does it resist / ignore the types the team is weak to?
    offense   does it hit popular Pokemon the team can't hit super effectively?
    roles     does it commonly bring a missing job (Fake Out, speed control...)?
    meta      overall usage - a prior that proven Pokemon tend to be good

Every score comes with a plain-English "why", so the output can be checked
rather than taken on faith. Without usage data the synergy/meta terms drop
out and roles are judged from the full learnset instead of common moves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.analysis import ROLES, Member, defense_matrix, meta_form, provides_role
from src.dex import Dex, to_id
from src.type_chart import ALL_TYPES, ability_defensive_multiplier
from src.usage import UsageData

DEFAULT_WEIGHTS = {"synergy": 0.30, "defense": 0.25, "offense": 0.15, "roles": 0.15, "meta": 0.15}


@dataclass
class TeamNeeds:
    weak_types: dict[str, float]          # type -> how badly the team needs a resist (0-1)
    unhit_meta: list[tuple[str, list[str], float]]  # (name, its types, usage %) the team can't hit SE
    missing_roles: list[str]


def team_needs(members: list[Member], dex: Dex, usage: UsageData | None, doubles: bool, meta_n: int = 25) -> TeamNeeds:
    weak_types: dict[str, float] = {}
    if members:
        matrix = defense_matrix(members)
        for atk_type, values in matrix.iterrows():
            weak = (values > 1).sum() + (values >= 4).sum() * 0.5
            covered = (values < 1).sum()
            need = max(0.0, weak - covered)
            if need > 0:
                weak_types[atk_type.lower()] = float(need)
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
                ability_defensive_multiplier(types, mv["type"].lower(), ability) >= 2
                for m in members for mv in m.damaging_moves
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


def _root(species) -> str:
    """Team-sheet identity: Megas and battle-only formes count as their base Pokemon."""
    if species.battle_only:
        return to_id(species.battle_only[0])
    return to_id(species.base_species) if species.is_mega else species.id


def _candidate_profile(name: str, dex: Dex, usage: UsageData | None):
    """Battle form, ability, move ids and STAB-ish attacking types a candidate brings."""
    species = dex.get_species(name)
    if usage is not None and usage.entry(name):
        form, ability = meta_form(name, usage, dex)
        move_ids = {to_id(m) for m, pct in usage.section(name, "moves").items() if pct >= 25}
        abilities = {ability}
    else:
        form, ability = species, to_id(species.abilities[0])
        move_ids = set(species.learnset)
        abilities = {to_id(a) for a in species.abilities}
    form = form or species
    atk_types = {t.lower() for t in form.types}
    for mid in move_ids:
        mv = dex.moves.get(mid)
        if mv and mv["category"] != "Status" and (mv["basePower"] or 0) >= 60 and usage is not None:
            atk_types.add(mv["type"].lower())
    spread = any(dex.moves.get(mid, {}).get("spread") and dex.moves[mid]["category"] != "Status" for mid in move_ids)
    return form, ability, move_ids, abilities, atk_types, spread


def recommend(
    members: list[Member],
    dex: Dex,
    usage: UsageData | None,
    doubles: bool = True,
    weights: dict | None = None,
    top_n: int = 12,
    pool_size: int = 80,
) -> pd.DataFrame:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if usage is None:
        weights["synergy"] = weights["meta"] = 0.0
    total_w = sum(weights.values()) or 1.0

    needs = team_needs(members, dex, usage, doubles)
    # Usage stats key Megas by their Mega name, so look members up by battle form.
    team_species = [m.form.name for m in members]
    on_team = {_root(m.form) for m in members}
    mega_on_team = any(m.form.is_mega for m in members)

    # Candidate pool: the usage leaderboard if we have one, else every legal Pokemon.
    if usage is not None:
        pool = [name for name, _ in usage.ranked(pool_size)]
    else:
        pool = [s.name for s in dex.selectable_species()]
    pool = [p for p in pool if dex.get_species(p) and _root(dex.get_species(p)) not in on_team]

    max_usage = max((usage.usage(p) for p in pool), default=1.0) if usage else 1.0
    rows = []
    for name in pool:
        form, ability, move_ids, abilities, atk_types, spread = _candidate_profile(name, dex, usage)
        cand_types = [t.lower() for t in form.types]
        reasons = []

        # synergy: mean log-lift with each current member (log2(1+lift), capped)
        synergy = 0.0
        if usage is not None and team_species:
            lifts = [usage.lift(member, name) for member in team_species if usage.entry(member)]
            if lifts:
                synergy = min(1.0, sum(math.log2(1 + l) for l in lifts) / len(lifts) / 2)
                best = max(team_species, key=lambda m: usage.lift(m, name))
                if usage.lift(best, name) >= 1.5:
                    reasons.append(f"{usage.lift(best, name):.1f}x more common than usual next to {best}")

        # defense: weighted share of the team's weak types it resists, minus ones it's also weak to
        defense = 0.0
        if needs.weak_types:
            gain = 0.0
            covered = []
            for t, w in needs.weak_types.items():
                mult = ability_defensive_multiplier(cand_types, t, ability)
                if mult < 1:
                    gain += w
                    covered.append(t.title())
                elif mult > 1:
                    gain -= w * 0.75
            defense = max(0.0, gain / sum(needs.weak_types.values()))
            if covered:
                reasons.append("resists " + ", ".join(covered[:4]))

        # offense: share of (usage-weighted) unhit meta Pokemon it hits super effectively
        offense = 0.0
        if needs.unhit_meta:
            hit = [(n, p) for n, types, p in needs.unhit_meta
                   if any(ability_defensive_multiplier(types, t) >= 2 for t in atk_types)]
            offense = sum(p for _, p in hit) / sum(p for _, _, p in needs.unhit_meta)
            if hit:
                reasons.append("hits " + ", ".join(n for n, _ in hit[:3]) + " super effectively")

        # roles: share of missing roles it fills
        roles = 0.0
        if needs.missing_roles:
            filled = [r for r in needs.missing_roles if provides_role(r, move_ids, abilities, spread)]
            roles = len(filled) / len(needs.missing_roles)
            if filled:
                labels = {r.key: r.label for r in ROLES}
                reasons.append("adds " + ", ".join(labels[r] for r in filled[:3]))

        meta = (usage.usage(name) / max_usage) if usage is not None else 0.0

        score = (weights["synergy"] * synergy + weights["defense"] * defense + weights["offense"] * offense
                 + weights["roles"] * roles + weights["meta"] * meta) / total_w
        note = ""
        if mega_on_team and form.is_mega:
            note = "second Mega - only one can Mega Evolve per battle"
            score *= 0.8
        rows.append({
            "pokemon": name, "form": form.name, "types": "/".join(form.types), "score": round(score * 100, 1),
            "synergy": round(synergy, 2), "defense": round(defense, 2), "offense": round(offense, 2),
            "roles": round(roles, 2), "meta": round(meta, 2),
            "why": "; ".join(reasons) or "solid all-round pick", "note": note,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)


__all__ = ["DEFAULT_WEIGHTS", "TeamNeeds", "team_needs", "recommend", "ALL_TYPES"]
