"""
setup.py

What a setup move buys: the core's damage and Speed against the most-used Pokemon at +0 and after one
use of its setup move (Dragon Dance, Swords Dance, Quiver Dance, Calm Mind, Nasty Plot, Shell Smash...).

A display, not a score: it assumes the setup turn is free. Whether you get that turn depends on Fake Out,
redirection, Protect and what the opponent does, which damage calcs can't see. The learned win model
already credits setup moves from real results (README, "What it learned"), turn cost included.
"""

from __future__ import annotations

from dataclasses import replace

from src.dex import Dex, to_id

# One use of each move: stat stage changes (Showdown's data). Growth is +2/+2 in sun; shown at +1.
SETUP_BOOSTS = {
    "dragondance": {"atk": 1, "spe": 1}, "swordsdance": {"atk": 2}, "nastyplot": {"spa": 2},
    "calmmind": {"spa": 1, "spd": 1}, "quiverdance": {"spa": 1, "spd": 1, "spe": 1},
    "bulkup": {"atk": 1, "def": 1}, "coil": {"atk": 1, "def": 1}, "irondefense": {"def": 2},
    "shellsmash": {"atk": 2, "spa": 2, "spe": 2, "def": -1, "spd": -1}, "agility": {"spe": 2},
    "rockpolish": {"spe": 2}, "victorydance": {"atk": 1, "def": 1, "spe": 1}, "tidyup": {"atk": 1, "spe": 1},
    "curse": {"atk": 1, "def": 1, "spe": -1}, "growth": {"atk": 1, "spa": 1}, "workup": {"atk": 1, "spa": 1},
    "geomancy": {"spa": 2, "spd": 2, "spe": 2}, "cosmicpower": {"def": 1, "spd": 1}, "amnesia": {"spd": 2},
    "shiftgear": {"atk": 1, "spe": 2}, "honeclaws": {"atk": 1}, "howl": {"atk": 1},
}
LABEL = {"atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}


def setup_move(pset) -> tuple[str, dict] | None:
    """The set's setup move with the biggest boost, and its stage changes."""
    found = [(to_id(m), m) for m in pset.moves if to_id(m) in SETUP_BOOSTS]
    if not found:
        return None
    mid, name = max(found, key=lambda x: sum(v for v in SETUP_BOOSTS[x[0]].values() if v > 0))
    return name, SETUP_BOOSTS[mid]


def boost_text(boosts: dict) -> str:
    return ", ".join(f"{v:+d} {LABEL[s]}" for s, v in boosts.items())


def _best(att, dfn, att_battler, dfn_battler, doubles: bool) -> tuple[float, str]:
    from src.damage import Field, calculate
    best = (0.0, "")
    f = Field(doubles=doubles)
    for mv in att.damaging_moves:
        r = calculate(att_battler, dfn_battler, mv, f)
        avg = 100 * sum(r.rolls) / len(r.rolls) / r.defender_hp if r.rolls else 0.0
        if avg > best[0]:
            best = (avg, mv["name"])
    return best


def after_setup(core_set, usage, dex: Dex, doubles: bool = True, n: int = 30) -> dict | None:
    """{move, boosts, beats (newly won one-on-ones, with the calc), ohko (before, after), outspeeds
    (newly outsped), total} for the core against the n most-used Pokemon; None without a setup move."""
    from src.analysis import build_members
    from src.damage import boosted
    from src.matchup import opponent_members, wins_one_on_one
    from src.stats import effective_speed
    found = setup_move(core_set)
    if found is None:
        return None
    move, boosts = found
    members = build_members([core_set], dex)
    if not members or members[0].battler is None:
        return None
    m = members[0]
    up = replace(m.battler, boosts={**m.battler.boosts, **boosts})
    item = m.pset.item if m.pset else None
    spe0 = effective_speed(m.stats["spe"], item)
    spe1 = effective_speed(boosted(m.stats["spe"], boosts.get("spe", 0)), item)
    beats, outspeeds, ohko0, ohko1, total = [], [], 0, 0, 0
    for name, _ in usage.ranked(n):
        opp = opponent_members([name], usage, dex)
        if not opp or opp[0].battler is None:
            continue
        t = opp[0]
        total += 1
        t_spe = effective_speed(t.stats["spe"], t.pset.item if t.pset else None)
        d0, _ = _best(m, t, m.battler, t.battler, doubles)
        d1, mv1 = _best(m, t, up, t.battler, doubles)
        taken0, _ = _best(t, m, t.battler, m.battler, doubles)
        taken1, _ = _best(t, m, t.battler, up, doubles)
        ohko0 += d0 >= 100
        ohko1 += d1 >= 100
        if not wins_one_on_one(d0, taken0, spe0, t_spe) and wins_one_on_one(d1, taken1, spe1, t_spe):
            beats.append((t.label, f"{mv1} {d1:.0f}%"))
        if spe0 <= t_spe < spe1:
            outspeeds.append(t.label)
    return {"move": move, "boosts": boosts, "beats": beats, "ohko": (ohko0, ohko1), "outspeeds": outspeeds,
            "total": total, "speed": (spe0, spe1)}


__all__ = ["SETUP_BOOSTS", "setup_move", "boost_text", "after_setup"]
