"""
stats.py

Pokemon Champions stat math.

Champions replaced EVs/IVs with *Stat Points* (SP): every Pokemon is level 50
with perfect IVs, and you spread 66 SP across its stats, at most 32 in any one.
Each SP adds exactly 1 to the stat, which gives a much simpler formula than
the mainline games (this matches Showdown's champions mod):

    HP    = base + SP + 75
    other = floor((base + SP + 20) * nature)      nature = 1.1 / 1.0 / 0.9

A Pokemon with 32 SP in a stat therefore gains 32 points there - the same
as 252 EVs at level 50.
"""

from __future__ import annotations

from src.dex import STATS, STAT_LABELS

SP_TOTAL = 66
SP_MAX = 32


def nature_multiplier(nature: dict | None, stat: str) -> float:
    if not nature or stat == "hp":
        return 1.0
    if nature.get("plus") == stat:
        return 1.1
    if nature.get("minus") == stat:
        return 0.9
    return 1.0


def calc_stat(base: int, sp: int, stat: str, nature: dict | None = None) -> int:
    if stat == "hp":
        return base + sp + 75
    # Showdown truncates the nature multiplication via integer math (x110/100).
    raw = base + sp + 20
    mult = nature_multiplier(nature, stat)
    if mult == 1.1:
        return raw * 110 // 100
    if mult == 0.9:
        return raw * 90 // 100
    return raw


def calc_stats(base_stats: dict, sps: dict | None, nature: dict | None = None) -> dict:
    sps = sps or {}
    return {s: calc_stat(base_stats[s], int(sps.get(s, 0)), s, nature) for s in STATS}


def sp_problems(sps: dict, total: int = SP_TOTAL, per_stat: int = SP_MAX) -> list[str]:
    problems = []
    for stat in STATS:
        value = int(sps.get(stat, 0))
        if value < 0:
            problems.append(f"{STAT_LABELS[stat]} has negative Stat Points.")
        elif value > per_stat:
            problems.append(f"{STAT_LABELS[stat]} has {value} Stat Points (max {per_stat}).")
    spent = sum(int(sps.get(s, 0)) for s in STATS)
    if spent > total:
        problems.append(f"{spent} Stat Points spent (max {total}).")
    return problems


def parse_spread(spread: str) -> tuple[str, dict]:
    """Smogon spread key 'Careful:32/0/2/0/32/0' -> ('Careful', {'hp': 32, ...})."""
    nature, _, values = spread.partition(":")
    numbers = [int(float(v)) for v in values.split("/")] if values else [0] * 6
    return nature, dict(zip(STATS, numbers))


def format_sps(sps: dict) -> str:
    """{'hp': 32, 'spd': 32, 'def': 2} -> '32 HP / 2 Def / 32 SpD' (paste order)."""
    parts = [f"{int(sps[s])} {STAT_LABELS[s]}" for s in STATS if int(sps.get(s, 0))]
    return " / ".join(parts)
