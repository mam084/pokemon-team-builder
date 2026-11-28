"""Analysis tab: defensive heatmap, role checklist, speed tiers, coverage, stats."""

from __future__ import annotations

import math
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import (coverage_vs_meta, defense_matrix, defense_summary, offense_by_type, role_checklist,
                          speed_table)
from src.dex import STAT_LABELS, STATS, load_dex
from src.formats import FORMATS
from src.usage import load_usage
from ui.theme import how_it_works
from ui.common import fmt_mult, jump_row, matchup_scale, palette, section

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

    section("How your team compares to what players build")
    all_top = len(team) > 1 and all((checks.get(r) or {}).get("rank") == 1 for r in roots)
    off_meta = rare >= (len(team) + 1) // 2
    if off_meta:
        st.markdown(f"**Off-meta build:** {rare} of your {len(team)} are on fewer than {HIDDEN_MAX:.0f}% of ladder "
                    "teams. Below, which of your own picks players *do* run together.")
    else:
        natural = sum(1 for r in checks.values() if r["rank"] and r["rank"] <= 15)
        st.markdown(f"**{natural} of {len(team)}** are natural fits: among the 15 Pokémon players most often pick "
                    "next to the rest of your team." + (" Each is the **#1** pick next to the rest: "
                    "a well-tested shell." if all_top else ""))
    lines = []
    for p, f, r, use in zip(team, forms, roots, share):
        c, link = checks.get(r) or {}, links.get(r)
        bits = [f"{use:.1f}% of teams"]
        bits.append(f"pairs best with {by_root.get(link[0], link[0])} ({math.exp(link[1]):.1f}x)"
                    if link and link[1] >= 0.3 else "no proven partner on your team")
        rank = c.get("rank") if c else None
        if all_top:
            pass   # said once above, not six times
        elif rank and rank <= 15:
            bits.append(f"#{rank} pick next to the rest")
        elif rank and not off_meta:
            bits.append("rare with this group")
        lines.append(f"- **{p.species}**: " + " · ".join(bits))
    st.markdown("\n".join(lines))
    st.caption("Learned from tournament team lists and ladder replays. 2.0x = players run the two together twice "
               "as often as chance. Usual isn't the same as good: an off-meta pick can be your surprise factor.")
    with st.expander("What players usually run in each spot"):
        name = {dex.sheet_id(s): s.name for s in dex.selectable_species() if not dex.is_cosmetic(s)}
        st.caption("For each member: the Pokémon players most often pick alongside your other five instead. "
                   "Each spot is judged against a different five, so the same name can come up more than once.")
        st.markdown("\n".join(
            f"- **{p.species}**: " + ", ".join(name.get(x, x) for x, _ in (checks.get(r) or {}).get("instead", []))
            for p, r in zip(team, roots) if (checks.get(r) or {}).get("instead")))


@st.cache_data(show_spinner=False, ttl=3600)
def _tournament_teams(regulation: str) -> list[dict]:
    from src.evaluate import load_tournament_teams
    from src.dex import load_dex
    try:
        return load_tournament_teams(regulation, load_dex(regulation))
    except (OSError, ValueError, KeyError):
        return []


def similar_teams_section(team, dex, regulation: str) -> None:
    """Real tournament teams that share most of yours, and how they did."""
    from src.similar_teams import find_similar, ordinal, top_cut
    teams = _tournament_teams(regulation)
    if not teams or len(team) < 3:
        return
    sims, need = find_similar(team, teams, dex)
    section("Tournament teams like yours")
    if not sims:
        st.markdown(f"None of the {len(teams):,} tournament teams we have run {need} or more of your Pokémon, "
                    "so there are no results for a team like this yet.")
        return
    w, l = sum(x.wins for x in sims), sum(x.losses for x in sims)
    all_w, all_l = sum(int(t.get("wins") or 0) for t in teams), sum(int(t.get("losses") or 0) for t in teams)
    rate, base = w / max(w + l, 1), all_w / max(all_w + all_l, 1)
    cut = sum(top_cut(x) for x in sims)
    st.markdown(f"**{len(sims)} teams** share {need}+ of your Pokémon. Together they went **{w}–{l} "
                f"({rate:.0%})**, against {base:.0%} for all tournament teams" + (f"; {cut} made top 8." if cut else "."))
    name = {dex.sheet_id(sp): sp.name for sp in dex.selectable_species() if not dex.is_cosmetic(sp)}
    lines = []
    for x in sims[:5]:
        place = f"{ordinal(x.placing)} of {x.players}" if x.placing else f"{x.players} players"
        swap = (f"{', '.join(name.get(r, r) for r in x.extra)} instead of {', '.join(name.get(r, r) for r in x.missing)}"
                if x.missing else "your exact team" if not x.extra else f"plus {', '.join(name.get(r, r) for r in x.extra)}")
        lines.append(f"- **{place}** ({x.wins}–{x.losses}), {x.date[5:].replace('-', '/')}: {swap}")
    st.markdown("\n".join(lines))
    st.caption("From Limitless tournament team lists for this regulation; best finishes first. Records include "
               "players who dropped, which is why the average is under 50%.")


def _covered_by(text: str) -> str:
    """'Conkeldurr (Wide Guard); Araquanid (Wide Guard)' -> 'Conkeldurr, Araquanid (Wide Guard)'."""
    parts = [x.strip() for x in str(text).split(";") if x.strip()]
    pairs = [re.match(r"^(.*?)(?: \((.*)\))?$", x).groups() for x in parts]
    tools = {tool for _, tool in pairs}
    if len(tools) == 1 and None not in tools:
        return f"{', '.join(n for n, _ in pairs)} ({tools.pop()})"
    return ", ".join(f"{n} ({tool})" if tool else n for n, tool in pairs)


@st.cache_data(show_spinner=False, max_entries=64)
def cached_paper(fmt_id: str, key: str) -> dict | None:
    from src.analysis import mega_variants
    from src.match_model import team_side
    from src.paper_report import breakdown
    from ui.matchups_tab import _unkey, archetypes_for, learned_meta_sides, swap_engine_for
    model, sides = learned_meta_sides(fmt_id)
    if model is None or not sides:
        return None
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    team = _unkey(key)
    engine = swap_engine_for(fmt_id)
    mine = [team_side(m, team, dex, usage, engine) for _, m in mega_variants(team, dex)]
    archs = archetypes_for(fmt_id)
    return breakdown(model, mine, sides, [a.name for a in archs], [a.popularity for a in archs])


def paper_section(team, dex, usage, fmt) -> None:
    """Why the team rates as it does on paper, and what would make it stronger (src/paper_report.py)."""
    if usage is None or len(team) < 2:
        return
    from src.match_model import cap_chance
    from src.team_rating import lenses, load_reference
    from ui.matchups_tab import learned_meta_sides, team_key
    section("Why it rates this way on paper")
    report = cached_paper(fmt.id, team_key(team))
    if not report or not report["chances"]:
        st.caption("Needs the learned win model for this format.")
        return
    avg = cap_chance(learned_meta_sides(fmt.id)[0], report["average"])   # as the Matchups tab grades it
    seen = lenses(team, dex, usage, avg, load_reference(fmt.regulation)) if len(team) == 6 else None
    if seen:
        paper, pct = seen["paper"]
        st.markdown(f"**On paper: {paper}.** Its matchups against the meta teams beat {pct:.0f}% of "
                    "tournament teams'. Here's what the win model sees, averaged over the meta teams.")
    else:
        st.markdown("What the win model sees in your team, averaged over the meta teams "
                    "(the grade needs all six).")
    costs = [(g, v, fix) for g, v, fix in report["parts"] if v < 0]
    gains = sorted(((g, v) for g, v, _ in report["parts"] if v > 0), key=lambda kv: -kv[1])
    if costs:
        st.markdown("**What costs it points**, and what would help  \n" + "  \n".join(
            f"**{g}** ({v:+.1f} pts): {fix}" for g, v, fix in costs[:4]))
    else:
        st.success("Nothing costs it points against the meta teams on average.")
    if gains:
        st.markdown("**What it does well:** " + ", ".join(f"{g} ({v:+.1f} pts)" for g, v in gains[:4]))
    if report["toughest"]:
        st.markdown("**Toughest meta teams:** " + ", ".join(
            f"{name} ({p:.0%})" for name, p in report["toughest"]))
    how_it_works(
        "The learned win model (Matchups tab) explains each matchup as pushes on the odds of winning: damage "
        "calcs, Speed, bulk, support tools and per-Pokémon effects learned from real games. These are those "
        "pushes averaged over the meta teams (weighted by how common each is), in win-percentage points "
        "against the average meta team. They compare you with the meta teams; the grade compares you with "
        "tournament teams. A support tool's line describes what the model learned from real games, which "
        "can be small or noisy, so treat those as hints. The **swaps on the Matchups tab** test actual "
        "replacements against the same model.", "How this is worked out")


def analysis_tab(team, members, dex, usage, fmt) -> None:
    if not members:
        st.info("Add Pokémon on the **Team** tab to see the analysis.")
        return
    jump_row(["Why it rates this way on paper", "Tournament teams like yours", "Defensive matchups",
              "Role checklist", "Speed tiers", "Offensive coverage"])
    paper_section(team, dex, usage, fmt)
    fit_check_section(team, dex, usage)
    similar_teams_section(team, dex, fmt.regulation)

    section("Defensive matchups")
    matrix = defense_matrix(members)
    summary = defense_summary(matrix)
    flagged = summary[summary["verdict"] != ""]
    if flagged.empty:
        st.success("No shared weaknesses: every type is resisted by at least one member.")
    else:
        st.markdown("  \n".join(
            f"**{t}:** {r['verdict'].lower()} ({r['weak']} weak" + (f", {r['4x']} take 4x" if r["4x"] else "")
            + f", {r['resist'] + r['immune']} resist)" for t, r in flagged.iterrows()))
    st.plotly_chart(matchup_heatmap(matrix), width="stretch")
    st.caption("Damage each attacking type does to each member (Mega forms and abilities like Levitate or "
               "Purifying Salt applied). Red = weak, blue = resists.")

    section("Role checklist")
    roles = role_checklist(members, fmt.is_doubles)
    missing = roles[roles["status"].isin(["Missing", "Partly"])]
    optional = roles[roles["status"] == "Optional"]
    covered = roles[roles["status"] == "Yes"]
    if len(missing):
        st.markdown("**Missing:** " + ", ".join(f"{r['role']}" + (" (partly)" if r["status"] == "Partly" else "")
                                                for _, r in missing.iterrows()))
    if len(covered):
        st.markdown("**Covered**  \n" + "  \n".join(f"✓ {r['role']}: {_covered_by(r['covered by'])}"
                                                    for _, r in covered.iterrows()))
    if len(optional):
        st.caption("Not on the team (optional): " + ", ".join(optional["role"]))
    with st.expander("Why each role matters"):
        st.dataframe(roles, hide_index=True, width="stretch",
                     column_config={"why it matters": st.column_config.TextColumn(width="medium")})

    section("Speed tiers")
    tr = st.toggle("Trick Room order (slowest first)", value=False)
    st.caption("Your Pokémon's Speed (with their Stat Points and nature) next to the meta's most common spreads."
               + ("" if usage else " Add usage data to see meta benchmarks."))
    st.plotly_chart(speed_chart(speed_table(members, dex, usage, n=20), tr), width="stretch")

    section("Offensive coverage")
    off = offense_by_type(members)
    weak_types = [t for t, r in off.iterrows() if r["best"] < 2]
    st.markdown(("**No super-effective hit on:** " + ", ".join(
        f"{t} (best {fmt_mult(off.loc[t, 'best']) or '1×'})" for t in weak_types)) if weak_types
        else "**Every type** is hit super effectively by at least one of your moves.")
    cov = coverage_vs_meta(members, dex, usage, n=30) if usage else pd.DataFrame()
    if not cov.empty:
        walls = cov[cov["best hit"] < 2]
        st.markdown(("**Popular Pokémon you can't hit super effectively:** " + ", ".join(
            f"{r['pokemon']} ({r['usage %']:.0f}%)" for _, r in walls.iterrows())) if not walls.empty
            else "You hit **all 30** of the most-used Pokémon super effectively.")
    with st.expander("Full coverage tables and stats"):
        st.dataframe(off.assign(best=off["best"].map(lambda x: fmt_mult(x) or "1×")).rename(
            columns={"hit_by": "hit by"}), width="stretch")
        if not cov.empty:
            cov["best hit"] = cov["best hit"].map(lambda x: fmt_mult(x) or "1×")
            st.dataframe(cov, hide_index=True, width="stretch")
        rows = [{"Pokémon": m.label, **{STAT_LABELS[s]: m.stats[s] for s in STATS}} for m in members]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
