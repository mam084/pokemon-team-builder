"""
roles.py

What a Pokemon *does* on a team, in the terms players use: "Fake Out support",
"Trick Room setter", "Rain setter", "Choice Scarf attacker"...

Roles are read from usage stats when available - a role counts if enough of
the Pokemon's sets run the move / item / ability behind it, and its strength is
that share. For a specific set on your team, the same rules run on that set's
own moves, item and ability (strength 100% when present).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.dex import Dex, to_id
from src.stats import parse_spread
from src.team import PokemonSet
from src.usage import UsageData

THRESHOLD = 30.0  # % of sets that must run something for it to count as a role


@dataclass(frozen=True)
class RoleRule:
    label: str
    moves: frozenset = frozenset()
    abilities: frozenset = frozenset()
    items: frozenset = frozenset()
    doubles_only: bool = False


RULES = [
    RoleRule("Trick Room setter", moves=frozenset({"trickroom"})),
    RoleRule("Tailwind setter", moves=frozenset({"tailwind"})),
    RoleRule("Speed control", moves=frozenset({"icywind", "electroweb", "thunderwave", "rocktomb",
                                               "bulldoze", "scaryface", "glare", "nuzzle"})),
    RoleRule("Fake Out support", moves=frozenset({"fakeout"}), doubles_only=True),
    RoleRule("Redirector", moves=frozenset({"followme", "ragepowder"}),
             abilities=frozenset({"lightningrod", "stormdrain"}), doubles_only=True),
    RoleRule("Intimidate", abilities=frozenset({"intimidate"})),
    RoleRule("Rain setter", moves=frozenset({"raindance"}), abilities=frozenset({"drizzle"})),
    RoleRule("Sun setter", moves=frozenset({"sunnyday"}), abilities=frozenset({"drought", "megasol"})),
    RoleRule("Sand setter", moves=frozenset({"sandstorm"}), abilities=frozenset({"sandstream"})),
    RoleRule("Snow setter", moves=frozenset({"snowscape"}), abilities=frozenset({"snowwarning"})),
    RoleRule("Terrain setter", moves=frozenset({"grassyterrain", "psychicterrain", "electricterrain",
                                                "mistyterrain"}),
             abilities=frozenset({"grassysurge", "psychicsurge", "electricsurge", "mistysurge"})),
    RoleRule("Wide Guard", moves=frozenset({"wideguard"}), doubles_only=True),
    RoleRule("Pivot", moves=frozenset({"uturn", "voltswitch", "partingshot", "flipturn", "teleport"})),
    RoleRule("Helping Hand support", moves=frozenset({"helpinghand"}), doubles_only=True),
    RoleRule("Screens", moves=frozenset({"reflect", "lightscreen", "auroraveil"})),
    RoleRule("Disruptor", moves=frozenset({"taunt", "encore", "spore", "sleeppowder", "yawn", "willowisp",
                                           "imprison", "disable", "perishsong"})),
    RoleRule("Healer", moves=frozenset({"lifedew", "pollenpuff", "healpulse", "junglehealing"}),
             abilities=frozenset({"hospitality"})),
    RoleRule("Setup sweeper", moves=frozenset({"swordsdance", "nastyplot", "calmmind", "bulkup",
                                               "dragondance", "quiverdance", "shellsmash", "coil",
                                               "victorydance", "tidyup", "irondefense", "geomancy"})),
    RoleRule("Choice Scarf attacker", items=frozenset({"choicescarf"})),
    RoleRule("Choice-locked attacker", items=frozenset({"choiceband", "choicespecs"})),
    RoleRule("Focus Sash lead", items=frozenset({"focussash"})),
]


@dataclass(frozen=True)
class RoleTag:
    label: str
    strength: float   # % of sets (usage) or 100 for your own set


def _priority_and_spread(move_pcts: dict[str, float], dex: Dex) -> list[RoleTag]:
    priority = spread = 0.0
    for mid, pct in move_pcts.items():
        mv = dex.moves.get(to_id(mid))
        if not mv or mv["category"] == "Status" or not mv["basePower"]:
            continue
        if mv["priority"] > 0 and mv["id"] != "fakeout":
            priority = max(priority, pct)
        if mv["spread"]:
            spread = max(spread, pct)
    tags = []
    if priority >= THRESHOLD:
        tags.append(RoleTag("Priority attacker", round(priority)))
    if spread >= 50:
        tags.append(RoleTag("Spread attacker", round(spread)))
    return tags


def _attacker_profile(move_pcts: dict[str, float], sps: dict | None, dex: Dex) -> list[RoleTag]:
    phys = spec = 0.0
    for mid, pct in move_pcts.items():
        mv = dex.moves.get(to_id(mid))
        if mv and mv["basePower"] and mv["id"] not in {"fakeout", "bodypress", "foulplay"}:
            if mv["category"] == "Physical":
                phys += pct
            elif mv["category"] == "Special":
                spec += pct
    tags = []
    if sps:
        bulk = sps["hp"] + sps["def"] + sps["spd"]
        if bulk >= 50:
            tags.append(RoleTag("Bulky", 100))
        elif sps["atk"] >= 28 or sps["spa"] >= 28:
            kind = "Physical" if sps["atk"] >= sps["spa"] else "Special"
            tags.append(RoleTag(f"{kind} attacker", 100))
    elif phys + spec >= 150:
        tags.append(RoleTag("Physical attacker" if phys >= spec else "Special attacker", 100))
    return tags


def _apply_rules(moves: dict, abilities: dict, items: dict, doubles: bool) -> list[RoleTag]:
    tags = []
    for rule in RULES:
        if rule.doubles_only and not doubles:
            continue
        strength = max(
            [moves.get(m, 0.0) for m in rule.moves]
            + [abilities.get(a, 0.0) for a in rule.abilities]
            + [items.get(i, 0.0) for i in rule.items]
            + [0.0]
        )
        if strength >= THRESHOLD:
            tags.append(RoleTag(rule.label, round(strength)))
    return tags


def meta_roles(name: str, usage: UsageData, dex: Dex, doubles: bool = True) -> list[RoleTag]:
    """Roles a meta Pokemon usually plays, strongest first. `name` is a usage entry."""
    entry = usage.entry(name)
    if entry is None:
        return []
    moves = {to_id(k): v for k, v in entry["moves"].items()}
    abilities = {to_id(k): v for k, v in entry["abilities"].items()}
    form = dex.get_species(name)
    if form is not None and form.is_mega:  # a Mega's ability is fixed
        abilities = {to_id(form.abilities[0]): 100.0}
    items = {to_id(k): v for k, v in entry["items"].items()}
    tags = _apply_rules(moves, abilities, items, doubles) + _priority_and_spread(moves, dex)
    spreads = entry.get("spreads") or {}
    sps = parse_spread(next(iter(spreads)))[1] if spreads else None
    tags.sort(key=lambda t: -t.strength)
    return tags + _attacker_profile(moves, sps, dex)


def species_roles(species: str, usage: UsageData, dex: Dex, doubles: bool = True) -> list[RoleTag]:
    """Roles for a team-sheet Pokemon, from its most used entry (e.g. its Mega)."""
    variants = usage.variants(species, dex)
    return meta_roles(variants[0], usage, dex, doubles) if variants else []


def set_roles(pset: PokemonSet, dex: Dex, doubles: bool = True) -> list[RoleTag]:
    """Roles a specific set on your team plays."""
    moves = {to_id(m): 100.0 for m in pset.moves}
    form = pset.battle_form(dex)
    abilities = {to_id(pset.battle_ability(dex)): 100.0}
    items = {to_id(pset.item): 100.0} if pset.item else {}
    tags = _apply_rules(moves, abilities, items, doubles) + _priority_and_spread(moves, dex)
    if form is not None:
        tags += _attacker_profile(moves, pset.sps if sum(pset.sps.values()) else None, dex)
    return tags


def role_text(tags: list[RoleTag], n: int = 3, show_pct: bool = False) -> str:
    if not tags:
        return "—"
    return " · ".join(f"{t.label} ({t.strength:.0f}%)" if show_pct and t.strength < 100 else t.label
                      for t in tags[:n])


# ---- broad jobs, for like-for-like swaps ----------------------------------------------------

SUPPORT_LABELS = {"Tailwind setter", "Trick Room setter", "Speed control", "Fake Out support", "Redirector",
                  "Intimidate", "Wide Guard", "Helping Hand support", "Screens", "Disruptor", "Healer", "Bulky"}
ATTACK_LABELS = {"Setup sweeper", "Choice Scarf attacker", "Choice-locked attacker", "Spread attacker",
                 "Priority attacker", "Physical attacker", "Special attacker"}
# Roles a team is built around: losing the only one breaks the plan, so a swap must keep it.
PLAN_LABELS = {"Rain setter", "Sun setter", "Sand setter", "Snow setter", "Terrain setter", "Trick Room setter"}


def job(tags: list[RoleTag]) -> str:
    """'Support', 'Attacker' or 'Hybrid', by which kind of role the set has more of."""
    labels = {t.label for t in tags}
    support, attack = len(labels & SUPPORT_LABELS), len(labels & ATTACK_LABELS)
    if support > attack:
        return "Support"
    if attack > support:
        return "Attacker"
    return "Hybrid"


def plan_roles(tags: list[RoleTag]) -> set[str]:
    return {t.label for t in tags} & PLAN_LABELS
