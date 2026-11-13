"""
analysis.py

Everything the app reports about a team:

- defense:  how each type hits each member (with Megas and type-relevant
            abilities like Levitate or Purifying Salt applied)
- offense:  what the team's actual moves hit super effectively, by type and
            against the Pokemon people are really using
- roles:    a checklist of jobs a Champions team usually wants covered
            (Fake Out, speed control, redirection, Intimidate...)
- speed:    real level-50 Speed stats next to the meta's common benchmarks

Team-vs-meta matchups and threats (with damage calcs) live in matchup.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.dex import Dex, Species, to_id
from src.stats import calc_stat, parse_spread
from src.team import PokemonSet
from src.type_chart import ALL_TYPES, ability_defensive_multiplier
from src.usage import UsageData


# --------------------------------------------------------------------------
# A team member as the battle sees it
# --------------------------------------------------------------------------
@dataclass
class Member:
    label: str
    form: Species
    types: list[str]          # lowercase, for the type chart
    ability_id: str
    stats: dict
    moves: list[dict]         # move records from the dex
    pset: PokemonSet | None = None
    battler: object = None    # src.damage.Battler, for damage calcs

    @property
    def damaging_moves(self) -> list[dict]:
        return [m for m in self.moves if m["category"] != "Status" and (m["basePower"] or 0) > 0]


def build_members(team: list[PokemonSet], dex: Dex) -> list[Member]:
    from src.damage import Battler  # local import: damage imports nothing from here, but keep it light

    members = []
    for pset in team:
        form = pset.battle_form(dex)
        if form is None:
            continue
        label = form.name if form.is_mega else (pset.nickname or form.name)
        members.append(Member(
            label=label,
            form=form,
            types=[t.lower() for t in form.types],
            ability_id=to_id(pset.battle_ability(dex)),
            stats=pset.stats(dex),
            moves=[dex.moves[to_id(m)] for m in pset.moves if to_id(m) in dex.moves],
            pset=pset,
            battler=Battler.from_set(pset, dex),
        ))
    return members


# --------------------------------------------------------------------------
# Defense
# --------------------------------------------------------------------------
def defense_matrix(members: list[Member]) -> pd.DataFrame:
    """Rows: attacking type. Columns: team member. Values: damage multiplier."""
    data = {
        m.label: [ability_defensive_multiplier(m.types, t, m.ability_id) for t in ALL_TYPES]
        for m in members
    }
    return pd.DataFrame(data, index=[t.title() for t in ALL_TYPES])


def defense_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    """Per attacking type: how many members are weak / resist / immune, plus a verdict."""
    rows = []
    for atk_type, values in matrix.iterrows():
        weak = int((values > 1).sum())
        resist = int(((values < 1) & (values > 0)).sum())
        immune = int((values == 0).sum())
        quad = int((values >= 4).sum())
        if weak >= 3 and resist + immune <= 1:
            verdict = "Major weakness"
        elif weak >= 2 and resist + immune == 0:
            verdict = "Shared weakness"
        elif weak > resist + immune:
            verdict = "Leaning weak"
        else:
            verdict = ""
        rows.append({"type": atk_type, "weak": weak, "4x": quad, "resist": resist,
                     "immune": immune, "verdict": verdict})
    return pd.DataFrame(rows).set_index("type")


# --------------------------------------------------------------------------
# Offense
# --------------------------------------------------------------------------
def _best_hit(members: list[Member], defending_types: list[str], ability_id: str = "") -> tuple[float, list[str]]:
    best, hitters = 0.0, []
    for m in members:
        for mv in m.damaging_moves:
            mult = ability_defensive_multiplier(defending_types, mv["type"].lower(), ability_id)
            if mult > best:
                best, hitters = mult, [f"{m.label} ({mv['name']})"]
            elif mult == best and mult > 1:
                hitters.append(f"{m.label} ({mv['name']})")
    return best, hitters


def offense_by_type(members: list[Member]) -> pd.DataFrame:
    """Best multiplier the team's moves get against each single defending type."""
    rows = []
    for t in ALL_TYPES:
        best, hitters = _best_hit(members, [t])
        rows.append({"type": t.title(), "best": best, "hit_by": ", ".join(hitters[:4])})
    return pd.DataFrame(rows).set_index("type")


def meta_form(name: str, usage: UsageData, dex: Dex) -> tuple[Species | None, str]:
    """A meta Pokemon's battle form and ability, assuming its most common item."""
    item = usage.common_item(name, dex)
    form = dex.battle_form(name, item)
    if form is None:
        return None, ""
    if form.is_mega:
        return form, to_id(form.abilities[0])
    abilities = usage.section(name, "abilities")
    ability = next(iter(abilities), form.abilities[0])
    return form, to_id(ability)


def coverage_vs_meta(members: list[Member], dex: Dex, usage: UsageData, n: int = 30) -> pd.DataFrame:
    rows = []
    for name, pct in usage.ranked(n):
        form, ability = meta_form(name, usage, dex)
        if form is None:
            continue
        best, hitters = _best_hit(members, [t.lower() for t in form.types], ability)
        rows.append({
            "pokemon": form.name, "usage %": pct, "types": "/".join(form.types),
            "best hit": best, "super effective from": ", ".join(hitters[:3]) or "—",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Role:
    key: str
    label: str
    why: str
    moves: frozenset = frozenset()
    abilities: frozenset = frozenset()
    doubles_only: bool = False
    essential: bool = False


ROLES = [
    Role("speed", "Speed control", "Tailwind, Trick Room or speed drops decide who moves first.",
         frozenset({"tailwind", "trickroom", "icywind", "electroweb", "thunderwave", "rocktomb",
                    "bulldoze", "scaryface", "stringshot", "glare", "nuzzle"}), essential=True),
    Role("fakeout", "Fake Out", "Free turns to set up or stop a threat.",
         frozenset({"fakeout"}), doubles_only=True, essential=True),
    Role("protect", "Protect on most members", "Doubles revolves around scouting and stalling with Protect.",
         frozenset({"protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap",
                    "burningbulwark"}), doubles_only=True),
    Role("intimidate", "Intimidate / Attack drops", "Blunts physical attackers.",
         frozenset({"partingshot", "willowisp", "snarl", "nobleroar", "charm"}),
         frozenset({"intimidate"})),
    Role("redirect", "Redirection", "Follow Me / Rage Powder pull attacks off a setup partner.",
         frozenset({"followme", "ragepowder", "allyswitch"}),
         frozenset({"lightningrod", "stormdrain"}), doubles_only=True),
    Role("guard", "Wide / Quick Guard", "Blocks spread moves or priority for the whole side.",
         frozenset({"wideguard", "quickguard"}), doubles_only=True),
    Role("pivot", "Pivoting", "U-turn / Parting Shot reposition and reuse Fake Out or Intimidate.",
         frozenset({"uturn", "voltswitch", "partingshot", "flipturn", "teleport", "chillyreception"})),
    Role("spread", "Spread damage", "Hitting both foes at once pressures double Protects.",
         doubles_only=True),
    Role("setup", "Setup / win condition", "A boosting move that can snowball a game.",
         frozenset({"swordsdance", "nastyplot", "calmmind", "bulkup", "dragondance", "irondefense",
                    "quiverdance", "shellsmash", "coil", "growth", "geomancy", "victorydance",
                    "tidyup", "curse", "workup", "rockpolish", "agility"})),
    Role("field", "Weather / terrain", "Sets the conditions your team plays around.",
         frozenset({"sunnyday", "raindance", "sandstorm", "snowscape", "grassyterrain",
                    "psychicterrain", "electricterrain", "mistyterrain"}),
         frozenset({"drought", "drizzle", "sandstream", "snowwarning", "grassysurge", "psychicsurge",
                    "electricsurge", "mistysurge", "megasol", "orichalcumpulse", "hadronengine"})),
    Role("status", "Disruption", "Taunt, Encore, sleep or burns break up opposing plans.",
         frozenset({"taunt", "encore", "spore", "sleeppowder", "yawn", "willowisp", "thunderwave",
                    "disable", "imprison", "haze", "clearsmog", "roar", "whirlwind"})),
    Role("recovery", "Recovery / support healing", "Keeps your win condition on the field.",
         frozenset({"recover", "roost", "slackoff", "strengthsap", "lifedew", "pollenpuff", "healpulse",
                    "wish", "moonlight", "morningsun", "synthesis", "shoreup", "junglehealing"}),
         frozenset({"hospitality", "regenerator"})),
]


def providers(role: Role, members: list[Member]) -> list[str]:
    if role.key == "spread":
        return [m.label for m in members if any(mv["spread"] for mv in m.damaging_moves)]
    out = []
    for m in members:
        if role.abilities and m.ability_id in role.abilities:
            out.append(m.label)
        elif any(mv["id"] in role.moves for mv in m.moves):
            out.append(m.label)
    return out


def role_checklist(members: list[Member], doubles: bool) -> pd.DataFrame:
    rows = []
    for role in ROLES:
        if role.doubles_only and not doubles:
            continue
        who = providers(role, members)
        if role.key == "protect":
            ok = len(who) >= max(1, len(members) - 2)
            status = "Yes" if ok else ("Partly" if who else "Missing")
        else:
            status = "Yes" if who else ("Missing" if role.essential else "Optional")
        rows.append({"status": status, "role": role.label, "covered by": ", ".join(who) or "—", "why it matters": role.why})
    return pd.DataFrame(rows)


def provides_role(role_key: str, move_ids: set[str], ability_ids: set[str], has_spread: bool = False) -> bool:
    role = next(r for r in ROLES if r.key == role_key)
    if role.key == "spread":
        return has_spread
    return bool(move_ids & role.moves) or bool(ability_ids & role.abilities)


# --------------------------------------------------------------------------
# Speed
# --------------------------------------------------------------------------
def meta_speed(name: str, usage: UsageData, dex: Dex) -> dict | None:
    form, _ = meta_form(name, usage, dex)
    if form is None:
        return None
    base = form.base_stats["spe"]
    spreads = usage.section(name, "spreads")
    common = None
    if spreads:
        nature_name, sps = parse_spread(next(iter(spreads)))
        common = calc_stat(base, sps["spe"], "spe", dex.get_nature(nature_name))
    scarf = usage.section(name, "items").get("choicescarf", 0) >= 20
    return {
        "pokemon": form.name,
        "base": base,
        "min": calc_stat(base, 0, "spe", {"minus": "spe"}),
        "common": common,
        "max": calc_stat(base, 32, "spe", {"plus": "spe"}),
        "scarf": scarf,
    }


def speed_table(members: list[Member], dex: Dex, usage: UsageData | None, n: int = 20) -> pd.DataFrame:
    rows = [{"pokemon": f"{m.label} (yours)", "speed": m.stats["spe"], "who": "Your team", "note": ""}
            for m in members]
    if usage is not None:
        for name, _ in usage.ranked(n):
            info = meta_speed(name, usage, dex)
            if info is None or info["common"] is None:
                continue
            note = "often Choice Scarf (x1.5)" if info["scarf"] else ""
            rows.append({"pokemon": info["pokemon"], "speed": info["common"], "who": "Meta (most common spread)", "note": note})
    return pd.DataFrame(rows).sort_values("speed", ascending=False).reset_index(drop=True)
