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
sun), no terrain, and no stat boosts. So +1 means "a needs half as many hits to KO b as b needs to KO a".

Support counts at the team level, since it helps teammates rather than one
pairing. A side's support (from the Pokemon it brings) changes every pair:

    Reflect / Light Screen / Aurora Veil  their physical / special hits on you x2/3
    Intimidate                            their physical hits on you x2/3
    Tailwind                              your Speed x2
    Trick Room                            turn order reversed

Each lasts only part of a game and can be stopped (Taunt, Fake Out, KOs), so it
applies with weight SUPPORT: damage x(1 - SUPPORT/3), and the Speed term is the
expected value over "it's up" / "it isn't" (weight SPEED_SUPPORT). Both weights
were checked on real match results; see the constants below. From the pair matrix:

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

import numpy as np
import pandas as pd

from src.analysis import Member, build_members
from src.team import MAX_MEGAS
from src.damage import Field, calculate
from src.dex import Dex, Species, to_id
from src.usage import UsageData

SPEED_BONUS = 0.5
# How much of a game a support effect counts for (see the docstring). Checked on 12,168 real
# tournament matches (src/validate.py): screens and Intimidate at 0.2 cost no measurable accuracy
# (log loss 0.69068 vs 0.69062 without), while Tailwind / Trick Room made predictions worse at
# every strength tried, so they don't change the score (SPEED_SUPPORT = 0).
SUPPORT = 0.2
SPEED_SUPPORT = 0.0


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


def _root(species: Species) -> int:
    return species.num  # Species Clause: Basculegion-F and Basculegion, Arcanine and -Hisui, share one


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
        megas = int(anchor_form.is_mega)
        while len(team) < team_size:
            scores: dict[str, float] = {}
            for i, member in enumerate(team):
                weight = 2.0 if i == 0 else 1.0  # keep the team built around its anchor
                for mate, pct in usage.section(member, "teammates").items():
                    scores[mate] = scores.get(mate, 0.0) + weight * pct
            best = None
            for mate, score in sorted(scores.items(), key=lambda kv: -kv[1]):
                form = dex.get_species(mate)
                if form is None or _root(form) in roots or (form.is_mega and megas >= MAX_MEGAS) or not usage.entry(mate):
                    continue
                best = mate
                break
            if best is None:
                break
            team.append(best)
            form = dex.get_species(best)
            roots.add(_root(form))
            megas += int(form.is_mega)
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
    """A meta team's popular sets. If it carries two Mega Stones, the first (its anchor's side)
    Mega Evolves and the other plays in its base forme, since only one can per battle."""
    sets = [s for s in (usage.popular_set(m, dex) for m in archetype_members) if s is not None]
    stones = [i for i, p in enumerate(sets) if p.is_mega(dex)]
    return build_members(sets, dex, evolve=stones[0] if stones else None)


# --------------------------------------------------------------------------
# Pair scoring
# --------------------------------------------------------------------------
MAX_HITS = 8  # "can't realistically KO": a move doing under ~12% is treated like no attack
_CALC_CACHE: dict[tuple, tuple[float, str]] = {}


def _set_key(m: Member) -> tuple:
    """Cache key for a member's calcs. The forme is part of it: with two Mega Stones the same
    set battles as a Mega in one version of the team and in its base forme in the other."""
    p = m.pset
    if p is None:
        return (m.label,)
    return (m.form.name, p.species, p.item, p.ability, p.nature, tuple(sorted(p.sps.items())), tuple(p.moves))


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
            if mv["id"] == "saltcure" and avg > 0:
                # Salt Cure's real damage is the residual it leaves: 1/8 max HP a turn (1/4 to
                # Water and Steel), so count it as part of each turn's damage
                avg += 25.0 if {"Water", "Steel"} & set(b.form.types) else 12.5
            if avg > best[0]:
                best = (avg, mv["name"])
    if len(_CALC_CACHE) > 200_000:
        _CALC_CACHE.clear()
    _CALC_CACHE[key] = best
    return best


def hits_to_ko(pct: float) -> int:
    return MAX_HITS if pct <= 0 else min(MAX_HITS, math.ceil(100 / pct - 1e-9))


@dataclass(frozen=True)
class Support:
    """Team-wide effects one side can set up."""
    reflect: bool = False
    light_screen: bool = False
    intimidate: bool = False
    tailwind: bool = False
    trick_room: bool = False

    def __or__(self, other: "Support") -> "Support":
        return Support(*(x or y for x, y in zip(self.astuple(), other.astuple())))

    def astuple(self) -> tuple:
        return (self.reflect, self.light_screen, self.intimidate, self.tailwind, self.trick_room)

    def names(self) -> list[str]:
        labels = ["Reflect", "Light Screen", "Intimidate", "Tailwind", "Trick Room"]
        return [n for n, on in zip(labels, self.astuple()) if on]


def member_support(m: Member) -> Support:
    moves = {mv["id"] for mv in m.moves}
    veil = "auroraveil" in moves
    return Support(reflect="reflect" in moves or veil, light_screen="lightscreen" in moves or veil,
                   intimidate=m.ability_id == "intimidate", tailwind="tailwind" in moves,
                   trick_room="trickroom" in moves)


def side_support(members) -> Support:
    out = Support()
    for m in members:
        out = out | member_support(m)
    return out


def _category(m: Member, move_name: str) -> str:
    return next((mv["category"] for mv in m.damaging_moves if mv["name"] == move_name), "Physical")


def pair_parts(yours: list[Member], theirs: list[Member], doubles: bool = True,
               weather: str | None = None) -> dict[str, np.ndarray]:
    """The raw pieces of every pair, before support: % each way, physical or not, Speeds."""
    shape = (len(yours), len(theirs))
    parts = {k: np.zeros(shape) for k in ("a_pct", "b_pct", "a_phys", "b_phys", "a_spe", "b_spe")}
    for i, a in enumerate(yours):
        for j, b in enumerate(theirs):
            a_pct, a_move = best_attack(a, b, doubles, weather)
            b_pct, b_move = best_attack(b, a, doubles, weather)
            parts["a_pct"][i, j], parts["b_pct"][i, j] = a_pct, b_pct
            parts["a_phys"][i, j] = _category(a, a_move) == "Physical"
            parts["b_phys"][i, j] = _category(b, b_move) == "Physical"
            parts["a_spe"][i, j], parts["b_spe"][i, j] = a.stats["spe"], b.stats["spe"]
    return parts


def _hits(pct: np.ndarray) -> np.ndarray:
    safe = np.where(pct > 0, pct, 1.0)
    return np.where(pct > 0, np.minimum(MAX_HITS, np.ceil(100 / safe - 1e-9)), MAX_HITS)


def _damage_factor(phys: np.ndarray, defender: Support, strength: float) -> np.ndarray:
    """Multiplier on hits into a side with this support (screens, Intimidate)."""
    cut = 1 - strength / 3
    screen = np.where(phys > 0, defender.reflect, defender.light_screen)
    factor = np.where(screen, cut, 1.0)
    if defender.intimidate:
        factor = factor * np.where(phys > 0, cut, 1.0)
    return factor


def scores_from_parts(parts: dict[str, np.ndarray], ours: Support, theirs: Support,
                      trick_room: bool = False, strength: float | None = None) -> np.ndarray:
    """Pair scores with both sides' support applied (see the module docstring)."""
    strength = SUPPORT if strength is None else strength
    a_pct = parts["a_pct"] * _damage_factor(parts["a_phys"], theirs, strength)
    b_pct = parts["b_pct"] * _damage_factor(parts["b_phys"], ours, strength)
    score = np.clip(np.log2(_hits(b_pct) / _hits(a_pct)), -3.0, 3.0)
    # Speed: expected value over whether each side's Tailwind / Trick Room is up
    speed_strength = SPEED_SUPPORT
    p_tw_a = speed_strength if ours.tailwind else 0.0
    p_tw_b = speed_strength if theirs.tailwind else 0.0
    p_tr = 1.0 if trick_room else 1 - (1 - (speed_strength if ours.trick_room else 0.0)) * \
        (1 - (speed_strength if theirs.trick_room else 0.0))
    speed = np.zeros_like(score)
    for tw_a, pa in ((2, p_tw_a), (1, 1 - p_tw_a)):
        for tw_b, pb in ((2, p_tw_b), (1, 1 - p_tw_b)):
            for tr, pt in ((True, p_tr), (False, 1 - p_tr)):
                weight = pa * pb * pt
                if weight == 0:
                    continue
                diff = parts["a_spe"] * tw_a - parts["b_spe"] * tw_b
                sign = np.sign(diff) * (-1 if tr else 1)
                speed += weight * SPEED_BONUS * sign
    return score + speed


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
    """Pair scores with both full sides' support applied. The raw parts ride along in
    .attrs so best_bring can re-apply support for just the Pokemon it brings."""
    parts = pair_parts(yours, theirs, doubles, weather)
    theirs_support = side_support(theirs)
    matrix = pd.DataFrame(scores_from_parts(parts, side_support(yours), theirs_support, trick_room),
                          index=[a.label for a in yours], columns=[b.label for b in theirs])
    matrix.attrs.update(parts=parts, row_support=[member_support(a) for a in yours],
                        theirs_support=theirs_support, trick_room=trick_room,
                        check=(tuple(matrix.index), tuple(matrix.columns), float(matrix.values.sum())))
    return matrix


def team_score(matrix: pd.DataFrame) -> float:
    """How well you answer their Pokemon minus how well they answer yours (0 = even)."""
    if matrix.empty:
        return 0.0
    yours_answer_theirs = matrix.max(axis=0).mean()
    theirs_answer_yours = (-matrix).max(axis=1).mean()
    return float(yours_answer_theirs - theirs_answer_yours)


def bring_matrix(matrix: pd.DataFrame, rows: list[int]) -> pd.DataFrame:
    """The matrix for just these of your Pokemon, with only *their* support applied."""
    a = matrix.attrs
    # pandas copies attrs onto derived frames (e.g. -matrix.T); only trust them on the original
    if "parts" not in a or a.get("check") != (tuple(matrix.index), tuple(matrix.columns),
                                               float(matrix.values.sum())):
        return matrix.iloc[rows]
    parts = {k: v[rows] for k, v in a["parts"].items()}
    ours = side_support([])
    for i in rows:
        ours = ours | a["row_support"][i]
    return pd.DataFrame(scores_from_parts(parts, ours, a["theirs_support"], a["trick_room"]),
                        index=matrix.index[rows], columns=matrix.columns)


def best_bring(matrix: pd.DataFrame, n: int) -> tuple[list[str], float]:
    """The n members whose best answers cover their team best, counting the support they
    bring for each other (ties: better average)."""
    if len(matrix.index) <= n:
        return list(matrix.index), team_score(matrix)
    best, best_key = None, None
    for combo in combinations(range(len(matrix.index)), n):
        sub = bring_matrix(matrix, list(combo))
        key = (team_score(sub), float(sub.values.mean()))
        if best_key is None or key > best_key:
            best, best_key = list(sub.index), key
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
def best_variant(variants, theirs: list[Member], trick_room: bool, doubles: bool, weather: str | None,
                 bring: int, picker=None) -> tuple[str | None, pd.DataFrame, list[str], float]:
    """
    For a team with several Mega Stones, which one to Mega Evolve against this
    opponent: the version with the best bring-N score. `variants` is the output
    of analysis.mega_variants (or a plain member list, treated as one version).
    `picker(members, matrix)` can choose the bring instead of the calcs (None = calcs).
    Returns (who evolves, pair matrix, bring picks, bring score); who is None when no
    Mega Stone holder is in the bring - you can't Mega Evolve a Pokémon you didn't bring.
    """
    if variants and isinstance(variants[0], Member):
        variants = [(next((m.form.name for m in variants if m.form.is_mega), None), variants)]
    best = None
    for who, members in variants:
        matrix = pair_matrix(members, theirs, trick_room, doubles, weather)
        picks, picked = best_bring(matrix, bring)
        chosen = picker(members, matrix) if picker else None
        if chosen:
            rows = [list(matrix.index).index(x) for x in chosen]
            picks, picked = list(chosen), team_score(bring_matrix(matrix, rows))
        mega = next((m.label for m in members if m.form.is_mega), None)
        evolves = who if mega is not None and mega in picks else None
        # a version whose Mega actually comes along beats one where it stays home; ties go to
        # the better bring overall, then to the Mega that does best against their whole team
        own = float(matrix.loc[mega].mean()) if mega is not None else 0.0
        key = (evolves is not None, round(picked, 6), round(team_score(matrix), 6), own)
        if best is None or key > best[0]:
            best = (key, evolves, matrix, picks, picked)
    _, who, matrix, picks, picked = best
    return who, matrix, picks, picked


def meta_matchups(yours, archetypes: list[Archetype], usage: UsageData, dex: Dex,
                  bring: int = 4, doubles: bool = True) -> pd.DataFrame:
    """`yours`: a member list, or analysis.mega_variants(...) to choose the Mega per opponent."""
    rows = []
    for arch in archetypes:
        theirs = opponent_members(arch.members, usage, dex)
        who, matrix, picks, picked_score = best_variant(yours, theirs, arch.trick_room, doubles,
                                                        arch.weather, bring)
        worst = matrix.max(axis=0).idxmin() if not matrix.empty else ""
        rows.append({
            "archetype": arch.name, "popularity": arch.popularity,
            "score": round(team_score(matrix), 2), "verdict": verdict(team_score(matrix)),
            "mega evolve": who or "—", f"bring {bring}": ", ".join(picks), "with bring": round(picked_score, 2),
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
            "pokemon": cand.label, "usage %": round(pct, 1), "avg matchup": round(sum(scores) / len(scores), 2),
            "beats": ", ".join(beats) or "—", "loses to": ", ".join(loses) or "—",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("avg matchup", ascending=False).head(top_n).reset_index(drop=True)


# --------------------------------------------------------------------------
# Individual threats
# --------------------------------------------------------------------------
def wins_one_on_one(mine_pct: float, theirs_pct: float, mine_speed: int, theirs_speed: int) -> bool:
    """Your Pokemon beats theirs head to head: it needs fewer hits to KO than they do, or the
    same number and it moves first. Percentages are each side's best hit on the other."""
    if mine_pct <= 0:
        return False
    need_mine = math.ceil(100 / mine_pct)
    need_theirs = math.ceil(100 / theirs_pct) if theirs_pct > 0 else 99
    return need_mine < need_theirs or (need_mine == need_theirs and mine_speed > theirs_speed)


def threat_report(members: list[Member], usage: UsageData, dex: Dex, n: int = 30,
                  doubles: bool = True) -> pd.DataFrame:
    """
    Popular Pokemon (popular sets) ranked by how much trouble they cause this team,
    using damage calcs in both directions and Speed (Choice Scarf counted):

        pressured = your Pokemon it 2HKOs (best move does >= 50% on average)
        answers   = your Pokemon that win the 1-on-1 (wins_one_on_one)
        threat    = usage % x (pressured + 1) / (answers + 1)
    """
    from src.stats import effective_speed
    rows = []
    for name, pct in usage.ranked(n):
        opp = opponent_members([name], usage, dex)
        if not opp:
            continue
        threat = opp[0]
        t_speed = effective_speed(threat.stats["spe"], threat.pset.item if threat.pset else None)
        pressured, answers, key_calcs, my_hits = [], [], [], []
        for m in members:
            dealt, dealt_move = best_attack(threat, m, doubles)
            taken, taken_move = best_attack(m, threat, doubles)
            m_speed = effective_speed(m.stats["spe"], m.pset.item if m.pset else None)
            if dealt >= 50:
                pressured.append(m.label)
                key_calcs.append((dealt, f"{dealt_move} {dealt:.0f}% to {m.label}"))
            if taken_move:
                my_hits.append((taken, f"{m.label} ({taken_move} {taken:.0f}%)"))
            if wins_one_on_one(taken, dealt, m_speed, t_speed):
                answers.append(f"{m.label} ({taken_move} {taken:.0f}%)")
        key_calcs.sort(reverse=True)
        my_hits.sort(reverse=True)
        rows.append({
            "pokemon": threat.label, "usage %": round(pct, 1),
            "2HKOs": len(pressured), "hardest hits": "; ".join(c for _, c in key_calcs[:2]) or "—",
            "answers": ", ".join(answers) or "none",
            "your best hits": ", ".join(h for _, h in my_hits[:2]) or "—",
            "threat score": round(pct * (len(pressured) + 1) / (len(answers) + 1), 1),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("threat score", ascending=False).reset_index(drop=True)
