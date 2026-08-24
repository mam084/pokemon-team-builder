"""
recommend.py

Stage 3: a basic teammate recommender. Given the Pokemon already on a team,
suggests good additions by aggregating real-world co-occurrence data across
every team member - not just showing one Pokemon's top partners in isolation
(that's what Stage 2 already does), but combining signal across the whole team.

This is intentionally simple - straight aggregation of co-occurrence
percentages, no learned weighting. Stage 4 is where this gets upgraded to
embeddings-based synergy scoring.
"""

from collections import defaultdict

import pandas as pd

from src.name_utils import normalize_name


def recommend_teammates(
    teammates_df: pd.DataFrame,
    team_names: list[str],
    top_n: int = 10,
) -> list[dict]:
    """
    Given a list of Pokemon already on a team, recommend additions.

    Approach: for each Pokemon on the team, pull its top real-world teammates
    and their co-occurrence %. Sum co-occurrence scores across all team
    members for each candidate (so a Pokemon that pairs well with *multiple*
    team members ranks higher than one that only pairs well with one).
    Candidates already on the team are excluded.

    Returns a list of dicts, sorted by score descending:
        [{"name": "Gholdengo", "score": 54.2, "paired_with": ["Great Tusk", "Kingambit"]}, ...]

    "score" is a simple additive co-occurrence sum - it is NOT a probability
    and isn't normalized, so it's only meaningful for ranking candidates
    relative to each other, not as an absolute number.
    """
    team_keys = set(normalize_name(name) for name in team_names)

    scores: dict[str, float] = defaultdict(float)
    paired_with: dict[str, list[str]] = defaultdict(list)
    display_names: dict[str, str] = {}

    for team_member in team_names:
        member_key = normalize_name(team_member)
        matches = teammates_df[teammates_df["name_key"] == member_key]

        for _, row in matches.iterrows():
            candidate_key = normalize_name(row["teammate"])

            if candidate_key in team_keys:
                continue  # already on the team, not a useful suggestion

            scores[candidate_key] += row["co_occurrence_pct"]
            paired_with[candidate_key].append(team_member.title())
            display_names[candidate_key] = row["teammate"]  # Smogon's display casing

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    results = []
    for candidate_key, score in ranked[:top_n]:
        results.append({
            "name": display_names[candidate_key],
            "score": round(score, 1),
            "paired_with": paired_with[candidate_key],
        })

    return results