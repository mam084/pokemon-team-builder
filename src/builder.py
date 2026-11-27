"""
builder.py

Build a whole team around one Pokemon.

Starting from the core Pokemon (its popular set, or the set you made), the
builder adds one Pokemon at a time: whichever the recommender ranks highest
for the team so far, using that Pokemon's popular set with an item that keeps
Item Clause (up to two Mega Stones - you choose which Mega Evolves each game). To give real
alternatives rather than three near-copies, the second Pokemon differs per
team: the best pick overall, then the best setter of each game plan the core
already benefits from (a sand setter for Garganacl, Trick Room for slow
attackers), then the next best picks. After that each team is filled greedily.

The finished teams are then ordered by src/team_rating.py: teammate fit plus the learned win
chance against the meta teams, the combination that tracked real tournament results best
(scripts/app_vs_results.py). Without that model, by the damage-calc score vs the meta.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from src.analysis import build_members, mega_variants
from src.dex import Dex, to_id
from src.recommend import recommend
from src.team import MAX_MEGAS, PokemonSet
from src.sheet_sets import apply as sheet_apply
from src.usage import UsageData

TEAM_SIZE = 6
# Popular sets are their top four moves, but a pick can be credited for any move on 25%+ of its
# sets. Swapping the credited move in (carry_credited) made sets *less* like what tournament players
# ran (held-out week: -0.37 matching moves per changed set, 95% -0.41 to -0.33; only 27% of swapped-in
# moves were real; labs/set_fit_lab.py), so it's off: sets stay as players run them, and the
# reason line drops any claim the set doesn't carry (honest_reason).
CARRY_CREDITED = False
# Moves and nature from real team sheets when there are enough (src/sheet_sets.apply). Held-out week:
# sets closer to what players ran (labs/sheet_set_lab.py); built teams lean toward winners the same
# (+0.001) and score higher, 53.0 -> 55.7 (Popular), 21.9 -> 22.8 (Neutral) (labs/threat_builder_lab.py).
SHEET_SETS = True
CARRY_KEEPS_PROTECT = True


@dataclass
class BuiltTeam:
    sets: list[PokemonSet]
    reasons: list[str] = field(default_factory=list)   # why each added Pokemon was picked
    meta_score: float | None = None
    rating: float | None = None                        # src.team_rating combined z-score
    chance: float | None = None                        # learned win chance vs the meta
    percentile: float | None = None                    # share of tournament teams it rates above
    theme: str = ""                                    # e.g. "Sand" when seeded by a sand setter


def _set_for(name: str, team: list[PokemonSet], dex: Dex, usage: UsageData) -> PokemonSet | None:
    """Popular set (item by Item Clause), with the moves and nature real team sheets run most."""
    taken = {p.item for p in team if p.item}
    megas = sum(p.is_mega(dex) for p in team)
    pset = usage.popular_set(name, dex, taken_items=taken, allow_mega=megas < MAX_MEGAS, team=team)
    if pset is None or not SHEET_SETS:
        return pset
    return sheet_apply(pset, dex, getattr(usage, "sheet_sets", None))


def core_set(name: str, dex: Dex, usage: UsageData) -> PokemonSet | None:
    """The set the builder starts a core with (also what the core report shows)."""
    return _set_for(name, [], dex, usage)


# Items that forbid status moves: a credited status move (Tailwind, Follow Me) can't go on these.
_NO_STATUS = {"choicescarf", "choiceband", "choicespecs", "assaultvest"}
_PROTECT = {"protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap", "burningbulwark"}


def carry_credited(pset: PokemonSet, credited, usage: UsageData, dex: Dex,
                   keep_protect: bool = CARRY_KEEPS_PROTECT) -> tuple[PokemonSet, list[str]]:
    """
    Make the added set carry what the pick was credited for. A Pokemon earns credit for Tailwind or
    Pivoting from any move on 25%+ of its sets, but its popular set is only the top four moves, so
    Corviknight could join "for its Tailwind" without Tailwind. For each credited claim the set lacks,
    swap in its most-used delivering move for the least-used move no claim needs. Returns the set and
    the claims it still can't carry (a Choice item forbids the status move), which the reason drops.
    """
    form = pset.battle_form(dex)
    pct = {to_id(m): v for m, v in usage.section(form.name if form else pset.species, "moves").items()}
    if not pct:
        pct = {to_id(m): v for m, v in usage.section(pset.species, "moves").items()}
    moves = list(pset.moves)
    no_status = to_id(pset.item or "") in _NO_STATUS
    unmet = []
    for label, options in credited:
        have = {to_id(m) for m in moves}
        if have & options:
            continue
        usable = [m for m in options if m in dex.moves and dex.can_learn(dex.get_species(pset.species).id, m)
                  and not (no_status and dex.moves[m]["category"] == "Status")]
        if not usable:
            unmet.append(label)
            continue
        add = max(usable, key=lambda m: pct.get(m, 0))
        needed = set().union(*(o for _, o in credited))
        droppable = [m for m in moves if to_id(m) not in needed]
        if keep_protect and any(to_id(m) not in _PROTECT for m in droppable):
            droppable = [m for m in droppable if to_id(m) not in _PROTECT]
        if len(moves) < 4:
            moves.append(dex.moves[add]["name"])
        elif droppable:
            drop = min(droppable, key=lambda m: pct.get(to_id(m), 0))
            moves[moves.index(drop)] = dex.moves[add]["name"]
        else:
            unmet.append(label)
    out = PokemonSet.from_dict(pset.to_dict())
    out.moves = moves
    return out, unmet


def honest_reason(why: str, unmet: list[str]) -> str:
    """Drop claims the added set doesn't carry from a recommendation's reason line."""
    if not unmet:
        return why
    parts = []
    for part in why.split("; "):
        if any(part.startswith(f"its {u} helps") for u in unmet):
            continue
        if part.startswith("adds "):
            kept = [x for x in part[5:].split(", ") if x not in unmet]
            if not kept:
                continue
            part = "adds " + ", ".join(kept)
        parts.append(part)
    return "; ".join(parts) or "solid all-round pick"


# The core's pairings count twice while filling, so a team built around a rarely used Pokemon keeps
# pairing with it instead of with its popular teammates (picks pairing with the core: 86-91% -> 93-96%).
# Held-out (labs/builder_lab.py): no loss; a gain toward winning teams (+0.047, 95% -0.003 to
# +0.102) that didn't quite clear zero. On by choice, for building around the core you picked.
ANCHOR_WEIGHT = 2.0


# Answering the core's threats (the meta Pokemon that beat the core one-on-one, src/core_report.py):
# among the recommender's top picks, each gets THREAT_WEIGHT score points (of 100) times the
# usage-weighted share of the core's still-unanswered threats it beats. Held-out week
# (labs/threat_builder_lab.py, 55 cores): built teams already answer 93-95% of the core's threats;
# at 10 points, 99%, but the lean toward winning teams moved +0.066 (95% -0.003 to +0.136) in Popular
# and +0.003 (-0.050 to +0.058) in Neutral, and team scores fell slightly. Not clear of zero: off.
THREAT_WEIGHT = 0.0


# Ladder edge: how much more each Pokemon wins than its players' ratings predict, on the last 30 days of
# rated replays (src/core_report.replay_index: won - expected over brought games, shrunk toward 0 by
# EDGE_PRIOR games). Among the recommender's top picks, each gets EDGE_WEIGHT score points per point of
# edge. Held-out week (labs/offmeta_lab.py --edge, edges from the 30 days before it): slope of
# wins-above-ratings on Pokemon shared with the builder's teams, Popular -0.39 / +0.10 at weight 2 / +0.19 at
# 5; Neutral -0.42 / -0.11 / +0.16; Hidden gems +1.65 / +2.19 / +1.65. Every change inside the noise, and
# the bonus pulls teams away from what players pair with the core. Off.
EDGE_WEIGHT = 0.0
EDGE_PRIOR = 100


# Variety across the three teams: when filling a later team, a pick loses DIVERSITY_WEIGHT score points
# (of 100) for each earlier team that already has it. Held-out week (labs/diversity_lab.py, 50 cores):
# different partners across the three teams 9.6 -> 13.1 (of 15, Popular, weight 10), but lean toward
# winning teams Popular +0.011 (95% -0.044 to +0.068), Neutral +0.020 (-0.017 to +0.064; +0.029 at 5,
# -0.004 to +0.072), and Hidden gems worse on paper at every weight (-0.34 points at 10, -0.68 to -0.01).
# More variety, no tested gain: off.
DIVERSITY_WEIGHT = 0.0


# One speed plan per team: once a team has a Trick Room setter, skip picks that set Tailwind, and the
# other way round (a core that sets both keeps both). Before, ~23% of built teams set both (10.5% of
# real tournament teams do, winning 47.9% of games vs 48.3-50.2% for one plan). Held-out week
# (labs/speed_mode_lab.py, 50 cores), one plan vs mixing, paired: lean toward winning teams Popular
# +0.002 (95% -0.028 to +0.034), Neutral +0.003 (-0.034 to +0.033), Hidden gems +0.014 (+0.000 to
# +0.031); learned win chance vs the meta +0.12 / +0.21 / +0.26 points (Hidden gems clear of zero,
# the others just touching it). Never worse, better where it shows: on.
NO_MIXED_SPEED = True
SPEED_MOVES = {"trickroom": "Trick Room", "tailwind": "Tailwind"}


def speed_modes(pset: PokemonSet) -> set[str]:
    """The speed plans this set can start ({"Trick Room", "Tailwind"} or a part of it)."""
    have = {to_id(m) for m in pset.moves}
    return {label for move, label in SPEED_MOVES.items() if move in have}


def mixes_speed(pset: PokemonSet, team: list[PokemonSet]) -> bool:
    """True when adding pset would give a one-plan team a second, opposite speed plan."""
    if not NO_MIXED_SPEED:
        return False
    have = set().union(*(speed_modes(p) for p in team)) if team else set()
    return len(have) == 1 and bool(speed_modes(pset) - have)


def edges_from(index: dict | None) -> dict[str, float]:
    """{sheet id: win-chance edge in points} from a core index (src/core_report.replay_index)."""
    out = {}
    for root, row in ((index or {}).get("pokemon") or {}).items():
        n = row.get("rated", 0)
        if n:
            out[root] = 100 * (row["rated_won"] - row["rated_expected"]) / (n + EDGE_PRIOR)
    return out


def _edge(pset: PokemonSet, dex: Dex, usage: UsageData) -> float:
    edges = getattr(usage, "edges", None)
    if not edges or not EDGE_WEIGHT:
        return 0.0
    s = dex.get_species(pset.species)
    return edges.get(dex.sheet_id(s), 0.0) if s is not None else 0.0


def _threats(core: PokemonSet, dex: Dex, usage: UsageData, doubles: bool) -> list[tuple]:
    """[(name, usage %, battle Member)] for the meta Pokemon that beat the core one-on-one."""
    from src.core_report import core_matchups
    from src.matchup import opponent_members
    out = []
    for name, _ in core_matchups(core, usage, dex, doubles=doubles)["threats"]:
        opp = opponent_members([name], usage, dex)
        if opp:
            out.append((name, usage.usage(name), opp[0]))
    return out


def _beats(pset: PokemonSet, threat, dex: Dex, doubles: bool) -> bool:
    from src.core_report import wins_against
    members = build_members([pset], dex)
    return any(wins_against(m, threat, doubles) for m in members)


def _complete(team: list[PokemonSet], reasons: list[str], dex: Dex, usage: UsageData, doubles: bool,
              mode: str, weights: dict | None, used: dict | None = None) -> None:
    threats = _threats(team[0], dex, usage, doubles) if THREAT_WEIGHT > 0 else []
    while len(team) < TEAM_SIZE:
        recs = recommend(build_members(team, dex), dex, usage, doubles=doubles, weights=weights,
                         top_n=15, mode=mode, anchor=team[0].species, anchor_weight=ANCHOR_WEIGHT)
        open_ = [t for t in threats if not any(_beats(p, t[2], dex, doubles) for p in team)]
        total = sum(w for _, w, _ in open_) or 1.0
        best, fallback = None, None
        for _, row in recs.iterrows():
            pset = _set_for(row["pokemon"], team, dex, usage)
            if pset is None or to_id(pset.species) in {to_id(p.species) for p in team}:
                continue
            if mixes_speed(pset, team):
                fallback = fallback or (row["score"], pset, row, [])
                continue
            hit = [n for n, w, t in open_ if _beats(pset, t, dex, doubles)] if open_ else []
            score = row["score"] + THREAT_WEIGHT * sum(w for n, w, _ in open_ if n in hit) / total \
                + EDGE_WEIGHT * _edge(pset, dex, usage) - DIVERSITY_WEIGHT * (used or {}).get(to_id(pset.species), 0)
            if best is None or score > best[0]:
                best = (score, pset, row, hit)
            if not open_ and not EDGE_WEIGHT and not (DIVERSITY_WEIGHT and used):
                break   # no bonus to weigh: the recommender's order stands
        best = best or fallback   # every top pick mixes plans: take the best of them over a short team
        if best is None:
            break
        _, pset, row, hit = best
        pset, why = _carry(pset, row, dex, usage)
        if hit:
            why = f"beats {', '.join(hit[:3])}, which beat {team[0].species}; " + why
        team.append(pset)
        reasons.append(f"{pset.species}: {why}")


def uncarried(pset: PokemonSet, credited) -> list[str]:
    """Credited claims (Tailwind, Pivoting...) none of whose moves are on the set."""
    have = {to_id(m) for m in pset.moves}
    return [label for label, options in credited if not have & options]


def _carry(pset: PokemonSet, row, dex: Dex, usage: UsageData) -> tuple[PokemonSet, str]:
    credited = row.get("credited") or []
    if CARRY_CREDITED:
        pset, unmet = carry_credited(pset, credited, usage, dex)
    else:
        unmet = uncarried(pset, credited)
    return pset, honest_reason(row["why"], unmet)


# In Neutral, the last of the teams is built the Hidden gems way (unlabelled; all three are ranked together).
# Hidden gems picks were the ones that beat their players' ratings on held-out ladder games
# (labs/offmeta_lab.py). The mix (--gems there): Neutral slope -0.45 with or without it, so no harm.
NEUTRAL_GEMS = 1


def build_teams(core: PokemonSet | str, dex: Dex, usage: UsageData, doubles: bool = True,
                mode: str = "popular", weights: dict | None = None, alternatives: int = 3,
                archetypes=None, regulation: str | None = None, gems: bool = True) -> list[BuiltTeam]:
    if isinstance(core, str):
        core = core_set(core, dex, usage)
        if core is None:
            return []
    gems = min(NEUTRAL_GEMS, alternatives - 1) if (mode == "neutral" and gems) else 0
    if gems:
        # the Neutral build's own first teams (in seed order, before rating), then the gems in place of the rest
        teams = build_teams(core, dex, usage, doubles, mode, weights, alternatives, gems=False)[:alternatives - gems]
        species = [{to_id(p.species) for p in t.sets} for t in teams]
        for t in build_teams(core, dex, usage, doubles, "hidden", weights, alternatives):
            if len(teams) >= alternatives:
                break
            if {to_id(p.species) for p in t.sets} not in species:
                teams.append(t)
                species.append({to_id(p.species) for p in t.sets})
        return _order(teams, dex, usage, doubles, archetypes, regulation)
    first = recommend(build_members([core], dex), dex, usage, doubles=doubles, weights=weights,
                      top_n=None, mode=mode).reset_index(drop=True)
    if first.empty:
        return []
    # seeds: best overall, then the best starter of each plan the core benefits from, then the rest
    seeds = [0]
    starters = first[(first["starts"] != "") & (first["plan"] >= 0.3)]
    for plan_label, group in starters.groupby("starts", sort=False):
        if len(seeds) < alternatives and plan_label != first.iloc[0]["starts"]:
            seeds.append(int(group.index[0]))
    seeds = sorted(set(seeds), key=seeds.index)
    seeds += [i for i in range(min(len(first), alternatives * 3)) if i not in seeds]
    teams: list[BuiltTeam] = []
    for i in seeds:
        if len(teams) >= alternatives:
            break
        row = first.iloc[i]
        second = _set_for(row["pokemon"], [core], dex, usage)
        if second is None or mixes_speed(second, [core]):
            continue
        second, why = _carry(second, row, dex, usage)
        theme = row["starts"] if row["starts"] and f"its {row['starts']} helps" in why else ""
        built = BuiltTeam([core, second], [f"{second.species}: {why}"], theme=theme)
        used = Counter(to_id(p.species) for t in teams for p in t.sets[1:])
        _complete(built.sets, built.reasons, dex, usage, doubles, mode, weights, used)
        if len(built.sets) == TEAM_SIZE and all(
            {to_id(p.species) for p in built.sets} != {to_id(p.species) for p in t.sets} for t in teams
        ):
            teams.append(built)
    return _order(teams, dex, usage, doubles, archetypes, regulation)


def _order(teams: list[BuiltTeam], dex: Dex, usage: UsageData, doubles: bool, archetypes, regulation) -> list[BuiltTeam]:
    """Rate and order the built teams (the tested team rating, else the matchup score)."""
    if archetypes and regulation and _rate(teams, dex, usage, archetypes, regulation):
        return teams
    if archetypes:
        from src.matchup import meta_matchups
        for t in teams:
            table = meta_matchups(mega_variants(t.sets, dex), archetypes, usage, dex, doubles=doubles)
            w = table["popularity"]
            t.meta_score = float((table["score"] * w).sum() / w.sum()) if len(table) else 0.0
        teams.sort(key=lambda t: -(t.meta_score or 0))
    return teams


def _rate(teams: list[BuiltTeam], dex: Dex, usage: UsageData, archetypes, regulation: str) -> bool:
    """Order by the tested team rating; False when its models aren't available."""
    from src import team_rating as R
    from src.match_model import load_model
    ref, model = R.load_reference(regulation), load_model(regulation)
    if ref is None or model is None or usage.teammates is None:
        return False
    sides, weights = R.meta_sides(archetypes, usage, dex)
    for t in teams:
        fit = R.teammate_fit(t.sets, dex, usage.teammates)
        if fit is None:
            return False
        t.chance = R.learned_vs_meta(t.sets, dex, usage, model, sides, weights)
        t.rating = R.combined(fit, t.chance, ref)
        t.percentile = R.percentile(t.rating, ref)
    teams.sort(key=lambda t: -t.rating)
    return True
