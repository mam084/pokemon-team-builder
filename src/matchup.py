"""
matchup.py

Team-vs-team matchups against the meta.

Smogon stats don't contain whole teams, so the common archetypes are rebuilt
from teammate co-occurrence: start from a popular "anchor" Pokemon and keep
adding whichever Pokemon is most often paired with everyone already on the
team (respecting Species Clause and one Mega per team). Near-duplicate teams
are dropped, and each team is named after what it sets up (Rain, Sun,
Trick Room...). Every opposing member uses its most popular set.

Matchups are scored one Pokemon pair at a time, with real damage calcs
(src/damage.py, both sides using their actual sets):

    hits(a -> b) = hits a needs to KO b with its best move (average roll)
    pair(a, b)   = log2(hits(b -> a) / hits(a -> b))      clamped to +-3
                 + 0.5 if a outspeeds b (reversed under Trick Room)

Calcs use the meta team's weather when it sets one (a Sun team is scored in
sun), no terrain, and no stat boosts. So +1 means "a needs half as many hits to KO b as b needs to KO a". From the
pair matrix:

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
from src.damage import Field, calculate
from src.dex import Dex, Species, to_id
from src.usage import UsageData

SPEED_BONUS = 0.5


# --------------------------------------------------------------------------
# Archetypes
# --------------------------------------------------------------------------
@dataclass
class Archetype:
    name: str
    members: list[str]          # usage-entry names (Megas by Mega name)
    popularity: float           # mean usage % of its members
    trick_room: bool = False
    weather: str | None = None  # "sun" / "rain" / "sand" / "snow" if the team sets it


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


WEATHER_OF = {"Rain": "rain", "Sun": "sun", "Sand": "sand", "Snow": "snow"}


def _label(members: list[str], usage: UsageData, dex: Dex) -> tuple[str, bool, str | None]:
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
    weather = next((WEATHER_OF[t] for t in tags if t in WEATHER_OF), None)
    return f"{style} ({members[0]} + {members[1]})", trick_room, weather


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
        name, tr, weather = _label(team, usage, dex)
        popularity = sum(usage.usage(m) for m in team) / len(team)
        archetypes.append(Archetype(name, team, round(popularity, 1), tr, weather))
        if len(archetypes) >= keep:
            break
    return archetypes


def opponent_members(archetype_members: list[str], usage: UsageData, dex: Dex) -> list[Member]:
    sets = [usage.popular_set(m, dex) for m in archetype_members]
    return build_members([s for s in sets if s is not None], dex)


# --------------------------------------------------------------------------
# Pair scoring
# --------------------------------------------------------------------------
MAX_HITS = 8  # "can't realistically KO": a move doing under ~12% is treated like no attack
_CALC_CACHE: dict[tuple, tuple[float, str]] = {}


def _set_key(m: Member) -> tuple:
    p = m.pset
    if p is None:
        return (m.label,)
    return (p.species, p.item, p.ability, p.nature, tuple(sorted(p.sps.items())), tuple(p.moves))


def best_attack(a: Member, b: Member, doubles: bool = True, weather: str | None = None) -> tuple[float, str]:
    """(average % of b's HP, move name) for a's strongest move against b (no terrain or boosts)."""
    key = (_set_key(a), _set_key(b), doubles, weather)
    if key in _CALC_CACHE:
        return _CALC_CACHE[key]
    best = (0.0, "")
    if a.battler is not None and b.battler is not None:
        f = Field(doubles=doubles, weather=weather)
        for mv in a.damaging_moves:
            result = calculate(a.battler, b.battler, mv, f)
            avg = 100 * sum(result.rolls) / len(result.rolls) / result.defender_hp if result.rolls else 0.0
            if avg > best[0]:
                best = (avg, mv["name"])
    if len(_CALC_CACHE) > 200_000:
        _CALC_CACHE.clear()
    _CALC_CACHE[key] = best
    return best


def hits_to_ko(pct: float) -> int:
    return MAX_HITS if pct <= 0 else min(MAX_HITS, math.ceil(100 / pct - 1e-9))


def pair_score(a: Member, b: Member, trick_room: bool = False, doubles: bool = True,
               weather: str | None = None) -> float:
    a_hits = hits_to_ko(best_attack(a, b, doubles, weather)[0])
    b_hits = hits_to_ko(best_attack(b, a, doubles, weather)[0])
    score = max(-3.0, min(3.0, math.log2(b_hits / a_hits)))
    if a.stats["spe"] != b.stats["spe"]:
        faster = a.stats["spe"] > b.stats["spe"]
        score += SPEED_BONUS if faster != trick_room else -SPEED_BONUS
    return score


def pair_matrix(yours: list[Member], theirs: list[Member], trick_room: bool = False,
                doubles: bool = True, weather: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        [[pair_score(a, b, trick_room, doubles, weather) for b in theirs] for a in yours],
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
                  bring: int = 4, doubles: bool = True) -> pd.DataFrame:
    rows = []
    for arch in archetypes:
        theirs = opponent_members(arch.members, usage, dex)
        matrix = pair_matrix(yours, theirs, arch.trick_room, doubles, arch.weather)
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
                  trick_room: bool = False, pool: int = 60, top_n: int = 6, doubles: bool = True,
                  weather: str | None = None) -> pd.DataFrame:
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
        scores = [pair_score(cand, b, trick_room, doubles, weather) for b in theirs]
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


# --------------------------------------------------------------------------
# Individual threats
# --------------------------------------------------------------------------
def threat_report(members: list[Member], usage: UsageData, dex: Dex, n: int = 30,
                  doubles: bool = True) -> pd.DataFrame:
    """
    Popular Pokemon (popular sets) ranked by how much trouble they cause this team,
    using damage calcs in both directions:

        pressured = your Pokemon it 2HKOs (best move does >= 50% on average)
        answers   = your Pokemon that 2HKO it back while taking under 50%
        threat    = usage % x (pressured + 1) / (answers + 1)
    """
    rows = []
    for name, pct in usage.ranked(n):
        opp = opponent_members([name], usage, dex)
        if not opp:
            continue
        threat = opp[0]
        pressured, answers, key_calcs = [], [], []
        for m in members:
            dealt, dealt_move = best_attack(threat, m, doubles)
            taken, taken_move = best_attack(m, threat, doubles)
            if dealt >= 50:
                pressured.append(m.label)
                key_calcs.append((dealt, f"{dealt_move} {dealt:.0f}% to {m.label}"))
            if taken >= 50 and dealt < 50:
                answers.append(f"{m.label} ({taken_move} {taken:.0f}%)")
        key_calcs.sort(reverse=True)
        rows.append({
            "pokemon": threat.label, "usage %": pct,
            "2HKOs": len(pressured), "hardest hits": "; ".join(c for _, c in key_calcs[:2]) or "—",
            "answers": ", ".join(answers) or "none",
            "threat score": round(pct * (len(pressured) + 1) / (len(answers) + 1), 1),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("threat score", ascending=False).reset_index(drop=True)
