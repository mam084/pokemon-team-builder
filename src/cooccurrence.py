"""
cooccurrence.py

Teammate pairings from real tournament team lists, as a second source for the
recommender's synergy signal.

Ladder teammate stats (src/usage.py) are weighted toward the rating cutoff, so
for a Pokemon on 0.05% of high-ladder teams they describe one or two players.
Thousands of open-tournament team sheets give those Pokemon real sample sizes.

Lift of a pair = observed teams with both / teams expected by chance. It is
smoothed with a pseudo-count (PRIOR teams of "no effect"), so a pair seen
together on 2 teams where 0.3 were expected reads as a modest lift, not 7x.
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

from src.dex import Dex
from src.team import PokemonSet

PRIOR = 3.0  # pseudo-count of teams pulling a pair's lift toward 1


class Cooccurrence:
    def __init__(self, teams: list[list[PokemonSet]], dex: Dex):
        self.dex = dex
        self.teams = len(teams)
        self.single: Counter = Counter()
        self.pair: Counter = Counter()
        for sets in teams:
            keys = sorted({self.key(p.species) for p in sets} - {None})
            self.single.update(keys)
            self.pair.update(combinations(keys, 2))

    def key(self, name: str) -> str | None:
        species = self.dex.get_species(name)
        return self.dex.sheet_id(species) if species else None  # Megas count as their base

    def log_lift(self, a: str, b: str) -> tuple[float, float]:
        """(smoothed log2 lift, confidence 0..1). Confidence grows with how many teams the
        pair would share by chance, so pairs of rarely used Pokemon carry little weight."""
        ka, kb = self.key(a), self.key(b)
        if not ka or not kb or ka == kb or not self.teams:
            return 0.0, 0.0
        na, nb = self.single.get(ka, 0), self.single.get(kb, 0)
        if not na or not nb:
            return 0.0, 0.0
        expected = na * nb / self.teams
        observed = self.pair.get((min(ka, kb), max(ka, kb)), 0)
        lift = (observed + PRIOR) / (expected + PRIOR)
        return math.log2(lift), expected / (expected + PRIOR)
