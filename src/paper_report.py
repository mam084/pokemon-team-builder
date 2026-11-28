"""
paper_report.py

Why a team rates the way it does "on paper": the learned win model's reasons, added up over every meta
team. The model (src/match_model.py) explains each matchup as pushes on the odds of winning: damage calcs,
Speed, bulk, support tools and per-Pokemon effects. Averaging those pushes over the meta teams shows where
the team gains and loses ground against the meta, and each part that costs it points comes with what would
help.

These are the model's reasons, in win-percentage points against the average meta team (25 x log-odds, the
slope at 50%). They're comparisons with the meta teams, not with tournament teams: the grade does that.
"""

from __future__ import annotations

from src.match_model import GROUPS, contributions, predict_match

POINTS = 25           # log-odds -> win-percentage points near 50%
MIN_POINTS = 0.3      # smaller average pushes aren't worth a line

# what would help when a part costs the team points
FIX = {
    "Damage calcs": "Hit the meta harder: attackers that 2HKO more of it, or coverage for the Pokémon you "
                    "can't hit super effectively (Offensive coverage, below).",
    "Speed": "Win the Speed race more often: a Tailwind or Trick Room setter that suits your team's Speed, "
             "or faster attackers (Speed tiers, below).",
    "Bulk": "Take hits better: bulkier picks, or more Stat Points in HP and the defenses.",
    "Pokémon picks": "The model rates some of your picks below the meta's, from how those Pokémon did in real "
                     "games. The swaps on the Matchups tab test replacements.",
    "Matchup score": "Your Pokémon match up worse, one on one, than the meta teams' do against you. The "
                     "swaps on the Matchups tab look for better ones.",
}
TOOL_HINT = {"Redirection": "Follow Me or Rage Powder", "Speed drops": "Icy Wind or Electroweb",
             "Priority attack": "a priority attack", "Setup": "a setup move", "Recovery": "recovery",
             "Weather": "a weather setter", "Terrain": "a terrain setter", "Sleep": "a sleep move",
             "Paralysis": "paralysis", "Burn": "burns"}


def group_of(feature: str) -> str:
    group = next((g for g, fs in GROUPS.items() if feature in fs), None)
    if group:
        return group
    if feature.startswith("tool: "):
        return feature[len("tool: "):]
    if feature.startswith("species: "):
        return "Pokémon picks"
    return {"score vs meta": "Matchup score"}.get(feature, feature)


def fix_for(group: str, coef_sign: float) -> str:
    if group in FIX:
        return FIX[group]
    hint = TOOL_HINT.get(group, group)
    if coef_sign > 0:
        return (f"In real games, teams with more {group} than their opponent won more often, and most meta "
                f"teams have more than you: consider a Pokémon with {hint}.")
    return (f"In real games, teams with more {group} than their opponent won a little less often, and you "
            f"have more than most meta teams. A small effect: worth a look, not a rule.")


def breakdown(model: dict, mine: list[dict], sides: list[dict], names: list[str] | None = None,
              weights: list[float] | None = None) -> dict:
    """
    {"parts": [(group, avg points, fix or "")] most-costly first, "chances": [per meta team],
     "toughest": [(name, chance)] the three worst, "average": weighted win chance}. `mine`: the team's sides (one per Mega choice; each
    matchup uses the best one, as the win chance does). `weights`: each meta team's popularity, as the
    Matchups tab weighs its win chance.
    """
    if not mine or not sides:
        return {"parts": [], "chances": [], "toughest": [], "average": 0.5}
    coef = dict(zip(model["model"]["features"], model["model"]["coef"]))
    totals: dict[str, float] = {}
    signs: dict[str, float] = {}
    chances = []
    weights = list(weights) if weights is not None and len(weights) == len(sides) else [1.0] * len(sides)
    for theirs, w in zip(sides, weights):
        side = max(mine, key=lambda m: predict_match(model, m, theirs))
        chances.append(predict_match(model, side, theirs))
        for name, c in contributions(model, side, theirs):
            g = group_of(name)
            totals[g] = totals.get(g, 0.0) + w * c
            signs.setdefault(g, coef.get(name, 1.0))
    n = len(sides)
    total_w = sum(weights) or 1.0
    parts = [(g, POINTS * v / total_w) for g, v in totals.items() if abs(POINTS * v / total_w) >= MIN_POINTS]
    parts.sort(key=lambda kv: kv[1])
    parts = [(g, v, fix_for(g, signs.get(g, 1.0)) if v < 0 else "") for g, v in parts]
    names = names or [f"Meta team {i + 1}" for i in range(n)]
    toughest = sorted(zip(names, chances), key=lambda kv: kv[1])[:3]
    average = sum(w * c for w, c in zip(weights, chances)) / total_w
    return {"parts": parts, "chances": chances, "toughest": toughest, "average": average}
