"""
spread.py

Spread tuner: the fewest Stat Points that hit a set's benchmarks, keeping its nature.

    - outspeed: be faster than a given Speed stat
    - survive:  take each listed attack (attacker's set + move) without being KO'd, at the
                highest damage roll, no crit, no boosts (doubles spread damage when the move
                hits both foes)

Whatever's left of the 66 points goes to the set's attacking stat (Attack or Sp. Atk, from its
moves), then HP, then the defense that was tested least. Searching HP x Def (physical hits) and
HP x SpD (special hits) separately keeps it to a few hundred damage calcs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from src.damage import Battler, Field, calculate
from src.dex import Dex, to_id
from src.stats import SP_MAX, SP_TOTAL, STATS, calc_stat
from src.team import PokemonSet


@dataclass
class Benchmark:
    attacker: PokemonSet
    move: str


@dataclass
class TuneResult:
    sps: dict | None                 # None when the benchmarks can't all be met
    notes: list[str] = field(default_factory=list)
    problem: str = ""


def attack_stat(pset: PokemonSet, dex: Dex) -> str:
    phys = spec = 0
    for m in pset.moves:
        mv = dex.get_move(m)
        if not mv or mv.get("offensiveStat") or mv.get("overrideOffensivePokemon"):
            continue
        phys += mv["category"] == "Physical"
        spec += mv["category"] == "Special"
    if phys != spec:
        return "atk" if phys > spec else "spa"
    form = pset.battle_form(dex)
    return "atk" if form is None or form.base_stats["atk"] >= form.base_stats["spa"] else "spa"


def speed_points(pset: PokemonSet, dex: Dex, target: int) -> int | None:
    """Fewest Speed points to be strictly faster than `target` (None if 32 isn't enough)."""
    form = pset.battle_form(dex)
    nature = dex.get_nature(pset.nature)
    for sp in range(SP_MAX + 1):
        if calc_stat(form.base_stats["spe"], sp, "spe", nature) > target:
            return sp
    return None


def _max_damage(att: Battler, me: PokemonSet, dex: Dex, move: dict, doubles: bool) -> tuple[int, int]:
    d = Battler.from_set(me, dex)
    r = calculate(att, d, move, Field(doubles=doubles))
    return r.max, r.defender_hp


def tune(pset: PokemonSet, dex: Dex, outspeed: int | None = None, survive: list[Benchmark] | None = None,
         doubles: bool = True, rest: str = "attack") -> TuneResult:
    """rest: where leftover points go - "attack" (its attacking stat first) or "bulk" (HP, defenses)."""
    notes = []
    spe = 0
    if outspeed is not None:
        need = speed_points(pset, dex, outspeed)
        if need is None:
            return TuneResult(None, problem=f"can't outspeed {outspeed} even with 32 Speed points "
                                            "(its nature would have to change)")
        spe = need
        form = pset.battle_form(dex)
        notes.append(f"{spe} Spe → {calc_stat(form.base_stats['spe'], spe, 'spe', dex.get_nature(pset.nature))} "
                     f"Speed (beats {outspeed})")

    survive = survive or []
    hits = []
    for b in survive:
        mv = dex.get_move(b.move)
        if mv is None or mv["category"] == "Status":
            continue
        hits.append((Battler.from_set(b.attacker, dex), mv, b))

    def ok(hp: int, de: int, sd: int, which: str) -> bool:
        trial = replace(pset, sps={**{s: 0 for s in STATS}, "hp": hp, "def": de, "spd": sd})
        for att, mv, _ in hits:
            if mv["category"] != which:
                continue
            dmg, total = _max_damage(att, trial, dex, mv, doubles)
            if dmg >= total:
                return False
        return True

    best = None
    budget = SP_TOTAL - spe
    for hp in range(SP_MAX + 1):
        de = next((x for x in range(SP_MAX + 1) if ok(hp, x, 0, "Physical")), None)
        sd = next((x for x in range(SP_MAX + 1) if ok(hp, 0, x, "Special")), None)
        if de is None or sd is None or hp + de + sd > budget:
            continue
        cost = hp + de + sd
        if best is None or cost < best[0] or (cost == best[0] and hp > best[1]):
            best = (cost, hp, de, sd)
    if best is None:
        return TuneResult(None, notes=notes, problem="no spread survives all of those hits within 66 points"
                          + (" with that Speed" if spe else ""))
    _, hp, de, sd = best
    sps = {s: 0 for s in STATS}
    sps.update({"hp": hp, "def": de, "spd": sd, "spe": spe})
    for _, mv, b in hits:
        trial = replace(pset, sps=sps)
        dmg, total = _max_damage(Battler.from_set(b.attacker, dex), trial, dex, mv, doubles)
        who = b.attacker.battle_form(dex)
        notes.append(f"survives {who.name if who else b.attacker.species}'s {mv['name']} "
                     f"(max roll {100 * dmg / total:.0f}%)")

    # the rest: attacking stat, then HP, then whichever defense is lower
    left = SP_TOTAL - sum(sps.values())
    low, high = ("def", "spd") if sps["def"] <= sps["spd"] else ("spd", "def")
    order = ([attack_stat(pset, dex), "hp", low, high] if rest == "attack"
             else ["hp", low, high, attack_stat(pset, dex)]) + ["spe"]
    for stat in order:
        add = min(left, SP_MAX - sps[stat])
        sps[stat] += add
        left -= add
    return TuneResult(sps, notes)


__all__ = ["Benchmark", "TuneResult", "tune", "speed_points", "attack_stat", "to_id"]
