"""
app.py

Streamlit dashboard: build a team of up to 6 Pokemon and see:
  - a type-coverage heatmap (where the team is collectively weak/resistant)
  - a stat comparison chart across the selected team

Run with:
    streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.name_utils import normalize_name
from src.recommend import recommend_teammates
from src.type_chart import ALL_TYPES, team_weaknesses

DATA_FILE = Path(__file__).resolve().parent / "data" / "pokemon_clean.csv"
USAGE_SUMMARY_FILE = Path(__file__).resolve().parent / "data" / "usage_summary.csv"
TEAMMATES_FILE = Path(__file__).resolve().parent / "data" / "teammates.csv"
STAT_COLS = ["hp", "attack", "defense", "special_attack", "special_defense", "speed"]

st.set_page_config(page_title="Pokemon Team Builder", page_icon="🎮", layout="wide")


@st.cache_data
def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        st.error(
            "No data found. Run `python src/fetch_data.py` then "
            "`python src/clean_data.py` first."
        )
        st.stop()
    df = pd.read_csv(DATA_FILE)
    df["name_key"] = df["name"].apply(normalize_name)
    return df


@st.cache_data
def load_usage_data() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """
    Loads Smogon usage summary + teammates data if available. Returns
    (None, None) if Stage 2 hasn't been run yet - the app should still work
    fine with just Stage 1 features in that case.
    """
    if not USAGE_SUMMARY_FILE.exists() or not TEAMMATES_FILE.exists():
        return None, None

    usage_df = pd.read_csv(USAGE_SUMMARY_FILE)
    usage_df["name_key"] = usage_df["pokemon"].apply(normalize_name)
    # Approximate "meta share" within each tier - real Smogon usage % is based
    # on a weighted count we don't have access to from the moveset file alone,
    # so this uses raw_count as a stand-in, normalized per-tier so tiers with
    # very different sample sizes stay comparable.
    usage_df["usage_share_pct"] = usage_df.groupby("tier")["raw_count"].transform(
        lambda counts: counts / counts.sum() * 100
    )

    teammates_df = pd.read_csv(TEAMMATES_FILE)
    teammates_df["name_key"] = teammates_df["pokemon"].apply(normalize_name)

    return usage_df, teammates_df


def get_types(df: pd.DataFrame, name: str) -> list[str]:
    row = df[df["name"] == name].iloc[0]
    types = [row["type_1"]]
    if pd.notna(row["type_2"]):
        types.append(row["type_2"])
    return types


def detect_tier(usage_df: pd.DataFrame, pokemon_name: str) -> str | None:
    """
    Given a Pokemon, find the tier it's most commonly used in (highest raw
    count among tiers it appears in). Returns None if we have no usage data
    for it in any tier.
    """
    key = normalize_name(pokemon_name)
    matches = usage_df[usage_df["name_key"] == key]
    if matches.empty:
        return None
    return matches.sort_values("raw_count", ascending=False).iloc[0]["tier"]


def names_in_tier(usage_df: pd.DataFrame, tier: str) -> set[str]:
    """Set of name_keys that appear in a given tier's usage data."""
    return set(usage_df[usage_df["tier"] == tier]["name_key"])


def render_type_coverage(df: pd.DataFrame, team_names: list[str]):
    st.subheader("Type Coverage")
    st.caption(
        "How your team holds up defensively against each attacking type. "
        "Red = weak (takes extra damage), green = resists, gray = no effect."
    )

    team_types = [get_types(df, name) for name in team_names]
    weaknesses = team_weaknesses(team_types)

    # Build a matrix: rows = team members, columns = attacking types
    z = [[weaknesses[t][i] for t in ALL_TYPES] for i in range(len(team_names))]

    # Custom text labels so 0.25/4.0 etc. read clearly instead of raw floats
    def label(mult: float) -> str:
        if mult == 0:
            return "0"
        if mult == 1:
            return ""
        if mult < 1:
            return f"{mult:g}x"
        return f"{mult:g}x"

    text = [[label(v) for v in row] for row in z]

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[t.title() for t in ALL_TYPES],
            y=team_names,
            text=text,
            texttemplate="%{text}",
            colorscale=[
                [0.0, "#6b7280"],   # 0x - gray (immune)
                [0.2, "#22c55e"],   # resists - green
                [0.4, "#e5e7eb"],   # neutral - light gray
                [0.6, "#f97316"],   # weak - orange
                [1.0, "#dc2626"],   # very weak - red
            ],
            zmin=0,
            zmax=4,
            showscale=False,
            hovertemplate="%{y} vs %{x}: %{z}x<extra></extra>",
        )
    )
    fig.update_layout(height=120 + 40 * len(team_names), margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    # Team-wide summary: which types hit 3+ team members super effectively
    st.markdown("**Shared weaknesses (2+ team members hit for 2x or more):**")
    shared = []
    for t in ALL_TYPES:
        count = sum(1 for m in weaknesses[t] if m >= 2.0)
        if count >= 2:
            shared.append((t.title(), count))
    if shared:
        for type_name, count in sorted(shared, key=lambda x: -x[1]):
            st.write(f"- **{type_name}**: hits {count} of your team members hard")
    else:
        st.write("No major shared weaknesses found. Nice balance!")


def render_stat_comparison(df: pd.DataFrame, team_names: list[str]):
    st.subheader("Stat Comparison")

    team_df = df[df["name"].isin(team_names)].set_index("name").loc[team_names]

    fig = go.Figure()
    for name in team_names:
        fig.add_trace(
            go.Scatterpolar(
                r=team_df.loc[name, STAT_COLS].values,
                theta=[c.replace("_", " ").title() for c in STAT_COLS],
                fill="toself",
                name=name.title(),
            )
        )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 200])),
        height=450,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Base stat totals:**")
    totals = team_df[STAT_COLS].sum(axis=1).sort_values(ascending=False)
    st.bar_chart(totals)


def render_usage_share(usage_df: pd.DataFrame, team_names: list[str], tier_label: str):
    st.subheader(f"Competitive Usage ({tier_label})")
    st.caption(
        "Approximate meta share among competitively-played teams, based on "
        "Smogon usage stats. Pokemon with no bar likely aren't commonly used "
        "in this tier."
    )

    team_keys = [normalize_name(name) for name in team_names]
    rows = []
    for display_name, key in zip(team_names, team_keys):
        match = usage_df[usage_df["name_key"] == key]
        usage_pct = round(match.iloc[0]["usage_share_pct"], 2) if not match.empty else 0
        rows.append({"Pokemon": display_name.title(), "Usage Share": usage_pct})

    usage_table = pd.DataFrame(rows).set_index("Pokemon")
    st.bar_chart(usage_table["Usage Share"])


def render_teammate_suggestions(teammates_df: pd.DataFrame, team_names: list[str]):
    st.subheader("Suggested Teammates (from real usage data)")
    st.caption(
        "What competitive players most often pair with each of your team members. "
        "Already-selected teammates are marked."
    )

    team_keys = set(normalize_name(name) for name in team_names)
    any_matches = False

    for display_name in team_names:
        key = normalize_name(display_name)
        matches = teammates_df[teammates_df["name_key"] == key].sort_values(
            "co_occurrence_pct", ascending=False
        )

        if matches.empty:
            continue

        any_matches = True
        st.markdown(f"**{display_name.title()}**")
        for _, row in matches.head(5).iterrows():
            teammate_key = normalize_name(row["teammate"])
            already_on_team = teammate_key in team_keys
            marker = " ✅ *(already on your team)*" if already_on_team else ""
            st.write(f"- {row['teammate']} — {row['co_occurrence_pct']:.1f}%{marker}")

    if not any_matches:
        st.info("No competitive teammate data found for this team.")


def render_recommendations(teammates_df: pd.DataFrame, team_names: list[str]):
    st.subheader("Recommended Additions")
    st.caption(
        "Ranked by combined real-world synergy with your whole team - a Pokemon "
        "that pairs well with multiple team members ranks above one that only "
        "pairs well with one."
    )

    if len(team_names) >= 6:
        st.info("Your team is full (6/6) - remove someone to see new recommendations.")
        return

    recommendations = recommend_teammates(teammates_df, team_names, top_n=8)

    if not recommendations:
        st.info("No recommendations found - try adding a more commonly-used competitive Pokemon.")
        return

    for rec in recommendations:
        paired_str = ", ".join(rec["paired_with"])
        st.write(f"**{rec['name']}** — synergy score {rec['score']} (pairs well with {paired_str})")


def main():
    df = load_data()
    usage_df, teammates_df = load_usage_data()
    has_tier_data = usage_df is not None and teammates_df is not None

    st.title("🎮 Pokemon Team Builder")
    st.caption("Build a team and see how it stacks up defensively and statistically.")

    selected_tier = None
    all_options = sorted(df["name"].str.title())

    if has_tier_data:
        tiers = sorted(usage_df["tier"].unique())
        mode = st.radio(
            "How do you want to start?",
            ["Pick a tier first", "Pick a Pokemon first"],
            horizontal=True,
        )

        if mode == "Pick a tier first":
            selected_tier = st.selectbox("Competitive tier", tiers)
            allowed_keys = names_in_tier(usage_df, selected_tier)
            options = sorted(
                df[df["name_key"].isin(allowed_keys)]["name"].str.title()
            )
            if not options:
                st.warning(f"No dex data matches any Pokemon used in {selected_tier}.")
                options = all_options
            team_names = st.multiselect(
                f"Pick up to 6 Pokemon used in {selected_tier}:",
                options=options,
                max_selections=6,
            )
        else:
            team_names = st.multiselect(
                "Pick up to 6 Pokemon for your team:",
                options=all_options,
                max_selections=6,
            )
            if team_names:
                detected = detect_tier(usage_df, team_names[0])
                if detected:
                    selected_tier = detected
                    st.info(f"Detected tier: **{selected_tier}** (based on {team_names[0]})")
                else:
                    st.info(
                        f"No competitive usage data found for {team_names[0]} in any tier - "
                        "usage/teammate sections below will be unavailable for this team."
                    )
    else:
        team_names = st.multiselect(
            "Pick up to 6 Pokemon for your team:",
            options=all_options,
            max_selections=6,
        )

    team_names = [n.lower() for n in team_names]

    if not team_names:
        st.info("Select at least one Pokemon above to get started.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        render_type_coverage(df, team_names)
    with col2:
        render_stat_comparison(df, team_names)

    if has_tier_data and selected_tier:
        tier_usage_df = usage_df[usage_df["tier"] == selected_tier]
        tier_teammates_df = teammates_df[teammates_df["tier"] == selected_tier]

        st.divider()
        col3, col4 = st.columns([1, 1])
        with col3:
            render_usage_share(tier_usage_df, team_names, selected_tier)
        with col4:
            render_teammate_suggestions(tier_teammates_df, team_names)

        st.divider()
        render_recommendations(tier_teammates_df, team_names)
    elif not has_tier_data:
        st.caption(
            "Tip: run `fetch_usage_data.py` and `parse_usage_data.py` to unlock "
            "real competitive usage data and teammate suggestions."
        )


if __name__ == "__main__":
    main()