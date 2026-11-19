"""
playbook.py

How to play against a style (Trick Room, Tailwind, weather, Psychic Terrain, setup sweepers), from what
real players did and how it went: rated ladder and Bo3 replays, last 30 days.

For each style, the games where the opponent *led* with a Pokemon that sets it up (what you can see when
you choose your turn-1 moves). Each turn-1 choice (Fake Out on the setter, Taunt it, attack it, set your
own speed control, Protect...) is scored by how much more the players who made it won than their ratings
predicted (Elo), compared with the players facing the same lead who didn't.

These are associations, not proof: a choice also says something about the team and the player. And the
replay log only shows moves that happened, so a setter stopped by Fake Out never shows its Trick Room;
that's why games are picked by the lead, not by what the setter did.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from src.dex import Dex, to_id

SUMMARY_DIR = Path(__file__).resolve().parent.parent / "data" / "replays" / "summary"
DAYS = 30
MIN_RATING = 1100
MIN_GAMES = 80          # a choice needs this many games (and as many without it) to be shown

SPEED = {"Trick Room": "trickroom", "Tailwind": "tailwind"}
WEATHER = {"Rain": {"drizzle"}, "Sun": {"drought"}, "Sand": {"sandstream"}, "Snow": {"snowwarning"}}
TAUNTS = {"taunt", "encore", "disable"}
PHAZE = {"haze", "clearsmog", "roar", "whirlwind", "dragontail", "circlethrow", "encore", "spectralthief"}
PROTECTS = {"protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap", "burningbulwark"}
SETUP = {"swordsdance", "nastyplot", "calmmind", "dragondance", "quiverdance", "shellsmash", "bulkup",
         "bellydrum", "victorydance", "tidyup", "coil", "geomancy", "shiftgear"}
OTHER_SPEED = {"trickroom": {"tailwind"}, "tailwind": {"trickroom", "icywind", "electroweb", "thunderwave"}}

STYLES = ["Trick Room", "Tailwind", "Rain", "Sun", "Sand", "Snow", "Psychic Terrain", "Setup sweepers"]
BLURB = {
    "Trick Room": "slow Pokémon move first for five turns",
    "Tailwind": "their side's Speed doubles for four turns",
    "Rain": "Water moves get stronger, Fire weaker; Swift Swim doubles Speed",
    "Sun": "Fire moves get stronger, Water weaker; Chlorophyll doubles Speed",
    "Sand": "Rock types get 50% more Special Defense; chip damage to most others",
    "Snow": "Ice types get 50% more Defense; Blizzard never misses",
    "Psychic Terrain": "priority moves (Fake Out too) fail against grounded Pokémon; Psychic moves hit harder",
    "Setup sweepers": "Calm Mind, Dragon Dance, Swords Dance, Quiver Dance and the like",
}


def style_setters(usage, dex: Dex) -> dict[str, set[str]]:
    """{style: battle-form names that set it} by the Matchups tab's rules (a move on 40%+ of sets, an
    ability on 50%+ or a Mega's own); setup sweepers: a setup move on 40%+ of sets."""
    out: dict[str, set[str]] = defaultdict(set)
    for name, _ in usage.ranked():
        form = dex.get_species(name)
        if form is None:
            continue
        abil = {to_id(form.abilities[0])} if form.is_mega else \
            {to_id(a) for a, pct in usage.section(name, "abilities").items() if pct >= 50}
        moves = {to_id(m) for m, pct in usage.section(name, "moves").items() if pct >= 40}
        for label, mid in SPEED.items():
            if mid in moves:
                out[label].add(name)
        for label, abilities in WEATHER.items():
            if abil & abilities:
                out[label].add(name)
        if "psychicsurge" in abil:
            out["Psychic Terrain"].add(name)
        if moves & SETUP:
            out["Setup sweepers"].add(name)
    return dict(out)


def _base(name: str) -> str:
    """'Charizard-Mega-Y' -> 'Charizard': replay leads name the battle form, previews the base."""
    for tag in ("-Mega-X", "-Mega-Y", "-Mega-Z", "-Mega"):
        if name.endswith(tag):
            return name[: -len(tag)]
    return name


SURGES = {"psychicsurge", "grassysurge", "electricsurge", "mistysurge", "hadronengine"}
FAILED_FAKE_OUT = "Fake Out into Psychic Terrain (it fails)"


def _abilities(name: str, dex: Dex) -> set[str]:
    s = dex.get_species(name)
    return {to_id(a) for a in s.abilities} if s is not None else set()


def _grounded(name: str, dex: Dex) -> bool:
    """Not Flying and no Levitate (Air Balloon isn't in the replay log)."""
    s = dex.get_species(name)
    return s is not None and "Flying" not in s.types and "levitate" not in _abilities(name, dex)


def _terrain_blocks(their_leads: list[str], my_leads: list[str], dex: Dex) -> bool:
    """Their lead brings Psychic Terrain and yours has no terrain of its own to replace it."""
    theirs = any("psychicsurge" in _abilities(x, dex) for x in their_leads)
    mine = any(_abilities(x, dex) & SURGES for x in my_leads)
    return theirs and not mine


def _labels(style: str, mine: list, their_setter: str, my_leads: list[str], my_brought: list[str],
            used: dict, setters: dict[str, set[str]], dex: Dex, their_leads: list[str] | None = None) -> set[str]:
    """The choices one player made (turn 1, or over the game for setup answers) facing this lead.
    The replay log shows a move even when it fails, so a Fake Out into Psychic Terrain at a grounded
    target is its own choice, not a Fake Out on the setter or its partner."""
    out = set()
    hits_setter = 0
    blocks = _terrain_blocks(their_leads or [their_setter], my_leads, dex)
    for mon, move, target in mine:
        mid = to_id(move)
        mv = dex.moves.get(mid)
        damaging = mv is not None and mv["category"] != "Status"
        on_setter = target is not None and _base(target) == _base(their_setter)
        if mid == "fakeout":
            if blocks and target is not None and _grounded(target, dex):
                out.add(FAILED_FAKE_OUT)
            else:
                out.add("Fake Out on the setter" if on_setter else "Fake Out on its partner")
        elif mid in TAUNTS and on_setter:
            out.add("Taunt or Encore on the setter")
        elif mid == "imprison" and style == "Trick Room":
            out.add("Imprison")
        elif damaging and on_setter:
            hits_setter += 1
        if style in SPEED and mid == SPEED[style]:
            out.add(f"Your own {style}")
        if style in SPEED and mid in OTHER_SPEED[SPEED[style]]:
            out.add("Tailwind" if style == "Trick Room" else "Trick Room or speed drops")
    if hits_setter:
        out.add("Attacked the setter" if hits_setter == 1 else "Both attacked the setter")
    if mine and all(to_id(m) in PROTECTS for _, m, _ in mine):
        out.add("Both Protected")
    if style in WEATHER:
        own = {n for lab in WEATHER for n in setters.get(lab, set()) if lab != style}
        if any(_base(x) in {_base(n) for n in own} for x in my_leads):
            out.add("Led your own weather setter")
        elif any(_base(x) in {_base(n) for n in own} for x in my_brought):
            out.add("Brought your own weather setter (not leading)")
    if style == "Setup sweepers":
        if any(to_id(m) in PHAZE for moves in used.values() for m in moves):
            out.add("Used Haze, Clear Smog, Roar, Whirlwind or Encore in the game")
    return out


# A choice that needs a move is judged only against players who had that move and didn't use it (having
# Fake Out isn't the story; using it is). (moves, where it had to be: "lead" for turn 1, "brought" for the game)
NEEDS_MOVE = {
    "Fake Out on the setter": ({"fakeout"}, "lead"),
    "Fake Out on its partner": ({"fakeout"}, "lead"),
    "Taunt or Encore on the setter": ({"taunt", "encore", "disable"}, "lead"),
    "Imprison": ({"imprison"}, "lead"),
    "Your own Trick Room": ({"trickroom"}, "lead"),
    "Your own Tailwind": ({"tailwind"}, "lead"),
    "Tailwind": ({"tailwind"}, "lead"),
    "Trick Room or speed drops": ({"trickroom", "icywind", "electroweb", "thunderwave"}, "lead"),
    "Used Haze, Clear Smog, Roar, Whirlwind or Encore in the game": (PHAZE, "brought"),
}
WEATHER_CHOICES = {"Led your own weather setter", "Brought your own weather setter (not leading)"}
COMMON = 40   # a move on this % of a Pokemon's ladder sets counts as one it has


def common_moves(usage) -> dict[str, set[str]]:
    """{Pokemon (base name): move ids on COMMON%+ of its ladder sets, any form}."""
    out: dict[str, set[str]] = defaultdict(set)
    for name, _ in usage.ranked():
        out[_base(name)] |= {to_id(m) for m, pct in usage.section(name, "moves").items() if pct >= COMMON}
    return dict(out)


def _has(mons: list[str], ids: set[str], r: dict, p: str, common: dict[str, set[str]]) -> bool:
    """Did one of these Pokemon have one of these moves: on its open team sheet, used in this game, or on
    COMMON%+ of its ladder sets."""
    sheet = {_base(m["species"]): {to_id(x) for x in m.get("moves") or []} for m in (r.get("sheets") or {}).get(p) or []}
    shown = {_base(m): {to_id(x) for x in mv} for m, mv in ((r.get("moves") or {}).get(p) or {}).items()}
    for mon in mons:
        b = _base(mon)
        if ids & (sheet.get(b, set()) | shown.get(b, set()) | common.get(b, set())):
            return True
    return False


def replay_playbook(records: list[dict], dex: Dex, setters: dict[str, set[str]], days: int = DAYS,
                    min_rating: int = MIN_RATING, common: dict[str, set[str]] | None = None) -> dict:
    """{style: {games, choices: [{choice, n, compared, against, edge, lo, hi}]}} (see the module docstring).
    edge: points of win chance above the ratings' prediction, minus the same for the comparison group, players
    facing the same lead who could have made the choice and didn't (they had the move, or a weather setter in
    team preview), or for choices any team can make, everyone else facing that lead; lo-hi: 90% interval."""
    common = common or {}
    stamped = [r for r in records if r.get("uploadtime")]
    if not stamped:
        return {}
    end = max(r["uploadtime"] for r in stamped)
    start = end - days * 86400
    by_style: dict[str, list[tuple[set[str], float, set[str]]]] = defaultdict(list)
    base_sets = {s: {_base(n) for n in names} for s, names in setters.items()}
    weather_setters = {_base(n) for lab in WEATHER for n in setters.get(lab, set())}
    for r in stamped:
        if r["uploadtime"] < start or r.get("forfeit"):
            continue
        ra, rb = (r["players"][p].get("rating") or 0 for p in ("p1", "p2"))
        if min(ra, rb) < min_rating:
            continue
        for p, q, own, opp in (("p1", "p2", ra, rb), ("p2", "p1", rb, ra)):
            leads = r["leads"].get(q) or []
            my_leads, my_brought = r["leads"].get(p) or [], r["brought"].get(p) or []
            for style in STYLES:
                setter = next((x for x in leads if _base(x) in base_sets.get(style, set())), None)
                if setter is None:
                    continue
                labels = _labels(style, r["turn1"].get(p) or [], setter, my_leads, my_brought,
                                 (r.get("moves") or {}).get(p) or {}, setters, dex, their_leads=leads)
                could = set()   # choices this player could have made
                for lab, (ids, where) in NEEDS_MOVE.items():
                    if _has(my_leads if where == "lead" else my_brought, ids, r, p, common):
                        could.add(lab)
                if style in WEATHER:
                    mine_w = {x for x in (r["preview"].get(p) or []) if _base(x) in weather_setters
                              and _base(x) not in base_sets.get(style, set())}
                    if mine_w:
                        could.add("Led your own weather setter")
                        if not any(_base(x) in {_base(o) for o in mine_w} for x in my_leads):
                            could.add("Brought your own weather setter (not leading)")
                residual = (r["winner"] == p) - 1 / (1 + 10 ** ((opp - own) / 400))
                by_style[style].append((labels, residual, could))
    out = {}
    for style, rows in by_style.items():
        # a Fake Out into Psychic Terrain does nothing, so it isn't scored as a choice: its games still count
        # for every other choice those players made (its +8 points in Nov 2026 said who clicks it, not what it did)
        failed = sum(FAILED_FAKE_OUT in labels for labels, _, _ in rows)
        all_labels = sorted({lab for labels, _, _ in rows for lab in labels} - {FAILED_FAKE_OUT})
        choices = []
        for lab in all_labels:
            gated = lab in NEEDS_MOVE or lab in WEATHER_CHOICES
            family = NEEDS_MOVE[lab][0] if lab in NEEDS_MOVE else None
            yes, no = [], []
            for labels, res, could in rows:
                if lab in labels:
                    yes.append(res)
                elif not gated:
                    no.append(res)
                elif lab in could:
                    # had it and didn't use it: for a move, no use of it at all this turn (a Fake Out on the
                    # partner isn't "not using Fake Out"); for weather, didn't lead / bring the setter
                    if family is None or not any(l2 in labels for l2, (ids, _) in NEEDS_MOVE.items() if ids & family):
                        no.append(res)
            if len(yes) < MIN_GAMES or len(no) < MIN_GAMES:
                continue
            m_y, m_n = sum(yes) / len(yes), sum(no) / len(no)
            var = lambda xs, m: sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1)  # noqa: E731
            se = math.sqrt(var(yes, m_y) / len(yes) + var(no, m_n) / len(no))
            edge = m_y - m_n
            choices.append({"choice": lab, "n": len(yes), "share": round(len(yes) / len(rows), 3),
                            "compared": len(no), "against": "had it, didn't" if gated else "everyone else",
                            "edge": round(100 * edge, 2), "lo": round(100 * (edge - 1.645 * se), 2),
                            "hi": round(100 * (edge + 1.645 * se), 2)})
        choices.sort(key=lambda c: -c["edge"])
        out[style] = {"games": len(rows), "setters": sorted(setters.get(style, set())), "choices": choices,
                      "failed_fake_outs": failed}
    return {"days": days, "min_rating": min_rating, "styles": out}


def save(book: dict, format_id: str) -> Path:
    path = SUMMARY_DIR / f"{format_id}_playbook.json"
    path.write_text(json.dumps(book, separators=(",", ":")))
    return path


def load(format_id: str) -> dict | None:
    path = SUMMARY_DIR / f"{format_id}_playbook.json"
    return json.loads(path.read_text()) if path.exists() else None


# ---------------------------------------------------------------------------- your team's tools
TOOLS = {
    "Fake Out": {"fakeout"}, "Taunt": {"taunt"}, "Encore": {"encore"}, "Imprison": {"imprison"},
    "Trick Room": {"trickroom"}, "Tailwind": {"tailwind"}, "Speed drops": {"icywind", "electroweb", "thunderwave"},
    "Haze / phazing": {"haze", "clearsmog", "roar", "whirlwind", "dragontail", "circlethrow", "spectralthief"},
    "Priority": {"suckerpunch", "aquajet", "bulletpunch", "extremespeed", "grassyglide", "machpunch",
                 "iceshard", "shadowsneak", "quickattack", "vacuumwave", "jetpunch", "firstimpression"},
    "Wide Guard": {"wideguard"},
}
TOOL_ABILITIES = {"Unaware": {"unaware"}, "Weather": {"drizzle", "drought", "sandstream", "snowwarning"},
                  "Intimidate": {"intimidate"}}


def team_tools(members) -> dict[str, list[str]]:
    """{tool: your Pokemon that have it} from moves and abilities (Mega abilities included)."""
    out: dict[str, list[str]] = defaultdict(list)
    for m in members:
        moves = {mv["id"] for mv in m.moves}
        abilities = {m.ability_id} | ({to_id(a) for a in m.form.abilities} if m.form.is_mega else set())
        for tool, ids in TOOLS.items():
            if moves & ids:
                out[tool].append(m.label)
        for tool, ids in TOOL_ABILITIES.items():
            if abilities & ids:
                out[tool].append(m.label)
    return dict(out)


def setter_hits(members, style: str, setters: dict[str, set[str]], usage, dex: Dex, doubles: bool = True,
                n: int = 3) -> list[tuple[str, str]]:
    """[(setter, 'Kingambit: Kowtow Cleave 92%')] your hardest hit on each of the n most used setters."""
    from src.matchup import best_attack, opponent_members
    names = sorted(setters.get(style, set()), key=lambda x: -usage.usage(x))[:n]
    out = []
    for name in names:
        opp = opponent_members([name], usage, dex)
        if not opp:
            continue
        best = max(((best_attack(m, opp[0], doubles), m.label) for m in members), key=lambda x: x[0][0],
                   default=None)
        if best and best[0][1]:
            (pct, move), who = best
            out.append((name, f"{who}: {move} {pct:.0f}%"))
    return out


__all__ = ["STYLES", "BLURB", "style_setters", "common_moves", "replay_playbook", "save", "load", "team_tools", "setter_hits"]
