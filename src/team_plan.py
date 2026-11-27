"""
team_plan.py

A one-line game plan for a whole team, before you know who you're facing: who to lead with, what the
speed plan is, and who closes the game. It's a starting point, read off the sets' roles (the same tags
as the Analysis tab) rather than a model: the Battle plan tab plans a specific matchup.

- Lead: the pair with the most turn-one tools (Tailwind / Trick Room, Fake Out, Intimidate, redirection,
  screens, a weather or terrain set on switch-in), as src/gameplan.LEAD_TOOLS weighs them.
- Closers: the two strongest attackers left in the back, setup sweepers first.
"""

from __future__ import annotations

from itertools import combinations

from src.dex import Dex
from src.gameplan import LEAD_TOOLS
from src.roles import set_roles
from src.team import PokemonSet

# turn-one value of what a set brings, on top of src/gameplan.LEAD_TOOLS
EXTRA_LEAD = {"Focus Sash lead": 0.15, "Sun setter": 0.2, "Rain setter": 0.2, "Sand setter": 0.2,
              "Snow setter": 0.2, "Terrain setter": 0.15}
SHORT = {"Tailwind setter": "Tailwind", "Trick Room setter": "Trick Room", "Fake Out support": "Fake Out",
         "Intimidate": "Intimidate", "Redirector": "redirection", "Screens": "screens",
         "Sun setter": "sun", "Rain setter": "rain", "Sand setter": "sand", "Snow setter": "snow",
         "Terrain setter": "terrain"}
ATTACKER = {"Physical attacker", "Special attacker"}


def _labels(pset: PokemonSet, dex: Dex, doubles: bool) -> list[str]:
    return [t.label for t in set_roles(pset, dex, doubles)]


def _lead_value(labels: list[str]) -> float:
    return sum(LEAD_TOOLS.get(x, 0.0) + EXTRA_LEAD.get(x, 0.0) for x in labels)


def _power(pset: PokemonSet, labels: list[str], dex: Dex) -> tuple:
    stats = pset.stats(dex)
    return ("Setup sweeper" in labels, bool(ATTACKER & set(labels)), max(stats["atk"], stats["spa"]))


def plan_line(sets: list[PokemonSet], dex: Dex, doubles: bool = True) -> str:
    """"Lead A + B (Tailwind, Fake Out); C (sets up) and D close it out from the back." ("" if too short)."""
    if len(sets) < 4:
        return ""
    labels = {i: _labels(p, dex, doubles) for i, p in enumerate(sets)}
    n_lead = 2 if doubles else 1
    # each tool counts once per lead: a second Fake Out adds little next to the first
    lead = max(combinations(range(len(sets)), n_lead),
               key=lambda pair: (_lead_value(sorted({x for i in pair for x in labels[i]})),
                                 -sum(_power(sets[i], labels[i], dex)[2] for i in pair)))
    tools = []
    for i in lead:
        tools += [SHORT[x] for x in labels[i] if x in SHORT and SHORT[x] not in tools]
    back = sorted((i for i in range(len(sets)) if i not in lead),
                  key=lambda i: _power(sets[i], labels[i], dex), reverse=True)
    closers = back[:2] if doubles else back[:1]
    head = f"Lead {' + '.join(sets[i].species for i in lead)}" + (f" ({', '.join(tools[:3])})" if tools else "")
    tail = " and ".join(sets[i].species + (" (sets up)" if "Setup sweeper" in labels[i] else "") for i in closers)
    return f"{head}; {tail} close{'s' if len(closers) == 1 else ''} it out from the back."
