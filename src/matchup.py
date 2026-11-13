"""
matchup.py

Team-vs-team matchups against the meta.

Smogon stats don't contain whole teams, so the common archetypes are rebuilt
from teammate co-occurrence: start from a popular "anchor" Pokemon and keep
adding whichever Pokemon is most often paired with everyone already on the
team (respecting Species Clause and one Mega per team). Near-duplicate teams
are dropped, and each team is named after what it sets up (Rain, Sun,
Trick Room...). Every opposing member uses its most popular set.

Matchups are scored one Pokemon pair at a time:

    pair(a, b) = log2(best multiplier a hits b with)
               - log2(best multiplier b hits a with)
               + 0.5 if a outspeeds b (reversed under Trick Room)

so +1 means "a hits b one step harder than b hits a". From the pair matrix:

    team score    = (mean over their Pokemon of your best answer to it)
                  - (mean over your Pokemon of their best answer to it)
                    so the score is zero-sum: a mirror match scores 0
    bring N       = the N of your 6 that maximize that score (VGC: 4, BSS: 3)
    counter picks = meta Pokemon with the best average pair score vs the team
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from src.analysis import Member, build_members
from src.dex import Dex, Species, to_id
from src.type_chart import ability_defensive_multiplier
from src.usage import UsageData

SPEED_BONUS = 0.5
IMMUNE_LOG = -3.0  # log2 value used for a 0x hit


# --------------------------------------------------------------------------
# Archetypes
# --------------------------------------------------------------------------
@dataclass
class Archetype:
    name: str
    members: list[str]          # usage-entry names (Megas by Mega name)
    popularity: float           # mean usage % of its members
    trick_room: bool = False


def _root(species: Species) -> str:
    if species.battle_only:
        return to_id(species.battle_only[0])
    return to_id(species.base_species)  # Basculegion-F and Basculegion share a species


SETTERS = [  # (label, abilities, moves) - first match names the archetype
    ("Rain", {"drizzle"}, {"raindance"}),
    ("Sun", {"drought", "megasol"}, {"sunnyday"}),
    ("Sand", {"sandstream"}, {"sandstorm"}),
    ("Snow", {"snowwarning"}, {"snowscape"}),
    ("Trick Room", set(), {"trickroom"}),
    ("Psychic Terrain", {"psychicsurge"}, set()),
    ("Tailwind", set(), {"tailwind"}),
]


def _label(members: list[str], usage: UsageData, dex: Dex) -> tuple[str, bool]:
    tags = []
    trick_room = False
    for label, abilities, moves in SETTERS:
        for m in members:
            form = dex.get_species(m)
            abil = {to_id(form.abilities[0])} if form is not None and form.is_mega else \
                {to_id(a) for a, p in usage.section(m, "abilities").items() if p >= 50}
            mv = {to_id(x) for x, p in usage.section(m, "moves").items() if p >= 40}
            if abil & abilities or mv & moves:
                tags.append(label)
                trick_room |= label == "Trick Room"
                break
    style = " + ".join(dict.fromkeys(tags[:2])) or "Goodstuffs"
    return f"{style} ({members[0]} + {members[1]})", trick_room


def build_archetypes(usage: UsageData, dex: Dex, team_size: int = 6, anchors: int = 40,
                     keep: int = 10) -> list[Archetype]:
    archetypes: list[Archetype] = []
    for anchor, _ in usage.ranked(anchors):
        anchor_form = dex.get_species(anchor)
        if anchor_form is None:
            continue
        team = [anchor]
        roots = {_root(anchor_form)}
        mega = anchor_form.is_mega
        while len(team) < team_size:
            scores: dict[str, float] = {}
            for i, member in enumerate(team):
                weight = 2.0 if i == 0 else 1.0  # keep the team built around its anchor
                for mate, pct in usage.section(member, "teammates").items():
                    scores[mate] = scores.get(mate, 0.0) + weight * pct
            best = None
            for mate, score in sorted(scores.items(), key=lambda kv: -kv[1]):
                form = dex.get_species(mate)
                if form is None or _root(form) in roots or (mega and form.is_mega) or not usage.entry(mate):
                    continue
                best = mate
                break
            if best is None:
                break
            team.append(best)
            form = dex.get_species(best)
            roots.add(_root(form))
            mega |= form.is_mega
        if len(team) < 4:
            continue
        if any(len(set(team) & set(a.members)) >= 5 for a in archetypes):
            continue  # near-duplicate of a team we already have
        name, tr = _label(team, usage, dex)
        popularity = sum(usage.usage(m) for m in team) / len(team)
        archetypes.append(Archetype(name, team, round(popularity, 1), tr))
        if len(archetypes) >= keep:
            break
    return archetypes


def opponent_members(archetype_members: list[str], usage: UsageData, dex: Dex) -> list[Member]:
    sets = [usage.popular_set(m, dex) for m in archetype_members]
    return build_members([s for s in sets if s is not None], dex)


# --------------------------------------------------------------------------
# Pair scoring
# --------------------------------------------------------------------------
def _best_log_hit(attacker: Member, defender: Member) -> float:
    best = None
    for mv in attacker.damaging_moves:
        mult = ability_defensive_multiplier(defender.types, mv["type"].lower(), defender.ability_id)
        best = mult if best is None else max(best, mult)
    if best is None:
        return -1.0  # no attacks at all: treat like a resisted hit
    return IMMUNE_LOG if best == 0 else math.log2(best)


def pair_score(a: Member, b: Member, trick_room: bool = False) -> float:
    score = _best_log_hit(a, b) - _best_log_hit(b, a)
    if a.stats["spe"] != b.stats["spe"]:
        faster = a.stats["spe"] > b.stats["spe"]
        score += SPEED_BONUS if faster != trick_room else -SPEED_BONUS
    return score


def pair_matrix(yours: list[Member], theirs: list[Member], trick_room: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        [[pair_score(a, b, trick_room) for b in theirs] for a in yours],
        index=[a.label for a in yours], columns=[b.label for b in theirs],
    )


def team_score(matrix: pd.DataFrame) -> float:
    """How well you answer their Pokemon minus how well they answer yours (0 = even)."""
    if matrix.empty:
        return 0.0
    yours_answer_theirs = matrix.max(axis=0).mean()
    theirs_answer_yours = (-matrix).max(axis=1).mean()
    return float(yours_answer_theirs - theirs_answer_yours)


def best_bring(matrix: pd.DataFrame, n: int) -> tuple[list[str], float]:
    """The n members whose best answers cover their team best (ties: better average)."""
    if len(matrix.index) <= n:
        return list(matrix.index), team_score(matrix)
    best, best_key = None, None
    for combo in combinations(matrix.index, n):
        sub = matrix.loc[list(combo)]
        key = (team_score(sub), float(sub.values.mean()))
        if best_key is None or key > best_key:
            best, best_key = list(combo), key
    return best, best_key[0]


def verdict(score: float) -> str:
    if score >= 0.75:
        return "Favorable"
    if score >= 0.25:
        return "Slightly favorable"
    if score > -0.25:
        return "Even"
    if score > -0.75:
        return "Slightly unfavorable"
    return "Unfavorable"


# --------------------------------------------------------------------------
# Team vs meta
# --------------------------------------------------------------------------
def meta_matchups(yours: list[Member], archetypes: list[Archetype], usage: UsageData, dex: Dex,
                  bring: int = 4) -> pd.DataFrame:
    rows = []
    for arch in archetypes:
        theirs = opponent_members(arch.members, usage, dex)
        matrix = pair_matrix(yours, theirs, arch.trick_room)
        picks, picked_score = best_bring(matrix, bring)
        worst = matrix.max(axis=0).idxmin() if not matrix.empty else ""
        rows.append({
            "archetype": arch.name, "popularity": arch.popularity,
            "score": round(team_score(matrix), 2), "verdict": verdict(team_score(matrix)),
            f"bring {bring}": ", ".join(picks), "with bring": round(picked_score, 2),
            "hardest to answer": worst,
        })
    return pd.DataFrame(rows)


def counter_picks(theirs: list[Member], usage: UsageData, dex: Dex, exclude: set[str] | None = None,
                  trick_room: bool = False, pool: int = 60, top_n: int = 6) -> pd.DataFrame:
    """Meta Pokemon (popular sets) that match up best against a given team."""
    exclude_roots = {to_id(x) for x in (exclude or set())}
    their_roots = {_root(m.form) for m in theirs}
    rows = []
    for name, pct in usage.ranked(pool):
        form = dex.get_species(name)
        if form is None or _root(form) in exclude_roots | their_roots:
            continue
        pset = usage.popular_set(name, dex)
        if pset is None:
            continue
        members = build_members([pset], dex)
        if not members:
            continue
        cand = members[0]
        scores = [pair_score(cand, b, trick_room) for b in theirs]
        if not scores:
            continue
        beats = [b.label for b, s in zip(theirs, scores) if s >= 1]
        loses = [b.label for b, s in zip(theirs, scores) if s <= -1]
        rows.append({
            "pokemon": cand.label, "usage %": pct, "avg matchup": round(sum(scores) / len(scores), 2),
            "beats": ", ".join(beats) or "—", "loses to": ", ".join(loses) or "—",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("avg matchup", ascending=False).head(top_n).reset_index(drop=True)
