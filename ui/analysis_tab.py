"""Analysis tab: defensive heatmap, role checklist, speed tiers, coverage, stats."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import (coverage_vs_meta, defense_matrix, defense_summary, offense_by_type, role_checklist,
                          speed_table)
from src.dex import STAT_LABELS, STATS
from ui.common import fmt_mult, matchup_scale, palette

def matchup_heatmap(matrix: pd.DataFrame) -> go.Figure:
    import numpy as np
    z = np.where(matrix.values == 0, -2.5, np.log2(matrix.values.clip(min=0.25)))
    text = matrix.map(fmt_mult).values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(matrix.columns), y=list(matrix.index), text=text, texttemplate="%{text}",
        zmin=-2.5, zmax=2, colorscale=matchup_scale(), showscale=False, xgap=2, ygap=2,
        customdata=matrix.values,
        hovertemplate="%{y} → %{x}: %{customdata}× damage<extra></extra>",
    ))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    return fig


def speed_chart(df: pd.DataFrame, trick_room: bool) -> go.Figure:
    df = df.sort_values("speed", ascending=trick_room).reset_index(drop=True)
    p = palette()
    colors = [p["blue"] if w == "Your team" else p["context"] for w in df["who"]]
    fig = go.Figure(go.Bar(
        x=df["speed"], y=df["pokemon"], orientation="h", marker_color=colors,
        text=df["speed"], textposition="outside", cliponaxis=False,
        customdata=df[["who", "note"]], hovertemplate="%{y}: %{x} Speed<br>%{customdata[0]} %{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(height=max(320, 24 * len(df)), margin=dict(l=10, r=40, t=10, b=10),
                      yaxis=dict(autorange="reversed"), xaxis_title="Speed at level 50", bargap=0.25)
    return fig


def fit_check_section(team, dex, usage) -> None:
    """How your team compares to what players build, from the learned teammate model: is it an
    off-meta build, which of your picks players pair with each other, and how usual each is."""
    from src.recommend import HIDDEN_MAX
    tm = usage.teammates if usage is not None else None
    if tm is None or len(team) < 3:
        return
    forms = [p.battle_form(dex) for p in team]
    roots = [dex.sheet_id(f) for f in forms]
    sheet = usage.team_sheet_usage(dex)
    share = [sheet.get(usage.sheet_name(f.name, dex) or "", 0.0) for f in forms]
    rare = sum(1 for x in share if x < HIDDEN_MAX)
    checks = {r["root"]: r for r in tm.fit_check(roots)}
    links = tm.links(roots)
    by_root = {dex.sheet_id(f): p.species for p, f in zip(team, forms)}

    st.subheader("How your team compares to what players build")
    off_meta = rare >= (len(team) + 1) // 2
    if off_meta:
        st.markdown(f"**Off-meta build.** {rare} of your {len(team)} are on fewer than {HIDDEN_MAX:.0f}% of ladder "
                    "teams, so the meta's usual pairings mostly don't apply. What still helps: which of your own "
                    "picks players *do* run together (proven partnerships), and which are new territory.")
    else:
        natural = sum(1 for r in checks.values() if r["rank"] and r["rank"] <= 15)
        st.markdown(f"**{natural} of {len(team)}** are natural fits with the rest: among the 15 Pokémon players "
                    "most often pick next to your other members.")
    lines = []
    for p, f, r, use in zip(team, forms, roots, share):
        c, link = checks.get(r) or {}, links.get(r)
        partner = (f"pairs best with **{by_root.get(link[0], link[0])}** ({math.exp(link[1]):.1f}x as likely "
                   "together)" if link and link[1] >= 0.3 else "no proven partner on your team yet")
        if not c or c.get("rank") is None:
            usual = "too rarely used to judge"
        elif c["rank"] <= 3:
            usual = f"a top pick next to the rest (#{c['rank']})"
        elif c["rank"] <= 15:
            usual = f"a natural pick next to the rest (#{c['rank']})"
        else:
            usual = f"rarely seen with this group (#{c['rank']} of {len(tm.vocab)})"
        if off_meta and not (c and c.get("rank") and c["rank"] <= 15):
            usual = ""  # on an off-meta build "rare next to this group" says nothing new
        lines.append(f"- **{p.species}** ({use:.1f}% of teams): {partner}" + (f"; {usual}." if usual else "."))
    st.markdown("\n".join(lines))
    st.caption("From real tournament team lists and ladder replays. \"4.5x\" means players are 4.5 times as likely "
               "to run the two together, all else equal. This is about how usual a team is, not how good: an "
               "off-meta pick can be the surprise that wins games.")
    with st.expander("What players usually run in each spot"):
        name = {dex.sheet_id(s): s.name for s in dex.selectable_species() if not dex.is_cosmetic(s)}
        st.caption("For each member: the Pokémon players most often pick alongside your other five instead. "
                   "Each spot is judged against a different five, so the same name can come up more than once.")
        st.markdown("\n".join(
            f"- **{p.species}**: " + ", ".join(name.get(x, x) for x, _ in (checks.get(r) or {}).get("instead", []))
            for p, r in zip(team, roots) if (checks.get(r) or {}).get("instead")))


def analysis_tab(team, members, dex, usage, fmt) -> None:
    if not members:
        st.info("Add Pokémon on the **Team** tab to see the analysis.")
        return
    fit_check_section(team, dex, usage)

    st.subheader("Defensive matchups")
    st.caption("Damage each attacking type deals to each member, with Mega forms and type-changing abilities "
               "(Levitate, Purifying Salt, Thick Fat…) applied. Red = weak, blue = resists.")
    matrix = defense_matrix(members)
    left, right = st.columns([3, 2])
    left.plotly_chart(matchup_heatmap(matrix), width="stretch")
    summary = defense_summary(matrix)
    flagged = summary[summary["verdict"] != ""]
    with right:
        if flagged.empty:
            st.success("No shared weaknesses - every type is answered by at least one resist.")
        else:
            st.markdown("**Types to watch**")
            st.dataframe(flagged, width="stretch")
        st.markdown("**Role checklist**")
        st.dataframe(role_checklist(members, fmt.is_doubles), hide_index=True, width="stretch",
                     column_config={"why it matters": st.column_config.TextColumn(width="medium")})

    st.subheader("Speed tiers")
    tr = st.toggle("Trick Room order (slowest first)", value=False)
    st.caption("Your team's real Speed stats next to the meta's most common spreads."
               + ("" if usage else " Add usage data to see meta benchmarks."))
    st.plotly_chart(speed_chart(speed_table(members, dex, usage, n=20), tr), width="stretch")

    st.subheader("Offensive coverage")
    c1, c2 = st.columns([2, 3])
    with c1:
        off = offense_by_type(members)
        st.caption("Best effectiveness your damaging moves get against each type.")
        st.dataframe(off.assign(best=off["best"].map(lambda x: fmt_mult(x) or "1×")),
                     width="stretch", height=420)
    with c2:
        if usage:
            st.caption("…and against the 30 most-used Pokémon, in their common battle form.")
            cov = coverage_vs_meta(members, dex, usage, n=30)
            cov["best hit"] = cov["best hit"].map(lambda x: fmt_mult(x) or "1×")
            st.dataframe(cov, hide_index=True, width="stretch", height=420)
        else:
            st.info("Coverage against the meta needs usage stats for this format.")

    st.subheader("Stats")
    rows = [{"Pokémon": m.label, **{STAT_LABELS[s]: m.stats[s] for s in STATS}} for m in members]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
