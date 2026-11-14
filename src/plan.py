"""
plan.py

The team's *game plan* - weather, Trick Room, Tailwind, terrain - and how well
a candidate Pokemon plays into it.

Teammate statistics only say who appears together. They can't tell that Snow
Warning makes Ice types 50% bulkier on the physical side, makes Blizzard never
miss and enables Aurora Veil, so a Mega Froslass team gets the meta's usual
partners instead of Pokemon that use the snow. This module scores that fit
directly from the rules:

    plan       what turns it on                    who benefits
    snow       Snow Warning, Snowscape             Ice types, Slush Rush, Ice Body,
                                                   Snow Cloak, Blizzard, Aurora Veil
    sun        Drought, Sunny Day                  Fire attackers, Chlorophyll, Solar
                                                   Power, Solar Beam/Blade, Weather Ball
    rain       Drizzle, Rain Dance                 Water attackers, Swift Swim,
                                                   Thunder / Hurricane / Electro Shot
    sand       Sand Stream, Sandstorm              Rock types (+50% SpD), Sand Rush,
                                                   Sand Force, Ground / Steel (no chip)
    trickroom  Trick Room                          slow Pokemon (base Speed <= 60)
    tailwind   Tailwind                            mid-speed attackers (base 60-100)
    terrain    Psychic / Grassy / Electric Surge   grounded attackers of that type,
                                                   Expanding Force, Grassy Glide...

It also works backwards: a team of Swift Swimmers with no rain setter rates a
rain setter highly.

Weather and terrain set by a *move* only count as a plan when someone on the
team uses them. Prankster Rain Dance on Sableye is usually weather control -
overwriting the opponent's sun or snow - not the start of a rain team, so on
its own it shouldn't pull Swift Swimmers into the suggestions. Weather from an
ability (Drizzle, Sand Stream...) is always up, so it always counts.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.dex import Dex, Species, to_id

SETTERS = {
    "snow": ({"snowwarning"}, {"snowscape", "chillyreception"}),
    "sun": ({"drought"}, {"sunnyday"}),
    "rain": ({"drizzle"}, {"raindance"}),
    "sand": ({"sandstream"}, {"sandstorm"}),
    "trickroom": (set(), {"trickroom"}),
    "tailwind": (set(), {"tailwind"}),
    "psychicterrain": ({"psychicsurge"}, {"psychicterrain"}),
    "grassyterrain": ({"grassysurge"}, {"grassyterrain"}),
    "electricterrain": ({"electricsurge"}, {"electricterrain"}),
}
LABELS = {
    "snow": "Snow", "sun": "Sun", "rain": "Rain", "sand": "Sand", "trickroom": "Trick Room",
    "tailwind": "Tailwind", "psychicterrain": "Psychic Terrain", "grassyterrain": "Grassy Terrain",
    "electricterrain": "Electric Terrain",
}
# abilities that need a plan someone else has to set up
NEEDS = {
    "slushrush": "snow", "icebody": "snow", "snowcloak": "snow",
    "chlorophyll": "sun", "solarpower": "sun", "harvest": "sun", "leafguard": "sun",
    "swiftswim": "rain", "raindish": "rain", "hydration": "rain", "dryskin": "rain",
    "sandrush": "sand", "sandforce": "sand", "sandveil": "sand",
}
SLOW, FAST = 60, 100
# Plans that are a move by nature: setting them is the point, users or not.
MOVE_PLANS = {"trickroom", "tailwind"}


@dataclass
class Plan:
    key: str
    label: str
    setters: list[str]       # members that turn it on
    needed: bool = False     # True when members need it but nobody sets it
    by_ability: bool = False  # at least one setter turns it on with its ability


@dataclass
class Profile:
    """What a Pokemon brings, as far as plans are concerned."""
    form: Species
    abilities: set[str]      # ids
    moves: set[str]          # ids it commonly runs (or could run)
    attack_types: set[str]   # types of its damaging moves


def team_plans(members, dex: Dex) -> list[Plan]:
    """Plans the current members set up - or need someone to set up."""
    plans: dict[str, Plan] = {}
    for m in members:
        move_ids = {mv["id"] for mv in m.moves}
        for key, (abilities, moves) in SETTERS.items():
            if m.ability_id in abilities or move_ids & moves:
                plan = plans.setdefault(key, Plan(key, LABELS[key], []))
                plan.setters.append(m.label)
                plan.by_ability = plan.by_ability or m.ability_id in abilities
    # A weather or terrain move with nobody using it is weather control, not a plan.
    for key in [k for k, p in plans.items() if k not in MOVE_PLANS and not p.by_ability]:
        if plan_users(members, plans[key], dex) == 0:
            del plans[key]
    # Abusers with no setter: the team *needs* that plan.
    for m in members:
        need = NEEDS.get(m.ability_id)
        if need and need not in plans:
            plans[need] = Plan(need, LABELS[need], [], needed=True)
    slow = [m for m in members if m.form.base_stats["spe"] <= 50]
    if len(slow) >= 3 and "trickroom" not in plans:
        plans["trickroom"] = Plan("trickroom", LABELS["trickroom"], [], needed=True)
    return list(plans.values())


def _attacks_with(p: Profile, mtype: str) -> bool:
    return mtype in p.attack_types


def fit(profile: Profile, plan: Plan) -> tuple[float, str]:
    """How well a candidate plays into one plan: (0-1, short reason)."""
    p, key = profile, plan.key
    types = set(p.form.types)
    spe = p.form.base_stats["spe"]
    abilities, moves = p.abilities, p.moves
    score, why = 0.0, []

    setter_abilities, setter_moves = SETTERS[key]
    if plan.needed and (abilities & setter_abilities or moves & setter_moves):
        return 1.0, f"sets the {plan.label} your team needs"

    if key == "snow":
        if "Ice" in types:
            score += 0.5
            why.append("Ice type (bulkier in snow)")
        if "slushrush" in abilities:
            score += 0.6
            why.append("Slush Rush")
        if abilities & {"icebody", "snowcloak"}:
            score += 0.2
        if "blizzard" in moves:
            score += 0.3
            why.append("Blizzard")
        if "auroraveil" in moves:
            score += 0.3
            why.append("Aurora Veil")
    elif key == "sun":
        if _attacks_with(p, "Fire"):
            score += 0.5
            why.append("Fire attacks")
        if abilities & {"chlorophyll", "solarpower"}:
            score += 0.6
            why.append("Chlorophyll" if "chlorophyll" in abilities else "Solar Power")
        if moves & {"solarbeam", "solarblade", "weatherball"}:
            score += 0.3
        if _attacks_with(p, "Water") and not _attacks_with(p, "Fire"):
            score -= 0.3
    elif key == "rain":
        if _attacks_with(p, "Water"):
            score += 0.5
            why.append("Water attacks")
        if "swiftswim" in abilities:
            score += 0.6
            why.append("Swift Swim")
        if moves & {"thunder", "hurricane", "electroshot", "weatherball"}:
            score += 0.4
            why.append("rain-boosted moves")
        if _attacks_with(p, "Fire") and not _attacks_with(p, "Water"):
            score -= 0.3
    elif key == "sand":
        if "Rock" in types:
            score += 0.6
            why.append("Rock type (+50% SpD in sand)")
        if types & {"Ground", "Steel"}:
            score += 0.2
        if abilities & {"sandrush", "sandforce"}:
            score += 0.6
            why.append("Sand Rush" if "sandrush" in abilities else "Sand Force")
    elif key == "trickroom":
        if spe <= 50:
            score += 1.0
        elif spe <= SLOW:
            score += 0.5
        elif spe >= FAST:
            score -= 0.5
        if score > 0 and not p.attack_types:  # a slow wall barely needs to move first
            score *= 0.4
        if score > 0:
            why.append(f"slow (base {spe} Speed)")
    elif key == "tailwind":
        if SLOW < spe <= FAST and p.attack_types:
            score += 0.6
            why.append(f"base {spe} Speed doubles to outspeed")
        elif spe <= 50:
            score -= 0.3
    elif key.endswith("terrain"):
        ttype = {"psychicterrain": "Psychic", "grassyterrain": "Grass", "electricterrain": "Electric"}[key]
        grounded = "Flying" not in types and "levitate" not in abilities
        if grounded and _attacks_with(p, ttype):
            score += 0.5
            why.append(f"boosted {ttype} attacks")
        if moves & {"expandingforce", "grassyglide", "risingvoltage"}:
            score += 0.4
    return max(0.0, min(1.0, score)), ", ".join(why[:2])


# Diminishing returns: the more members already play into a plan, the less another
# one adds (and five Ice types share five weaknesses). Factor by existing users.
SATURATION = {0: 1.0, 1: 1.0, 2: 0.6, 3: 0.3}


def plan_users(members, plan: Plan, dex: Dex) -> int:
    """Members that already benefit from a plan (fit >= 0.5), not counting pure setters."""
    count = 0
    for m in members:
        prof = member_profile(m, dex)
        if fit(prof, Plan(plan.key, plan.label, plan.setters))[0] >= 0.5:
            count += 1
    return count


def plan_score(profile: Profile, plans: list[Plan], members=None, dex: Dex | None = None) -> tuple[float, str]:
    """Mean fit across the team's plans (with diminishing returns), plus the reason from the best one."""
    if not plans:
        return 0.0, ""
    fits = []
    for plan in plans:
        value, why = fit(profile, plan)
        if members is not None and dex is not None and not why.startswith("sets the"):
            value *= SATURATION.get(plan_users(members, plan, dex), 0.15)
        fits.append(((value, why), plan))
    mean = sum(f for (f, _), _ in fits) / len(fits)
    (best, why), plan = max(fits, key=lambda x: x[0][0])
    if best <= 0 or not why:
        return mean, ""
    reason = why if why.startswith("sets the") else f"plays into your {plan.label}: {why}"
    return mean, reason


def member_profile(m, dex: Dex) -> Profile:
    return profile_from(m.form, {m.ability_id}, {mv["id"] for mv in m.moves}, dex)


def enabler_score(profile: Profile, members, plans: list[Plan], dex: Dex) -> tuple[float, str, str]:
    """
    Credit for *starting* a plan the team doesn't run yet but already benefits
    from: a sand setter next to Garganacl (Rock types get +50% Special Defense
    in sand), Trick Room next to slow attackers. Worth 80% of the best fit.
    Returns (score, reason, the plan's label).
    """
    present = {p.key for p in plans if not p.needed}
    best, why, label_out = 0.0, "", ""
    profiles = [(m.label, member_profile(m, dex)) for m in members]
    for key, (abilities, moves) in SETTERS.items():
        if key in present or not (profile.abilities & abilities or profile.moves & moves):
            continue
        plan = Plan(key, LABELS[key], [])
        for label, prof in profiles:
            value = 0.8 * fit(prof, plan)[0]
            if value > best:
                best, why, label_out = value, f"its {LABELS[key]} helps your {label}", LABELS[key]
    return best, why, label_out


def profile_from(form: Species, abilities, moves, dex: Dex) -> Profile:
    move_ids = {to_id(m) for m in moves}
    attack_types = {dex.moves[m]["type"] for m in move_ids
                    if m in dex.moves and dex.moves[m]["category"] != "Status" and (dex.moves[m]["basePower"] or 0) >= 50}
    return Profile(form, {to_id(a) for a in abilities}, move_ids, attack_types)
