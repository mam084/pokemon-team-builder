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

from src.type_chart import ALL_TYPES, team_weaknesses

DATA_FILE = Path(__file__).resolve().parent / "data" / "pokemon_clean.csv"
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
    return pd.read_csv(DATA_FILE)


def get_types(df: pd.DataFrame, name: str) -> list[str]:
    row = df[df["name"] == name].iloc[0]
    types = [row["type_1"]]
    if pd.notna(row["type_2"]):
        types.append(row["type_2"])
    return types


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


def main():
    df = load_data()

    st.title("🎮 Pokemon Team Builder")
    st.caption("Build a team and see how it stacks up defensively and statistically.")

    team_names = st.multiselect(
        "Pick up to 6 Pokemon for your team:",
        options=sorted(df["name"].str.title()),
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


if __name__ == "__main__":
    main()