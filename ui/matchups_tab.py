"""Matchups tab: team vs rebuilt meta teams, pairing heatmaps, counters and threats."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dex import load_dex
from src.formats import FORMATS
from src.analysis import build_members, mega_variants
from src.matchup import (build_archetypes, counter_picks, meta_matchups, opponent_members, threat_report,
                         verdict)
from src.evidence import team_signal_sentence
from src.match_model import GROUPS, beyond, cap_chance, load_model, predict_match, team_side
from src.recommend import MODES
from src.swaps import HIDDEN_MAX, SwapEngine, mode_pool, suggest_swaps
from src.team import PokemonSet
from src.usage import load_usage
from src.validate import win_chance
from ui.common import jump_row, matchup_scale, section, sprite
from ui.compare import apply_swap, compare_section
from ui.theme import how_it_works

VALIDATION_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"


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


@st.cache_data(show_spinner=False)
def match_check(regulation: str) -> dict | None:
    """data/evaluation/<reg>_matches.json from src/validate.py, if it exists."""
    path = VALIDATION_DIR / f"{regulation}_matches.json"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_resource(show_spinner=False)
def learned_meta_sides(fmt_id: str):
    """The learned model and each meta team's side of it (None when there's no model)."""
    fmt = FORMATS[fmt_id]
    model = load_model(fmt.regulation)
    if model is None:
        return None, []
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    engine = swap_engine_for(fmt_id)
    sides = []
    for arch in archetypes_for(fmt_id):
        sets = [p for p in (usage.popular_set(m, dex) for m in arch.members) if p is not None]
        sides.append(team_side(opponent_members(arch.members, usage, dex), sets, dex, usage, engine))
    return model, sides


@st.cache_data(show_spinner=False, max_entries=64)
def learned_chances(fmt_id: str, key: str) -> list[float]:
    """Learned win chance against each meta team (best Mega choice per opponent)."""
    model, sides = learned_meta_sides(fmt_id)
    if model is None:
        return []
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    team = _unkey(key)
    engine = swap_engine_for(fmt_id)
    mine = [team_side(members, team, dex, usage, engine) for _, members in mega_variants(team, dex)]
    return [max(predict_match(model, m, theirs) for m in mine) for theirs in sides]


@st.cache_data(show_spinner=False, max_entries=64)
def untested_parts(fmt_id: str, key: str) -> list[str]:
    """What this team does past every real tournament team (so its win chance is capped there)."""
    model, sides = learned_meta_sides(fmt_id)
    if model is None or not model.get("trust"):
        return []
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    team = _unkey(key)
    engine = swap_engine_for(fmt_id)
    mine = [team_side(members, team, dex, usage, engine) for _, members in mega_variants(team, dex)]
    found: set[str] = set()
    for theirs in sides:
        found |= beyond(model, max(mine, key=lambda m: predict_match(model, m, theirs)), theirs)
    return sorted({untested_label(f) for f in found})


def untested_label(feature: str) -> str:
    if feature.startswith("tool: "):
        return feature[len("tool: "):]
    group = next((g for g, fs in GROUPS.items() if feature in fs), None)
    return {"Damage calcs": "damage", "Speed": "Speed", "Bulk": "bulk"}.get(group or "",
                                                                            "this combination" if feature == "total" else feature)


PROVEN_TEXT = {
    "Strong": "Strong players often bring these Pokémon together.",
    "Solid": "A fairly usual combination among tournament teams.",
    "Shaky": "A less usual combination than most tournament teams.",
    "Weak": "Strong players rarely bring these Pokémon together.",
}


def team_check(fmt_id: str, team, dex, usage, chance: float) -> None:
    """Two lenses instead of one grade: is it proven (tournament data), does it work on paper."""
    from src.team_rating import lenses, load_reference
    ref = load_reference(FORMATS[fmt_id].regulation)
    seen = lenses(team, dex, usage, chance, ref)
    if seen is None:
        return
    proven, _ = seen["proven"]
    paper, paper_pct = seen["paper"]
    st.markdown("#### Team check")
    cols = st.columns(2)
    with cols[0].container(border=True):
        st.markdown(f"**Proven:** {proven}")
        st.caption(f"Off-meta: {seen['off_meta']} of {len(team)} are on few ladder teams, so tournament data "
                   "can't judge this combination yet. That's not a mark against it." if proven == "Untested"
                   else PROVEN_TEXT[proven])
    with cols[1].container(border=True):
        st.markdown(f"**On paper:** {paper}")
        st.caption(f"Its matchups against the meta teams (damage calcs, Speed, bulk, support moves) beat "
                   f"{paper_pct:.0f}% of tournament teams'. Popularity plays no part.")
    if proven in ("Shaky", "Weak"):
        why = rare_partners(team, dex, usage.teammates)
        if why:
            st.caption(why)


def rare_partners(team, dex, tm) -> str:
    """Which members strong players rarely run with the rest (the Analysis tab shows who they run)."""
    roots = [dex.sheet_id(p.battle_form(dex)) for p in team]
    rare = [p.species for p, c in zip(team, tm.fit_check(roots)) if c["rank"] and c["rank"] > 15]
    if not rare:
        return ""
    names = " and ".join(rare[:2]) if len(rare) <= 2 else f"{', '.join(rare[:2])} and {len(rare) - 2} more"
    return f"Strong players rarely run {names} with the rest of this team. The Analysis tab shows who they run instead."


FAVORED = 0.53  # a matchup counts as favorable at 53%+ to win (unfavorable at 47% or less)


def chance_verdict(p: float) -> str:
    if p >= 0.56:
        return "Favorable"
    if p >= FAVORED:
        return "Slightly favorable"
    if p > 1 - FAVORED:
        return "Even"
    if p > 0.44:
        return "Slightly unfavorable"
    return "Unfavorable"


def win_text(score: float, check: dict | None, model: str) -> str:
    """'about 47% to win', from how real tournament matches with this score went."""
    if not check or model not in check["models"]:
        return ""
    return f"about {win_chance(score, check['models'][model]['k']):.0%} to win"


def reliability_box(check: dict | None, learned: dict | None = None) -> None:
    if learned:
        t = learned["test"]
        cal = learned["calibration"]
        with st.expander(f"How reliable are these win chances? Tested on {learned['test_matches']:,} real "
                         "tournament matches"):
            main = t.get("learned model (skill + team)", t.get("learned model", {}))
            skill = t.get("player skill only")
            team_only = t.get("team only", t.get("learned, no Pokémon effects"))
            calc = t.get("damage-calc matchup score", t.get("matchup score only", {}))
            lines = [
                f"Win chances come from a model **learned from {learned['matches']:,} real Limitless matches** "
                "where both team lists are known. It weighs the damage-calc matchup, Speed, bulk and each side's "
                "support tools by how much they mattered in real results"
                + (", **between equally rated players**: each player's skill rating going into the match is in "
                   "the model too, so a team doesn't get credit for its pilot. Here it compares teams, so both "
                   "players count as equal." if skill else ".")
                + f" It was fitted on older tournaments and tested on the newest {learned['test_matches']:,} "
                f"matches ({learned['test_dates'][0]} to {learned['test_dates'][1]}), which it never saw.\n",
                f"- With both players' ratings it picks the winner **{main['accuracy']:.1%}** of the time; "
                + (f"ratings alone {skill['accuracy']:.1%}. " if skill else "")
                + (f"From the teams alone: {team_only['accuracy']:.1%}. " if team_only else "")
                + f"The damage-calc score alone gets {calc['accuracy']:.1%}; a coin flip 50%. "
                + team_signal_sentence(learned),
                "- **Are the percentages honest?** For the full model (ratings and teams), the table splits the "
                "test matches into five equal groups by "
                "the win chance the model gave. In each group, the average chance it gave should match how often "
                f"that side actually won: in the group it rated lowest it said {cal[0]['predicted']:.0%} and they "
                f"won {cal[0]['actual']:.0%}; in the highest, {cal[-1]['predicted']:.0%} and "
                f"{cal[-1]['actual']:.0%}.\n",
                "Who's playing matters more than the team, and luck matters a lot, so a team win chance is a few "
                "points of edge, not a sure thing. See **What wins games** at the bottom of the Pokémon tab for what the model "
                "learned.",
            ]
            st.markdown("\n".join(lines))
            names = ["Lowest fifth", "2nd fifth", "Middle fifth", "4th fifth", "Highest fifth"]
            rows = [{"matches, by the win chance given": names[i] if len(cal) == 5 else f"Group {i + 1}",
                     "model said": c["predicted"], "actually won": c["actual"], "matches": c.get("matches")}
                    for i, c in enumerate(cal)]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="percent")
                                        for c in ["model said", "actually won"]})
        return
    if not check:
        return
    m = check["models"]
    h2h, pop = m["team vs team (all 6)"], m["popularity"]
    cal = h2h["calibration"]
    with st.expander(f"How reliable are these scores? Tested on {check['matches']:,} real tournament matches"):
        st.markdown(
            f"Every Limitless match with both team lists ({check['matches']:,} matches) was scored team against team "
            f"with the same calcs as this tab. The win-chance curve was fitted on the older "
            f"{check['fit_matches']:,} and checked on the newest {check['test_matches']:,} "
            f"({check['test_dates'][0]} to {check['test_dates'][1]}).\n\n"
            f"- The team this tab favors won **{h2h['accuracy']:.1%}** of those matches (coin flip 50%, "
            f"\"the more popular team\" {pop['accuracy']:.1%}).\n"
            f"- When it favored one side most strongly, that side won **{cal[-1]['actual']:.0%}**; "
            f"when it favored the other side most strongly, **{cal[0]['actual']:.0%}**.\n\n"
            + ("So the score carries some signal, but" if h2h["accuracy"] >= 0.53 and h2h["accuracy"] > pop["accuracy"]
               else "So the score barely beats a coin flip, and")
            + " a single game is mostly decided by play and luck: treat a "
            "\"favorable\" matchup as a few percentage points, not a guaranteed win. Team lists don't publish stat "
            "points, so each Pokémon got its most common ladder spread."
        )
        st.dataframe(pd.DataFrame(cal).rename(columns={"score": "avg score", "predicted": "predicted win %",
                                                       "actual": "actual win %"}),
                     hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="percent")
                                    for c in ["predicted win %", "actual win %"]})


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


def _swaps_on() -> None:
    from src.usage_counts import count
    count("find swaps")
    st.session_state[SWAPS_ON] = True


def matchups_tab(fmt_id, team, members, dex, usage, fmt) -> None:
    if usage is None:
        st.info("Matchups need usage stats for this format.")
        return
    archetypes = archetypes_for(fmt_id)
    doubles = fmt.is_doubles
    if members:
        jump_row(["Compare versions", "Biggest threats to your team", "Suggested swaps"])
    section("Against the meta")
    how_it_works(
        "- **Meta teams** are rebuilt from Smogon teammate data: start from a popular Pokémon and keep adding "
        "whoever is most often paired with the whole team so far. Each opponent uses its most popular set.\n"
        "- **Each pairing** is decided by real damage calcs both ways. A pair scores +1 when your Pokémon needs "
        "half as many hits to KO theirs as they need to KO yours, and ±0.5 for Speed (reversed under Trick "
        "Room). Weather teams are scored in their weather.\n"
        "- **Support counts for the whole side**: Reflect, Light Screen and Aurora Veil cut the other side's "
        "physical/special hits, and Intimidate cuts their physical hits, at partial strength since they're only up "
        "for part of a game. A screens setter can earn a bring slot by making the rest of the team take less "
        "damage. Tailwind and Trick Room setters aren't credited: on real match results, adding them made "
        "predictions worse. Fake Out, redirection, status, boosts and switching aren't modeled.\n"
        "- **Team score** is how well you answer them minus how well they answer you, so 0 is even. "
        "With two Mega Stones, each matchup uses whichever Mega Evolves best.\n"
        "- **Win chance** comes from a model learned on real tournament matches. It weighs the calcs above "
        "together with Speed, bulk and each side's support tools (Wide Guard, Encore, Fake Out...), by how much "
        "each actually mattered in real results between equally rated players.",
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
        check = match_check(fmt.regulation)
        chances = learned_chances(fmt_id, team_key(team))
        if chances:
            team_check(fmt_id, team, dex, usage, cap_chance(learned_meta_sides(fmt_id)[0],
                                                            float(np.average(chances, weights=weights))))
        c = st.container(key="metric_row").columns(4)
        if chances:
            # one yardstick everywhere: the learned win chance (the calc score stays as a column)
            avg = cap_chance(learned_meta_sides(fmt_id)[0], float(np.average(chances, weights=weights)))
            c[0].metric("Win chance", f"{avg:.0%}", help="Usage-weighted average win chance against the meta "
                                                         "teams below, from the learned model (equal players). "
                                                         "Capped at the best real tournament team's.")
            c[1].metric("Favorable", sum(p >= FAVORED for p in chances), help=f"{FAVORED:.0%}+ to win")
            c[2].metric("Even", sum(1 - FAVORED < p < FAVORED for p in chances))
            c[3].metric("Unfavorable", sum(p <= 1 - FAVORED for p in chances), help=f"{1 - FAVORED:.0%} or less")
            table.insert(2, "win chance", [round(100 * p) for p in chances])
            untested = untested_parts(fmt_id, team_key(team))
            if untested:
                st.caption(f"⚠️ Untested: no real tournament team goes as far on {', '.join(untested)}. "
                           "Win chances are capped at what real teams reach, since the data can't say more.")
            table["verdict"] = [chance_verdict(p) for p in chances]
            table = table.drop(columns=["score"])  # one yardstick: win chance
        else:
            c[0].metric("Overall", f"{overall:+.2f}", help="Usage-weighted average of the team scores below")
            c[1].metric("Favorable", int((table["score"] >= 0.25).sum()))
            c[2].metric("Even", int(((table["score"] > -0.25) & (table["score"] < 0.25)).sum()))
            c[3].metric("Unfavorable", int((table["score"] <= -0.25).sum()))
            st.caption(f"Overall: {verdict(overall).lower()}"
                       + (f", {win_text(overall, check, 'score vs the meta')} against a typical meta team."
                          if check else "."))
            # score next to the name, so it's visible without scrolling sideways on a phone
            if check:
                k = check["models"]["team vs team (all 6)"]["k"]
                table.insert(2, "win chance", [round(100 * win_chance(x, k)) for x in table["score"]])
        score_col = [c for c in ("score",) if c in table]
        # phone width: the team and its win chance; the verdict only when there's no win chance to show
        first = ["archetype"] + (["win chance"] if "win chance" in table else ["verdict"]) + score_col
        table = table[first + [c for c in table.columns if c not in first and c not in ("with bring", "verdict")]]
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "archetype": st.column_config.TextColumn("meta team", width="medium", pinned=True),
                "popularity": st.column_config.NumberColumn("avg usage %", format="%.1f"),
                "score": st.column_config.NumberColumn("score", format="%+.2f"),
                "calc score": st.column_config.NumberColumn("calc score", format="%+.2f",
                                                            help="Damage calcs and Speed only (0 = even)"),
                "win chance": st.column_config.NumberColumn("win chance", format="%d%%",
                                                            help="From a model learned on real tournament "
                                                                 "matches (see How reliable...)"),
                "with bring": st.column_config.NumberColumn(f"score with bring {fmt.pick}", format="%+.2f"),
            },
        )

    if members:
        compare_section(fmt_id, team, fmt)
    reliability_box(match_check(fmt.regulation), learned_meta_sides(fmt_id)[0])

    st.markdown("Facing a specific team? Plan the game on the **Battle plan** tab: bring, leads, turn 1, "
                "and who answers what.")
    st.button("Open the Battle plan", key="to_battle_plan", on_click=_open_battle_plan)

    threats = threats_section(fmt_id, team, members, dex, usage, doubles)
    swaps_section(team, dex, usage, fmt, threats)


def _open_battle_plan() -> None:
    st.session_state["main_tabs"] = "Battle plan"


def threats_section(fmt_id: str, team, members, dex, usage, doubles: bool) -> pd.DataFrame:
    section("Biggest threats to your team")
    if not members:
        st.info("Add Pokémon on the **Team** tab to see which popular Pokémon threaten you.")
        return pd.DataFrame()
    how_it_works("The 30 most-used Pokémon (popular sets), ranked by **usage × (your Pokémon it 2HKOs + 1) ÷ "
                 "(answers + 1)**. An *answer* beats it 1-on-1: it needs fewer hits to KO it than it needs back, or "
                 "the same number and it's faster (Choice Scarf counted).", "How threats are ranked")
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
                answers = (f"Your answers (win 1-on-1): {row['answers']}." if row["answers"] != "none" else
                           f"Nothing on your team wins 1-on-1. Your hardest hits on it: {row['your best hits']}.")
                st.caption(f"2HKOs {row['2HKOs']} of your team. Hardest hits: {row['hardest hits']}.  \n{answers}")
    with st.expander(f"All {len(threats)} threats"):
        st.dataframe(threats, hide_index=True, width="stretch",
                     column_config={"threat score": st.column_config.ProgressColumn(
                         "threat score", min_value=0, max_value=float(threats["threat score"].max() or 1),
                         format="%.1f")})
    return threats


@st.cache_resource(show_spinner=False)
def swap_engine_for(fmt_id: str) -> SwapEngine:
    fmt = FORMATS[fmt_id]
    engine = SwapEngine(archetypes_for(fmt_id), load_usage(fmt_id), load_dex(fmt.regulation), fmt.is_doubles)
    engine.attach_model(load_model(fmt.regulation))  # learned win chance vs the meta, when available
    from src.team_rating import load_reference
    engine.attach_rating(load_reference(fmt.regulation), load_usage(fmt_id).teammates)  # swaps judged on it
    return engine


def candidate_help(usage, dex) -> str:
    """The three candidate pools in the same unit: share of ladder teams."""
    sheet = list(usage.team_sheet_usage(dex).values()) if usage is not None else []
    popular_floor = min((pct for _, pct in usage.ranked(80)), default=0) if usage is not None else 0
    common = sum(1 for v in sheet if v >= HIDDEN_MAX)
    return (f"**Neutral:** any Pokémon with ladder data.  \n**Popular picks:** the 80 most used (about "
            f"{popular_floor:.1f}%+ of teams).  \n**Hidden gems:** only Pokémon on under {HIDDEN_MAX:.0f}% of teams "
            f"(everything outside the top {common}).")


SWAPS_ON = "swaps_on"


def swaps_section(team, dex, usage, fmt, threats: pd.DataFrame) -> None:
    section("Suggested swaps")
    if len(team) < 2:
        st.info("Swaps need at least two Pokémon on your team.")
        return
    st.caption("Replace one member with a Pokémon that fixes a problem without hurting the overall matchup.")
    if st.session_state.get("swap_mode") not in MODES:  # start from the Recommendations tab's style
        st.session_state["swap_mode"] = st.session_state.get("rec_mode", "neutral")
    mode = st.segmented_control("Candidates", list(MODES), format_func=MODES.get, key="swap_mode",
                                help=candidate_help(usage, dex)) or "neutral"
    how_it_works(
        f"Candidates follow the **{MODES[mode]}** style. Each swap is judged by your **team score**: how your "
        "team compares with real tournament teams, from two things. **Fit**: how often strong players bring "
        "each Pokémon with the other five. **Win chance** against the meta teams, from the learned model "
        "(damage calcs, Speed, bulk and support tools). Together they tracked real tournament results better "
        "than win chance alone. Each newcomer uses its popular set (keeping Item Clause and at most two Mega "
        "Stones). In Best swaps, a swap that makes the team noticeably worse is never shown. Each Pokémon is "
        "suggested as the best upgrade for one member at most. **Players' pick** is what players most often run "
        "with your other five instead.  \n\n"
        "**How well it works** (186,000 rated ladder and Bo3 games, which neither model learned from): "
        "comparing teams that share five Pokémon, the sixth the app scores higher won **1.4 points** more "
        "above what the players' ratings predicted. When fit and win chance agree it's **1.8 points**; when only "
        "the win model likes a swap, there's no measurable edge, and the swap says so. Players' pick names "
        "the replacement real players chose in its top 3 for 42% of real swaps.",
        "How swaps are chosen")
    threat_names = list(threats["pokemon"].head(10)) if not threats.empty else []
    others = [n for n, _ in usage.ranked(60) if n not in threat_names]
    options = ["Best overall vs the meta"] + threat_names + others
    focus = st.selectbox("Fix", options, key="swap_focus",
                         format_func=lambda o: o if o == options[0] else
                         (f"{o} (threat #{threat_names.index(o) + 1})" if o in threat_names else o))
    focus_name = None if focus == options[0] else focus
    # Off by default: when real players replace a member, the newcomer has a different job 54% of the time,
    # and a team's only weather / Trick Room setter is replaced by another one just 16% of the time
    # (labs/swap_choice_lab.py), so the filter hid what most players actually do.
    same_role = st.toggle("Same role only", value=False, key="swap_same_role",
                          help="Swap a support for a support and an attacker for an attacker, and keep the "
                               "team's weather, terrain or Trick Room setter. Real players change a member's "
                               "job about half the time, so it's off by default.")
    view = st.segmented_control("Show", ["For each member", "Best swaps"], default="For each member",
                                key="swap_view") or "For each member"
    per_member = view == "For each member"
    # The search is the app's heaviest step (~9 s of server time per team), so it runs on request:
    # once a visitor has asked, it runs for each new version of their team for the rest of the visit.
    if not st.session_state.get(SWAPS_ON):
        st.button("Find swaps", key="find_swaps", type="primary", width="stretch",
                  on_click=_swaps_on,
                  help="Tries every member against every candidate. Takes a few seconds.")
        return
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
        engine = swap_engine_for(fmt.id)
        rated = engine.rating(team, engine.win_chance(team)) if not focus_name else None
        st.success("No single swap improves this without hurting the overall matchup. Your team already "
                   "handles it about as well as one change can." if focus_name else
                   f"No single swap raises your team score ({rated[1]:.0f} out of 100). That's about as good "
                   "as one change can make it." if rated else
                   "No single swap improves the overall matchup.")
        return
    st.caption(base_text(swaps))
    for i, row in swaps.iterrows():
        with st.container(border=True):
            cols = st.columns([5, 2])
            gain = f" · vs {focus_name} {row['vs threat']:+.1f}" if focus_name else ""
            cols[0].markdown(
                f"**{row['swap out']} → {row['swap in']}** · {row['out job']}"
                + (f" → {row['in job']}" if row['in job'] != row['out job'] else "")
                + f" · {change_text(row)}{gain}"
            )
            cols[0].caption(swap_detail(row))
            cols[1].button("Apply swap", key=f"swap_{i}_{row['swap in']}", width="stretch",
                           on_click=apply_swap, args=(int(row["slot"]), row["_set"], team_key(team),
                                                       team[int(row["slot"])].nickname or team[int(row["slot"])].species))


def pick_label(row) -> str:
    """'Best upgrade' only when it really raises the team; otherwise it's the best alternative."""
    if row["pick"] != "Best upgrade":
        return row["pick"]
    # the same test change_text uses for "about the same", so an upgrade is never "about the same"
    for col, same in (("score change", 1.0), ("win change", 0.2), ("overall change", 0.02)):
        value = row.get(col)
        if value is not None and not pd.isna(value):
            return "Best upgrade" if value >= same else "Best alternative"
    return row["pick"]


# Measured on real games (labs/swap_quality_lab.py, Nov 21): where one sixth beat another for the same
# five, the sixth the app preferred did +1.8 points better when teammate fit and win chance both favored it,
# and +0.05 (a coin flip) when only the win model did.
BACKING_NOTE = {
    "both": "Backed by both: your team gets closer to what players bring, and its win chance rises.",
    "win model only": "Win model only: your team gets less like what players bring. Swaps like this showed no "
                      "clear edge in real games.",
}


def backing_note(row) -> str:
    """One line on how much to trust an upgrade, for swaps that raise the team score."""
    b, change = row.get("backing"), row.get("score change")
    if not isinstance(b, str) or change is None or pd.isna(change) or change < 1:
        return ""
    return BACKING_NOTE.get(b, "")


def swap_detail(row) -> str:
    detail = row["set"]
    note = backing_note(row)
    if note:
        detail = f"{note}  \n{detail}"

    if row["shared roles"]:
        detail += f"  \nShared roles: {row['shared roles']}"
    if row["key calc"]:
        detail += f"  \n{row['key calc']}"
    return detail


def change_text(row) -> str:
    """'team score 64 (+6)' (team rating), '+2.3 points of win chance' (learned model) or '+0.12 score'."""
    score, delta_s = row.get("score"), row.get("score change")
    if score is not None and not pd.isna(score):
        return (f"team score {score:.0f} (about the same)" if abs(delta_s) < 1 else
                f"team score {score:.0f} ({delta_s:+.0f})")
    win = row.get("win change")
    if win is not None and not pd.isna(win):
        if abs(win) < 0.2:
            return "about the same win chance"
        return f"{win:+.1f} points of win chance"
    delta = row["overall change"]
    if abs(delta) < 0.02:
        return "about the same"
    return f"{delta:+.2f} {'better' if delta > 0 else 'worse'}"


def base_text(swaps: pd.DataFrame) -> str:
    win, base = swaps.attrs.get("base_win"), swaps.attrs.get("base_overall")
    score = swaps.attrs.get("base_score")
    if score is not None:
        return (f"Your team now: team score {score:.0f} out of 100, higher than {score:.0f}% of tournament "
                "teams. It combines both lenses of the Team check: proven pairings and matchups on paper.")
    if win is not None:
        return f"Your team now: about {win:.0%} to win against the meta teams."
    return f"Your team now: {base:+.2f} vs the meta ({verdict(base)})." if base is not None else ""


def member_alternatives(team, swaps: pd.DataFrame, focus_name: str | None, same_role: bool) -> None:
    """The closest alternatives for every member, whether or not they improve the team."""
    st.caption("Who else could fill each spot, and how your team score would change. "
               + (base_text(swaps) if not swaps.empty else ""))
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
                cols[0].markdown(f"{pick_label(row)}: **{row['swap in']}**{jobs} · "
                                 f"{change_text(row)}{extra}")
                cols[0].caption(swap_detail(row))
                cols[1].button("Apply swap", key=f"alt_{slot}_{i}_{row['swap in']}", width="stretch",
                               on_click=apply_swap, args=(int(row["slot"]), row["_set"], team_key(team),
                                                       team[int(row["slot"])].nickname or team[int(row["slot"])].species))
