"""
formats.py

The Pokemon Champions formats the tool supports.

A *regulation* (M-B, M-C, ...) decides which Pokemon, moves and items are
legal; a *format* adds the battle style on top (VGC doubles: bring 6, pick 4;
Battle Stadium Singles: bring 6, pick 3). Both formats of one regulation share
a single dex file in data/dex/.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    id: str              # Showdown / Smogon stats id
    label: str           # shown in the UI
    regulation: str      # data/dex/<regulation>.json
    game_type: str       # "doubles" or "singles"
    pick: int            # how many of the 6 you bring into each game
    active: str          # human-readable date range
    usage_cutoff: int = 1630  # Smogon rating cutoff to pull usage stats at
    current: bool = False

    @property
    def is_doubles(self) -> bool:
        return self.game_type == "doubles"


FORMATS: dict[str, Format] = {
    f.id: f
    for f in [
        Format(
            id="gen9championsvgc2026regmc",
            label="VGC 2026 Reg M-C (Doubles)",
            regulation="regmc",
            game_type="doubles",
            pick=4,
            active="Sep 9 – Dec 2, 2026",
            current=True,
        ),
        Format(
            id="gen9championsbssregmc",
            label="Battle Stadium Singles Reg M-C",
            regulation="regmc",
            game_type="singles",
            pick=3,
            active="Sep 9 – Dec 2, 2026",
            current=True,
        ),
        Format(
            id="gen9championsvgc2026regmb",
            label="VGC 2026 Reg M-B (Doubles, past)",
            regulation="regmb",
            game_type="doubles",
            pick=4,
            active="Jun 17 – Sep 8, 2026",
        ),
    ]
}

DEFAULT_FORMAT = "gen9championsvgc2026regmc"
