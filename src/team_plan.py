"""
team_plan.py

A short game plan for a whole team, before you know who you're facing: the four (three in singles) to
bring by default, who leads and why, and who closes. It's a starting point read off the sets' roles (the
same tags as the Analysis tab), not a model: the Battle plan tab plans a specific matchup.

- Lead: the pair with the most turn-one tools (src/gameplan.LEAD_TOOLS, plus weather / terrain / Sash),
  each tool counted once per lead, with a bonus when one lead protects the other's setup (Fake Out or
  redirection next to Tailwind / Trick Room).
- Closers: the core you built around (when it isn't leading), then the strongest attackers left, favouring ones that use the team's speed plan or weather. Only
  one setup sweeper: you rarely get two free setup turns, so a second one counts for less.
- Flex: the rest, to swap in by matchup.
"""

from __future__ import annotations

from itertools import combinations

from src.dex import Dex, to_id
from src.gameplan import LEAD_TOOLS
from src.roles import set_roles
from src.team import PokemonSet

# turn-one value of what a set brings, on top of src/gameplan.LEAD_TOOLS
EXTRA_LEAD = {"Focus Sash lead": 0.15, "Sun setter": 0.2, "Rain setter": 0.2, "Sand setter": 0.2,
              "Snow setter": 0.2, "Terrain setter": 0.15}
SPEED_SETTERS = {"Tailwind setter": "Tailwind", "Trick Room setter": "Trick Room"}
COVER = {"Fake Out support": "Fake Out", "Redirector": "redirection"}
SHORT = {"Intimidate": "Intimidate", "Screens": "screens", "Sun setter": "sun", "Rain setter": "rain",
         "Sand setter": "sand", "Snow setter": "snow", "Terrain setter": "terrain"}
ATTACKER = {"Physical attacker", "Special attacker"}
COVER_BONUS = 0.25        # a lead that keeps the other lead's speed control safe on turn one
PLAN_BONUS = 0.3          # a closer that uses the team's speed plan or weather
SETUP_BONUS = 0.2         # the first setup sweeper among the closers
SECOND_SETUP = -0.15      # a second one: two free setup turns rarely happen
WEATHER_ABILITIES = {"sun": {"chlorophyll", "solarpower", "protosynthesis"}, "rain": {"swiftswim"},
                     "sand": {"sandrush", "sandforce"}, "snow": {"slushrush"}}
WEATHER_WORD = {"sun": "sun", "rain": "rain", "sand": "sand", "snow": "snow"}


def _labels(pset: PokemonSet, dex: Dex, doubles: bool) -> list[str]:
    return [t.label for t in set_roles(pset, dex, doubles)]


def _lead_value(pair: tuple[int, ...], labels: dict[int, list[str]]) -> float:
    tools = {x for i in pair for x in labels[i]}   # each tool once per lead: a second Fake Out adds little
    value = sum(LEAD_TOOLS.get(x, 0.0) + EXTRA_LEAD.get(x, 0.0) for x in tools)
    if len(pair) == 2:
        a, b = pair
        for s, c in ((a, b), (b, a)):
            if set(labels[s]) & set(SPEED_SETTERS) and set(labels[c]) & set(COVER):
                return value + COVER_BONUS
    return value


def _power(pset: PokemonSet, dex: Dex) -> float:
    stats = pset.stats(dex)
    return max(stats["atk"], stats["spa"]) / 200


def _uses(pset: PokemonSet, dex: Dex, speed_plan: str, weather: str) -> str:
    """What of the team's plan this closer plays into: 'under Tailwind', 'in sun', ... or ''."""
    from src.builder import invests_speed
    if weather and to_id(pset.battle_ability(dex)) in WEATHER_ABILITIES.get(weather, set()):
        return f"in {WEATHER_WORD[weather]}"
    form = pset.battle_form(dex)
    base = form.base_stats["spe"] if form is not None else 0
    if speed_plan == "Tailwind" and invests_speed(pset, dex) and 45 <= base <= 110:
        return "under Tailwind"
    if speed_plan == "Trick Room" and not invests_speed(pset, dex) and base <= 60:
        return "under Trick Room"
    return ""


def plan_line(sets: list[PokemonSet], dex: Dex, doubles: bool = True, pick: int | None = None) -> str:
    """'Lead A + B: A's Fake Out buys B a free Tailwind. C (sets up) and D clean up under Tailwind.
    Swap in E or F by matchup.' ('' when the team is too short)."""
    pick = pick or (4 if doubles else 3)
    if len(sets) < pick:
        return ""
    from src.builder import field_setters, speed_modes
    labels = {i: _labels(p, dex, doubles) for i, p in enumerate(sets)}
    n_lead = 2 if doubles else 1
    lead = max(combinations(range(len(sets)), n_lead),
               key=lambda pair: (_lead_value(pair, labels), -sum(_power(sets[i], dex) for i in pair)))

    speed = set().union(*(speed_modes(sets[i]) for i in lead))
    speed_plan = next(iter(speed)) if len(speed) == 1 else ""
    weathers = set().union(*(field_setters(p, dex)["weather"] for p in sets))
    weather = next(iter(weathers)) if len(weathers) == 1 else ""

    # closers, greedily: power, plus the team's plan, plus one setup sweeper at most
    closers, uses = [], {}
    rest = [i for i in range(len(sets)) if i not in lead]
    if 0 not in lead:   # the core you built around always comes
        closers.append(0)
        uses[0] = _uses(sets[0], dex, speed_plan, weather)
    for _ in range(pick - n_lead - len(closers)):
        def score(i):
            s = _power(sets[i], dex) + (0.1 if ATTACKER & set(labels[i]) else 0.0)
            u = _uses(sets[i], dex, speed_plan, weather)
            s += PLAN_BONUS if u else 0.0
            if "Setup sweeper" in labels[i]:
                s += SECOND_SETUP if any("Setup sweeper" in labels[j] for j in closers) else SETUP_BONUS
            return s
        best = max((i for i in rest if i not in closers), key=score)
        closers.append(best)
        uses[best] = _uses(sets[best], dex, speed_plan, weather)
    flex = [i for i in rest if i not in closers]

    return " ".join(x for x in (_lead_text(sets, lead, labels), _closer_text(sets, closers, labels, uses),
                                _flex_text(sets, flex)) if x)


def _lead_text(sets, lead, labels) -> str:
    names = " + ".join(sets[i].species for i in lead)
    setter = next((i for i in lead if set(labels[i]) & set(SPEED_SETTERS)), None)
    cover = next((i for i in lead if i != setter and set(labels[i]) & set(COVER)), None)
    clauses = []
    if setter is not None:
        plan = SPEED_SETTERS[next(x for x in labels[setter] if x in SPEED_SETTERS)]
        if cover is not None:
            tool = COVER[next(x for x in labels[cover] if x in COVER)]
            clauses.append(f"{sets[cover].species}'s {tool} buys {sets[setter].species} a free {plan}")
        else:
            clauses.append(f"{sets[setter].species} sets {plan} turn one")
    extra = []
    for i in lead:
        for x in labels[i]:
            if x in SHORT and SHORT[x] not in extra:
                extra.append(SHORT[x])
            if x in COVER and i != cover and COVER[x] not in extra:
                extra.append(COVER[x])
    if extra:
        clauses.append(("plus " if clauses else "") + ", ".join(extra[:3]))
    return f"Lead {names}" + (f": {', '.join(clauses)}." if clauses else ".")


def _closer_text(sets, closers, labels, uses) -> str:
    if not closers:
        return ""
    parts = [sets[i].species + (" (sets up)" if "Setup sweeper" in labels[i] else "") for i in closers]
    shared = {uses[i] for i in closers}
    if len(shared) == 1 and "" not in shared:
        where = f" {shared.pop()}"
    else:
        parts = [p + (f" ({uses[i]})" if uses[i] and "(" not in p else "") for p, i in zip(parts, closers)]
        where = ""
    if all(ATTACKER & set(labels[i]) for i in closers):
        verb = "cleans up" if len(parts) == 1 else "clean up"
        return f"{' and '.join(parts)} {verb}{where}."
    return f"In the back: {' and '.join(parts)}{where}."


def _flex_text(sets, flex) -> str:
    if not flex:
        return ""
    names = [sets[i].species for i in flex]
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
    return f"Swap in {joined} by matchup."
