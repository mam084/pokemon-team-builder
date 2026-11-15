"""Matchups tab: team vs rebuilt meta teams, pairing heatmaps, counters and threats."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import load_dex
from src.formats import FORMATS
from src.analysis import build_members, mega_variants
from src.matchup import (best_attack, best_variant, build_archetypes, counter_picks, meta_matchups,
                         opponent_members, team_score, threat_report, verdict)
from src.gameplan import game_plan
from src.recommend import MODES
from src.roles import meta_roles, role_text
from src.swaps import HIDDEN_SKIP, SwapEngine, mode_pool, suggest_swaps
from src.team import PokemonSet
from src.usage import load_usage
from ui.common import matchup_scale, sprite, type_badges
from ui.state import write_slot
from ui.theme import how_it_works

@st.cache_resource(show_spinner=False)
def archetypes_for(fmt_id: str):
    fmt = FORMATS[fmt_id]
    usage = load_usage(fmt_id)
    if usage is None:
        return []
    return build_archetypes(usage, load_dex(fmt.regulation), team_size=6)


def team_key(team) -> str:
    """A hashable fingerprint of the team for st.cache_data."""
    return json.dumps([p.to_dict() for p in team], sort_keys=True)


def _unkey(key: str) -> list[PokemonSet]:
    return [PokemonSet.from_dict(d) for d in json.loads(key)]


# The heavy tables only change when the team does, so they're cached on the team's
# contents: tapping anything else (a tab, a selectbox) no longer recomputes them.
@st.cache_data(show_spinner=False, max_entries=64)
def cached_meta_matchups(fmt_id: str, key: str) -> pd.DataFrame:
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    return meta_matchups(mega_variants(_unkey(key), dex), archetypes_for(fmt_id), usage, dex,
                         bring=fmt.pick, doubles=fmt.is_doubles)


@st.cache_data(show_spinner=False, max_entries=64)
def cached_threats(fmt_id: str, key: str) -> pd.DataFrame:
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    doubles = fmt.is_doubles
    threats = threat_report(build_members(_unkey(key), dex), usage, dex, n=30, doubles=doubles)
    if not threats.empty:
        threats["meta counters"] = [
            ", ".join(counter_picks(opponent_members([name], usage, dex), usage, dex, pool=50, top_n=3,
                                    doubles=doubles)["pokemon"])
            if i < 10 else "—"
            for i, name in enumerate(threats["pokemon"])
        ]
    return threats


@st.cache_data(show_spinner=False, max_entries=128)
def cached_swaps(fmt_id: str, key: str, focus: str | None, mode: str, same_role: bool,
                 per_member: int | None) -> pd.DataFrame:
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    return suggest_swaps(_unkey(key), dex, usage, swap_engine_for(fmt_id), focus=focus,
                         pool=mode_pool(usage, mode, dex), top_n=8, same_role=same_role, per_member=per_member)


def pair_scale() -> list:
    """Diverging red (their side wins) -> neutral -> blue (yours wins)."""
    scale = matchup_scale()
    weak_strong, weak_soft, mid = scale[5][1], scale[4][1], scale[3][1]
    light_r, strong = scale[2][1], scale[0][1]
    return [[0, weak_strong], [0.33, weak_soft], [0.5, mid], [0.67, light_r], [1, strong]]


def pair_heatmap(matrix: pd.DataFrame) -> go.Figure:
    z = matrix.clip(-3, 3).values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(matrix.columns), y=list(matrix.index), text=matrix.round(1).values,
        texttemplate="%{text:+.1f}", zmin=-3, zmax=3, xgap=2, ygap=2, showscale=False,
        colorscale=pair_scale(),
        hovertemplate="%{y} vs %{x}: %{z:+.1f}<extra></extra>",
    ))
    fig.update_layout(height=80 + 46 * len(matrix.index), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    return fig


def matchups_tab(fmt_id, team, members, dex, usage, fmt) -> None:
    if usage is None:
        st.info("Matchups need usage stats for this format.")
        return
    archetypes = archetypes_for(fmt_id)
    doubles = fmt.is_doubles
    st.subheader("Against the meta")
    how_it_works(
        "- **Meta teams** are rebuilt from Smogon teammate data: start from a popular Pokémon and keep adding "
        "whoever is most often paired with the whole team so far. Each opponent uses its most popular set.\n"
        "- **Each pairing** is decided by real damage calcs both ways. A pair scores +1 when your Pokémon needs "
        "half as many hits to KO theirs as they need to KO yours, and ±0.5 for Speed (reversed under Trick "
        "Room). Weather teams are scored in their weather.\n"
        "- **Team score** is how well you answer them minus how well they answer you, so 0 is even. "
        "With two Mega Stones, each matchup uses whichever Mega Evolves best.",
        "How matchups are scored")
    if not members:
        st.info("Add Pokémon on the **Team** tab to see how you match up. The meta teams are listed below.")
    else:
        variants = mega_variants(team, dex)
        table = cached_meta_matchups(fmt_id, team_key(team))
        if len(variants) < 2:
            table = table.drop(columns=["mega evolve"])
        weights = table["popularity"]
        overall = float((table["score"] * weights).sum() / weights.sum()) if len(table) else 0.0
        c = st.container(key="metric_row").columns(4)
        c[0].metric("Overall", f"{overall:+.2f}", help="Usage-weighted average of the team scores below")
        c[0].caption(verdict(overall))
        c[1].metric("Favorable", int((table["score"] >= 0.25).sum()))
        c[2].metric("Even", int(((table["score"] > -0.25) & (table["score"] < 0.25)).sum()))
        c[3].metric("Unfavorable", int((table["score"] <= -0.25).sum()))
        # score next to the name, so it's visible without scrolling sideways on a phone
        first = ["archetype", "score", "verdict"]
        table = table[first + [c for c in table.columns if c not in first]]
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "archetype": st.column_config.TextColumn("meta team", width="medium"),
                "popularity": st.column_config.NumberColumn("avg usage %", format="%.1f"),
                "score": st.column_config.NumberColumn("score", format="%+.2f"),
                "with bring": st.column_config.NumberColumn(f"score with bring {fmt.pick}", format="%+.2f"),
            },
        )

    st.subheader("Matchup detail")
    names = [a.name for a in archetypes]
    if not names:
        st.info("Not enough usage data to build meta teams.")
        return
    pick = st.selectbox("Meta team", names)
    arch = archetypes[names.index(pick)]
    theirs = opponent_members(arch.members, usage, dex)
    cards = "".join(
        f"<div class='opp-card'><img src='{sprite(opp.form, dex)}' alt=''>"
        f"<div class='opp-name'>{opp.label}</div><div>{type_badges(opp.form.types)}</div>"
        f"<div class='opp-meta'>{opp.pset.item or 'No item'} · "
        f"{role_text(meta_roles(arch.members[i], usage, dex, doubles), 2)}</div></div>"
        for i, opp in enumerate(theirs))
    st.markdown(f"<div class='opp-grid'>{cards}</div>", unsafe_allow_html=True)
    notes = []
    if arch.trick_room:
        notes.append("This team sets Trick Room, so slower Pokémon get the Speed bonus.")
    if arch.weather:
        notes.append(f"Calcs are done in {arch.weather}, which this team sets.")
    if notes:
        st.caption(" ".join(notes))

    if members:
        variants = mega_variants(team, dex)
        who, matrix, picks, picked = best_variant(variants, theirs, arch.trick_room, doubles, arch.weather,
                                                  fmt.pick)
        members_now = next(ms for w, ms in variants if w == who)
        score = team_score(matrix)
        if len(variants) > 1:
            st.caption(f"You carry {len(variants)} Mega Stones; against this team, **Mega Evolve {who}** "
                       "(the other plays in its base forme).")
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Your team vs {pick}: {score:+.2f} ({verdict(score)})**")
            st.plotly_chart(pair_heatmap(matrix), width="stretch")
            st.caption("Blue = your Pokémon (row) wins that pairing, red = theirs (column) does.")
        with right:
            st.markdown(f"**Suggested bring {fmt.pick}:** {', '.join(picks)} ({picked:+.2f})")
            answers = []
            for opp in theirs:
                col = matrix[opp.label]
                best = col.idxmax()
                mine = next(m for m in members_now if m.label == best)
                pct, move = best_attack(mine, opp, doubles, arch.weather)
                answers.append({
                    "their Pokémon": opp.label,
                    "your best answer": best if col.max() >= 0.5 else "—",
                    "key calc": f"{move} {pct:.0f}%" if col.max() >= 0.5 and move else "—",
                })
            st.dataframe(pd.DataFrame(answers), hide_index=True, width="stretch")
        plan = game_plan(members_now, theirs, matrix, picks, dex, doubles, arch.trick_room, arch.weather)
        game_plan_box(plan, who if len(variants) > 1 else None)

    st.markdown(f"**Counter picks for {pick}**: meta Pokémon (popular sets) with the best average pairing "
                "against this team" + (", not counting your current team." if team else "."))
    counters = counter_picks(theirs, usage, dex, exclude={p.species for p in team},
                             trick_room=arch.trick_room, doubles=doubles, weather=arch.weather)
    if not counters.empty:
        counters.insert(1, "usually plays", [role_text(meta_roles(n, usage, dex, doubles), 2)
                                             for n in counters["pokemon"]])
        st.dataframe(counters, hide_index=True, width="stretch",
                     column_config={"avg matchup": st.column_config.NumberColumn(format="%+.2f")})

    threats = threats_section(fmt_id, team, members, dex, usage, doubles)
    swaps_section(team, dex, usage, fmt, threats)


def game_plan_box(plan, mega: str | None) -> None:
    with st.container(border=True):
        st.markdown("**Game plan**")
        lines = [f"**Bring:** {', '.join(plan.bring)}" + (f" (Mega Evolve {mega})" if mega else ""),
                 f"**Lead:** {' + '.join(plan.lead)}. {plan.lead_why}",
                 f"**In the back:** {', '.join(plan.back)}" if plan.back else "",
                 f"**Expect them to lead:** {' + '.join(plan.their_leads)}",
                 f"**Your strongest piece:** {plan.strongest} ({plan.strongest_why})" if plan.strongest else ""]
        st.markdown("  \n".join(line for line in lines if line))
        if plan.watch_out:
            st.markdown("**Watch out for**  \n" + "  \n".join(
                f"- **{w['pokemon']}**: {w['hit']}; {w['your best']}." for w in plan.watch_out))
        else:
            st.markdown("**Watch out for:** nothing on their team goes unanswered by your bring.")
        order, prev = [], None
        for r in plan.speed:
            name = f"**{r['pokemon']}**" if r["side"] == "yours" else r["pokemon"]
            sep = "" if prev is None else (" = " if r["speed"] == prev else " › ")
            order.append(f"{sep}{name} {r['speed']}")
            prev = r["speed"]
        st.caption("Speed order (yours in bold): " + "".join(order)
                   + (f". {plan.speed_note}" if plan.speed_note else ""))


def threats_section(fmt_id: str, team, members, dex, usage, doubles: bool) -> pd.DataFrame:
    st.subheader("Biggest threats to your team")
    if not members:
        st.info("Add Pokémon on the **Team** tab to see which popular Pokémon threaten you.")
        return pd.DataFrame()
    how_it_works("The 30 most-used Pokémon (popular sets), ranked by **usage × (your Pokémon it 2HKOs + 1) ÷ "
                 "(answers + 1)**. An *answer* 2HKOs it back while taking under 50%. **Meta counters** are the "
                 "Pokémon with the best pairing against it, if you want to add one.", "How threats are ranked")
    threats = cached_threats(fmt_id, team_key(team))
    if threats.empty:
        return threats
    cols = st.columns(3)
    for i, row in threats.head(3).iterrows():
        with cols[i]:
            with st.container(border=True):
                form = dex.get_species(row["pokemon"])
                img = f"<img class='card-sprite' src='{sprite(form, dex)}' alt=''>" if form else ""
                st.markdown(f"<div class='card-head'>{img}<div><b>{row['pokemon']}</b><br>"
                            f"{row['usage %']:.1f}% usage</div></div>", unsafe_allow_html=True)
                st.caption(f"2HKOs {row['2HKOs']} of your team. Hardest hits: {row['hardest hits']}. "
                           f"Your answers: {row['answers']}.")
    st.dataframe(threats, hide_index=True, width="stretch",
                 column_config={"threat score": st.column_config.ProgressColumn(
                     "threat score", min_value=0, max_value=float(threats["threat score"].max() or 1),
                     format="%.1f")})
    return threats


@st.cache_resource(show_spinner=False)
def swap_engine_for(fmt_id: str) -> SwapEngine:
    fmt = FORMATS[fmt_id]
    return SwapEngine(archetypes_for(fmt_id), load_usage(fmt_id), load_dex(fmt.regulation), fmt.is_doubles)


def swaps_section(team, dex, usage, fmt, threats: pd.DataFrame) -> None:
    st.subheader("Suggested swaps")
    if len(team) < 2:
        st.info("Swaps need at least two Pokémon on your team.")
        return
    st.caption("Replace one member with a Pokémon that fixes a problem without hurting the overall matchup.")
    if st.session_state.get("swap_mode") not in MODES:  # start from the Recommendations tab's style
        st.session_state["swap_mode"] = st.session_state.get("rec_mode", "neutral")
    mode = st.segmented_control("Candidates", list(MODES), format_func=MODES.get, key="swap_mode",
                                help=f"Hidden gems leaves out the {HIDDEN_SKIP} most-used Pokémon. Popular picks "
                                     "only uses the top 80.") or "neutral"
    how_it_works(
        f"Candidates follow the **{MODES[mode]}** style. Each swap is scored "
        "with the same damage calcs as above, using the newcomer's popular set (keeping Item Clause and at most "
        "two Mega Stones). Swaps that lower your overall score by more than 0.05 are never shown.",
        "How swaps are chosen")
    threat_names = list(threats["pokemon"].head(10)) if not threats.empty else []
    others = [n for n, _ in usage.ranked(60) if n not in threat_names]
    options = ["Best overall vs the meta"] + threat_names + others
    focus = st.selectbox("Fix", options, key="swap_focus",
                         format_func=lambda o: o if o == options[0] else
                         (f"{o} (threat #{threat_names.index(o) + 1})" if o in threat_names else o))
    focus_name = None if focus == options[0] else focus
    same_role = st.toggle("Same role only", value=True, key="swap_same_role",
                          help="Swap a support for a support and an attacker for an attacker, and keep the "
                               "team's weather, terrain or Trick Room setter.")
    view = st.segmented_control("Show", ["For each member", "Best swaps"], default="For each member",
                                key="swap_view") or "For each member"
    per_member = view == "For each member"
    with st.spinner("Trying swaps…"):
        swaps = cached_swaps(fmt.id, team_key(team), focus_name, mode, same_role, 2 if per_member else None)
    if per_member:
        member_alternatives(team, swaps, focus_name, same_role)
        return
    if swaps.empty and same_role:
        st.info("No same-role swap helps here. Turn off **Same role only** to see swaps that change a "
                "member's job.")
        return
    if swaps.empty:
        st.success("No single swap improves this without hurting the overall matchup. Your team already "
                   "handles it about as well as one change can." if focus_name else
                   "No single swap improves the overall matchup.")
        return
    base = swaps.attrs.get("base_overall", 0.0)
    st.caption(f"Your team now: {base:+.2f} vs the meta ({verdict(base)}).")
    for i, row in swaps.iterrows():
        with st.container(border=True):
            cols = st.columns([5, 2])
            gain = f" · vs {focus_name} {row['vs threat']:+.1f}" if focus_name else ""
            cols[0].markdown(
                f"**{row['swap out']} → {row['swap in']}** · {row['out job']}"
                + (f" → {row['in job']}" if row['in job'] != row['out job'] else "")
                + f" · overall {row['overall']:+.2f} "
                f"({row['overall change']:+.2f}){gain}"
            )
            cols[0].caption(swap_detail(row))
            cols[1].button("Apply swap", key=f"swap_{i}_{row['swap in']}", width="stretch",
                           on_click=write_slot, args=(int(row["slot"]), row["_set"]))


def swap_detail(row) -> str:
    detail = row["set"]
    if row["shared roles"]:
        detail += f"  \nShared roles: {row['shared roles']}"
    if row["key calc"]:
        detail += f"  \n{row['key calc']}"
    return detail


def change_text(delta: float) -> str:
    if abs(delta) < 0.02:
        return "about the same"
    return f"{delta:+.2f} {'better' if delta > 0 else 'worse'}"


def member_alternatives(team, swaps: pd.DataFrame, focus_name: str | None, same_role: bool) -> None:
    """The closest alternatives for every member, whether or not they improve the team."""
    base = swaps.attrs.get("base_overall") if not swaps.empty else None
    st.caption("Who else could fill each spot, with how the team's overall matchup would change"
               + (f" (your team now: {base:+.2f}, {verdict(base)})." if base is not None else "."))
    for slot, pset in enumerate(team):
        rows = swaps[swaps["slot"] == slot] if not swaps.empty else swaps
        with st.container(border=True):
            job_txt = f" · {rows.iloc[0]['out job']}" if len(rows) else ""
            st.markdown(f"**{pset.nickname or pset.species}**{job_txt}")
            if rows.empty:
                st.caption("No same-role alternative in the candidate pool. Turn off **Same role only** to "
                           "see Pokémon that would change this spot's job." if same_role else
                           "No alternative found in the candidate pool.")
                continue
            for i, row in rows.iterrows():
                cols = st.columns([5, 2], vertical_alignment="center")
                extra = f" · vs {focus_name} {row['vs threat']:+.1f}" if focus_name else ""
                jobs = f" ({row['in job']})" if row["in job"] != row["out job"] else ""
                cols[0].markdown(f"{row['pick']}: **{row['swap in']}**{jobs} · "
                                 f"{change_text(row['overall change'])}{extra}")
                cols[0].caption(swap_detail(row))
                cols[1].button("Apply swap", key=f"alt_{slot}_{i}_{row['swap in']}", width="stretch",
                               on_click=write_slot, args=(int(row["slot"]), row["_set"]))
