"""
formats.py

The Pokemon Champions formats the tool supports.

A *regulation* (M-B, M-C, ...) decides which Pokemon, moves and items are
legal; a *format* adds the battle style on top (VGC doubles: bring 6, pick 4;
Battle Stadium Singles: bring 6, pick 3). Both formats of one regulation share
a single dex file in data/dex/.
"""

import os
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
    start: str = ""      # first day (YYYY-MM-DD): replays are fetched back to here
    replays: tuple[str, ...] = ()  # Showdown formats whose replays feed this one's learned models
    limitless: str = ""  # Limitless VGC format id for tournament team lists ("M-C")
    previous: str = ""   # the last regulation's format of the same style: its sets fill in early on

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
            start="2026-09-09",
            replays=("gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3"),
            limitless="M-C",
            previous="gen9championsvgc2026regmb",
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
# The tests pin a regulation with a full season of data (tests/__init__.py), so a switch to a brand-new
# one doesn't fail checks that need tournament sheets or a month of replays; the app never sets this.
if os.environ.get("PTB_FORMAT") in FORMATS:
    DEFAULT_FORMAT = os.environ["PTB_FORMAT"]
CURRENT = FORMATS[DEFAULT_FORMAT]  # the regulation the learned models and evaluation are built for

# A new regulation: run scripts/new_regulation.py (it adds the entries above, marks the old ones
# past and points DEFAULT_FORMAT at the new one; README "When a new regulation starts").
# Replay fetching, the replay summaries and every learned model read these entries; nothing
# else names the regulation. Until Smogon publishes the new regulation's stats, usage is
# built from its replays (src/replay_usage.py).


def replay_sources() -> dict[str, tuple[str, str]]:
    """{Showdown format id to fetch replays for: (app format it feeds, its start day)} for
    the current formats."""
    return {r: (f.id, f.start) for f in FORMATS.values() if f.current for r in f.replays}
