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
from src.matchup import (best_attack, best_variant, build_archetypes, counter_picks, meta_matchups,
                         opponent_members, team_score, threat_report, verdict)
from src.bring_model import load_model as load_bring_model
from src.bring_model import pick as bring_pick
from src.gameplan import game_plan
from src.match_model import GROUPS, beyond, cap_chance, explain, load_model, predict_match, team_side
from src.recommend import MODES
from src.replays import load_summary, usual_picks
from src.roles import meta_roles, role_text
from src.swaps import HIDDEN_MAX, SwapEngine, mode_pool, suggest_swaps
from src.team import PokemonSet
from src.usage import load_usage
from src.validate import win_chance
from ui.common import jump_row, matchup_scale, section, sprite, type_badges
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


@st.cache_data(show_spinner=False, ttl=3600)
def bring_model_for(regulation: str) -> dict | None:
    """The replay-learned bring model, only if it beat both baselines on held-out games."""
    model = load_bring_model(regulation)
    if not model:
        return None
    r = model["results"]["bring"]
    return model if r["learned"][0] > max(r["usual picks"][0], r["damage calcs"][0]) else None


@st.cache_data(show_spinner=False, ttl=3600)
def replay_summary(fmt_id: str) -> dict | None:
    return load_summary(fmt_id)


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
                + (f"ratings alone {skill['accuracy']:.1%}, so the teams add real signal on top of skill. "
                   if skill else "")
                + (f"From the teams alone: {team_only['accuracy']:.1%}. " if team_only else "")
                + f"The damage-calc score alone gets {calc['accuracy']:.1%}; a coin flip 50%.",
                "- **Are the percentages honest?** The table splits the test matches into five equal groups by "
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
            "So the score carries real signal, but a single game is mostly decided by play and luck: treat a "
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


def battle_plan_tab(fmt_id, team, members, dex, usage, fmt) -> None:
    """One opponent, in detail: win chance, what to bring and lead, turn 1, who answers what."""
    if usage is None:
        st.info("The battle plan needs usage stats for this format.")
        return
    archetypes = archetypes_for(fmt_id)
    doubles = fmt.is_doubles
    if not members:
        st.info("Add Pokémon on the **Team** tab, then enter the six you see at team preview here.")
        return
    names = [a.name for a in archetypes]
    if not names:
        st.info("Not enough usage data to build meta teams.")
        return
    pick = st.selectbox("Opponent", [FACING] + names, key="detail_pick",
                        help="The six you see at team preview, or one of the common meta teams.")
    their_side = None
    if pick == FACING:
        facing = facing_archetype(dex, usage)
        if facing is None:
            return
        arch, their_sets, filled = facing
        theirs = build_members(their_sets, dex, evolve=0 if their_sets[0].is_mega(dex) else None)
        model_now = learned_meta_sides(fmt_id)[0]
        if model_now is not None:
            their_side = team_side(theirs, their_sets, dex, usage, swap_engine_for(fmt_id))
        pick = "their team"
        if filled:
            spread = [n for n, parts in filled.items() if parts == ["nature and stat points"]]
            other = {n: parts for n, parts in filled.items() if parts != ["nature and stat points"]}
            bits = ([f"nature and stat points for {', '.join(spread)}"] if spread else []) + \
                   [f"{', '.join(parts)} for {n}" for n, parts in other.items()]
            st.caption("Not on their sheet, so taken from the most common set: " + "; ".join(bits) + ".")
    else:
        arch = archetypes[names.index(pick)]
        theirs = opponent_members(arch.members, usage, dex)
    cards = "".join(
        f"<div class='opp-card'><img src='{sprite(opp.form, dex)}' alt=''>"
        f"<div class='opp-name'>{opp.label}</div><div>{type_badges(opp.form.types)}</div>"
        f"<div class='opp-item'>{opp.pset.item or 'No item'}</div>"
        f"<div class='opp-meta'>{role_text(meta_roles(arch.members[i], usage, dex, doubles), 2)}</div></div>"
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
        # The bring-4 comes from the replay-learned model when it predicts real choices better
        # than both the calcs and players' usual picks (data/evaluation/<reg>_bring_model.json);
        # the Mega choice follows the bring, so the Pokémon told to Mega Evolve is always brought.
        bring_model = bring_model_for(fmt.regulation)
        use_model = bool(bring_model) and fmt.pick == 4 and len(members) > 4
        def mega_of(ms):
            return next((m.label for m in ms if m.form.is_mega), None)

        # the Mega always comes (who Mega Evolves is chosen by calcs); the model picks the rest
        picker = (lambda ms, mx: bring_pick(bring_model, ms, theirs, mx, dex, keep=mega_of(ms))[0]) \
            if use_model else None
        who, matrix, picks, picked = best_variant(variants, theirs, arch.trick_room, doubles, arch.weather,
                                                  fmt.pick, picker)
        members_now = next(ms for _, ms in variants if [m.label for m in ms] == list(matrix.index))
        score = team_score(matrix)
        model, sides = learned_meta_sides(fmt_id)
        pros = cons = []
        if model is not None and (their_side is not None or pick in names):
            mine = team_side(members_now, team, dex, usage, swap_engine_for(fmt_id))
            theirs_side = their_side if their_side is not None else sides[names.index(pick)]
            p_win = predict_match(model, mine, theirs_side)
            pros, cons = explain(model, mine, theirs_side)
            st.markdown(f"**Your team vs {pick}: about {p_win:.0%} to win ({chance_verdict(p_win).lower()})**")
        else:
            chance = win_text(score, match_check(fmt.regulation), "team vs team (all 6)")
            st.markdown(f"**Your team vs {pick}: {verdict(score).lower()}**" + (f" ({chance})" if chance else ""))

        plan_picks, bring_source = picks, ("replays" if use_model else "calcs")
        plan = game_plan(members_now, theirs, matrix, plan_picks, dex, doubles, arch.trick_room, arch.weather)
        plan.bring_source = bring_source
        plan.calc_lead = list(plan.lead)  # the calcs' lead against this team, before replays override it
        summary = replay_summary(fmt_id)
        if summary:
            label = {p.species: m.label for p, m in zip(team, members_now)}
            # their likely leads: what ladder players lead with (beats the calc guess on replays)
            their_sets = [o.pset for o in theirs if o.pset is not None]
            their_label = {p.species: o.label for p, o in zip(their_sets, [o for o in theirs if o.pset])}
            _, their_lead = usual_picks(summary, [p.species for p in their_sets])
            plan.their_leads = [their_label.get(s, s) for s in their_lead]
            plan.their_leads_source = "replays"
            if bring_source == "replays":
                r = bring_model["results"]["lead"]
                if r["learned"][0] > r["usual picks"][0]:  # the model's own leads test best
                    plan.lead = bring_pick(bring_model, members_now, theirs, matrix, dex,
                                           keep=mega_of(members_now))[1]
                    if not set(plan.lead) <= set(plan_picks):
                        plan.lead = [x for x in plan.lead if x in plan_picks][:2]
                else:  # players' usual leads among the four
                    _, lead_species = usual_picks(summary, [p.species for p, m in zip(team, members_now)
                                                            if m.label in plan_picks])
                    plan.lead = [label.get(s, s) for s in lead_species]
                plan.back = [b for b in plan.bring if b not in plan.lead]
        mega_name = None
        if len(variants) > 1 and who:
            form = dex.get_species(who)
            mega_name = form.base_species if form is not None else who
        game_plan_box(plan, mega_name)
        turn1_box(plan, members_now, theirs, fmt_id)
        playbook_box(theirs, members_now, dex, usage, fmt)

        answers = []
        for opp in theirs:
            col = matrix[opp.label]
            best = col.idxmax()
            mine_m = next(m for m in members_now if m.label == best)
            pct, move = best_attack(mine_m, opp, doubles, arch.weather)
            good = col.max() >= 0.5
            answers.append({"their Pokémon": opp.label, "your best answer": best if good else "none",
                            "key hit": f"{move} {pct:.0f}%" if good and move else "—"})
        st.markdown("**Who answers what**")
        st.dataframe(pd.DataFrame(answers), hide_index=True, width="stretch")
        with st.expander("Every pairing, and what moves the win chance"):
            st.plotly_chart(pair_heatmap(matrix), width="stretch")
            st.caption("Damage calcs both ways for each pair: blue = your Pokémon (row) wins it, red = theirs "
                       "(column) does.")
            if pros or cons:
                pts = lambda items: ", ".join(f"{g} ({v:+.0f})" for g, v in items)  # noqa: E731
                st.markdown("  \n".join(x for x in [f"**Helping you:** {pts(pros)}" if pros else "",
                                                     f"**Against you:** {pts(cons)}" if cons else ""] if x))
                st.caption("Points of win chance, from the model learned on real tournament matches. **Damage "
                           "calcs**: how your Pokémon and theirs hit each other. **Speed**: who moves first, "
                           "including Trick Room and Tailwind fit. **Bulk**: average defenses. The rest are support tools (Wide Guard, Fake Out...). "
                           "How popular your Pokémon are doesn't count: we tested it and it didn't help predict "
                           "real results.")


FACING = "A team you're facing (enter its six)…"


PICK, PASTE = "Pick their six", "Paste their team sheet"


def facing_archetype(dex, usage):
    """The team you're facing, as (Archetype, sets in Mega-first order, {species: parts filled in}).
    Picked by name, each gets its most common set; pasted (an open team sheet or a full Showdown paste),
    it keeps their real items, abilities and moves, and only what the sheet leaves out comes from the
    most common set. With two or more Mega Stones you say which one Mega Evolves. None until there are
    two Pokémon to plan against."""
    from src.matchup import Archetype, _label
    from src.opponent import mega_first, sets_from_sheet, style_of
    sheet = usage.team_sheet_usage(dex)
    how = st.segmented_control("Their team", [PICK, PASTE], default=PICK, key="opp_input",
                               help="Bo3 and tournament games show open team sheets: paste theirs to plan "
                                    "against their real items, abilities and moves.") or PICK
    filled: dict[str, list[str]] = {}
    if how == PASTE:
        text = st.text_area("Their team sheet", key="opp_paste", height=180,
                            placeholder="Paste their open team sheet or Showdown export…")
        sets, filled, warnings = sets_from_sheet(text, dex, usage) if text.strip() else ([], {}, [])
        for w in warnings:
            st.caption(f"⚠ {w}")
        if len(sets) < 2:
            st.caption("Paste at least two of their Pokémon to see the plan.")
            return None
    else:
        picked = st.multiselect("Their six (from team preview)", list(sheet), key="opp_team", max_selections=6,
                                placeholder="Type to search…",
                                help="Each gets its most common set. Sorted by how often it's on ladder teams.")
        if len(picked) < 2:
            st.caption("Pick at least two of their Pokémon to see the plan.")
            return None
        sets = [p for p in (usage.popular_set(n, dex) for n in picked) if p is not None]
        if len(sets) < 2:
            return None
    stones = [p.species for p in sets if p.is_mega(dex)]
    mega = None
    if len(stones) > 1:
        mega = st.selectbox("Which one Mega Evolves?", stones, key="opp_mega",
                            help="Only one Mega per battle; the others play in their base forme.")
    sets = mega_first(sets, dex, mega)
    # usage-entry names (a Mega by its Mega name) for roles and popularity
    names = [(p.battle_form(dex).name if i == 0 and p.is_mega(dex) else p.species) for i, p in enumerate(sets)]
    if how == PASTE:
        trick_room, weather, tags = style_of(sets, dex)
        name = f"{' + '.join(dict.fromkeys(tags[:2])) or 'Goodstuffs'} ({names[0]} + {names[1]})"
    else:
        name, trick_room, weather = _label(names, usage, dex)
    pop = sum(sheet.get(n, 0) for n in names) / len(names)
    return Archetype("Their team: " + name.split(" (")[0], names, round(pop, 1), trick_room, weather), sets, filled


def playbook_box(theirs, my_members, dex, usage, fmt) -> None:
    """The Playbook's findings for the styles this opponent sets up: plays that worked, and who on your
    team can make them (ui/playbook_tab.py has the full evidence). Setters are matched on the forme each
    opponent battles as (a Mega Charizard Y sets Sun; Mega X's Dragon Dance sets don't count for it)."""
    from src.playbook import STYLES, team_tools
    from ui.playbook_tab import _book, _name, _setters, _verdict, _who
    book = _book(fmt.id)
    if not book:
        return
    setters = _setters(fmt.id)

    def form_name(n: str) -> str:
        f = dex.get_species(n)
        return f.name if f is not None else n
    battling = {o.form.name: o.label for o in theirs}
    tools = team_tools(my_members)
    blocks, styles = [], []
    for style in STYLES:
        forms = {form_name(n) for n in setters.get(style, set())}
        who_sets = sorted({battling[f] for f in battling if f in forms})
        data = book["styles"].get(style)
        if not who_sets or not data:
            continue
        styles.append(style)
        good = [c for c in data["choices"] if _verdict(c) == "worked"]
        bad = [c for c in data["choices"] if _verdict(c) == "backfired"]
        rows = []
        for c in good[:3]:
            w = _who(c["choice"], tools)
            who = "" if w is None else (f" · yours: {', '.join(w)}" if w else " · your team can't")
            rows.append(f"- ✓ {_name(c['choice'])}: **{c['edge']:+.0f}** points{who}")
        if not good:
            rows.append("- No play clearly won more")
        if bad:
            rows.append(f"- ✗ Avoid {_name(bad[-1]['choice']).lower()}: **{bad[-1]['edge']:+.0f}** points")
        blocks.append(f"**Against their {style}** ({', '.join(who_sets)})\n\n" + "\n".join(rows))
    if blocks:
        with st.expander(f"From the Playbook: plays that won more against their {', '.join(styles)}"):
            st.markdown("\n\n".join(blocks))
            st.caption("Points of win chance above what the players' ratings predicted, against players who could "
                       "have made the same play and didn't. Associations, not proof: the Playbook tab has the details.")


def game_plan_box(plan, mega: str | None) -> None:
    """The plan for this matchup in a few short lines; how each part was chosen sits in one caption."""
    with st.container(border=True):
        st.markdown("**Game plan**")
        lines = [f"**Bring:** {', '.join(plan.bring)}" + (f" · Mega Evolve {mega}" if mega else ""),
                 f"**Lead:** {' + '.join(plan.lead)}" + (f" · **Back:** {', '.join(plan.back)}" if plan.back else ""),
                 (f"**On damage calcs against this team:** {' + '.join(plan.calc_lead)}"
                  if getattr(plan, "calc_lead", None) and plan.bring_source == "replays"
                  and set(plan.calc_lead) != set(plan.lead) else ""),
                 f"**They usually lead:** {' + '.join(plan.their_leads)}" if plan.their_leads else "",
                 f"**Your strongest piece:** {plan.strongest} ({plan.strongest_why})" if plan.strongest else ""]
        if plan.watch_out:
            lines.append("**Watch out for:** " + "; ".join(
                f"{w['pokemon']} ({w['hit']}; {w['your best']})" for w in plan.watch_out))
        st.markdown("  \n".join(line for line in lines if line))
        order, prev = [], None
        for r in plan.speed:
            name = f"**{r['pokemon']}**" if r["side"] == "yours" else r["pokemon"]
            sep = "" if prev is None else (" = " if r["speed"] == prev else " › ")
            order.append(f"{sep}{name} {r['speed']}")
            prev = r["speed"]
        st.caption("Speed (yours in bold, with each set's Stat Points and nature): " + "".join(order)
                   + (f". {plan.speed_note}" if plan.speed_note else ""))
        st.caption(("Bring and lead: what real players with your Pokémon choose against a team like this, "
                    "learned from ladder replays; it leans on your own team more than on theirs, so similar "
                    "opponents often get the same lead. The calcs' lead is shown when it differs. "
                    if plan.bring_source == "replays" else "Bring and lead: from damage calcs against this team. ")
                   + "Their leads: what players with their six usually lead.")


@st.cache_data(show_spinner=False)
def turn1_data(fmt_id: str) -> dict:
    from src.replays import load_turn1
    data = load_turn1(fmt_id)
    return data["pokemon"] if data else {}


def turn1_box(plan, members_now, theirs, fmt_id: str) -> None:
    """Turn 1 for each of your leads: what players clicked against their likely leads (or overall)."""
    table = turn1_data(fmt_id)
    if not table or not plan.lead:
        return
    species_of = {m.label: m.pset.species for m in members_now if m.pset is not None}
    their_species = {o.label: o.pset.species for o in theirs if o.pset is not None}
    their_leads = [their_species.get(x, x) for x in (plan.their_leads or [])]
    lines = []
    for lead in plan.lead:
        row = table.get(species_of.get(lead, lead))
        if not row:
            continue
        vs = [(t, row["vs"][t]) for t in their_leads if t in row.get("vs", {})]
        if vs:
            t, cell = max(vs, key=lambda x: x[1]["n"])
            moves, against = cell["moves"], f"against {t} ({cell['n']:,} games)"
        else:
            moves, against = row["all"], f"in all its leads ({row['n']:,} games)"
        lines.append(f"**{lead}:** " + ", ".join(f"{m} {s:.0%}" for m, s in moves) + f" <span class='rec-sub'>{against}</span>")
    if lines:
        with st.container(border=True):
            st.markdown("**Turn 1: what players click**  \n" + "  \n".join(lines), unsafe_allow_html=True)
            st.caption("From the last 30 days of ladder and Bo3 replays: the first move each lead used, against "
                       "their likely lead when there are enough games. It's what players do, not a tested "
                       "best move; the Playbook below says which plays won more against each style.")


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
        "suggested as the best upgrade for one member at most.",
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


def swap_detail(row) -> str:
    detail = row["set"]

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
