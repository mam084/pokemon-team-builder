"""Recommendations tab: ranked suggestions as cards, each with an Add to team button."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.builder import build_teams, core_set as builder_core_set
from src.dex import to_id
from src.matchup import verdict
from src.recommend import HIDDEN_MAX, DEFAULT_WEIGHTS, EXPLORE_WEIGHTS, MODES, recommend
from src.roles import meta_roles, role_text, set_roles
from ui.common import SLOTS, sprite, type_badges, no_usage
from ui.core_report import core_threats, thin_line, threats_line
from ui.matchups_tab import archetypes_for
from ui.state import add_to_team, load_team
from ui.theme import how_it_works

HELP = {
    "synergy": "How strongly players pair it with your whole team, from a model learned on ~50,000 real "
               "tournament and ladder teams. It weighs every member at once, so two Pokémon that only appear "
               "together because both go with a third don't count as partners. 0.5 = no pull either way.",
    "defense": "Resists the types your team is weak to (and doesn't share its weaknesses).",
    "offense": "Hits popular Pokémon your team can't hit super effectively.",
    "roles": "Commonly brings a role you're missing (Fake Out, speed control…).",
    "meta": "Overall ladder usage - proven Pokémon tend to be good. (In Popular picks, Pairs with already counts how "
            "often players pick it.)",
    "plan": "Plays into your team's weather, Trick Room, Tailwind or terrain (with diminishing returns), "
            "or sets one up that your team already benefits from.",
}
MODE_HELP = {
    "popular": "Data-tuned on real tournament teams. Leans on proven meta Pokémon.",
    "neutral": "Popularity counts for nothing and every Pokémon with ladder data is considered. "
               "Leans on synergy, type fit and your team's game plan (weather, Trick Room...).",
    "hidden": f"Like Neutral, but only Pokémon on fewer than {HIDDEN_MAX:.0f}% of ladder teams, to surface less common picks.",
}


def mode_picker() -> str:
    """Shared by recommendations, the team builder and swap suggestions."""
    if st.session_state.get("rec_mode") not in MODES:
        st.session_state["rec_mode"] = "neutral"
    mode = st.radio("Recommendation style", list(MODES), format_func=MODES.get, key="rec_mode",
                    horizontal=True)
    st.caption(MODE_HELP[mode])
    return mode


def weights_for(mode: str) -> dict:
    """The weights in effect: the sliders' values (they render at the bottom of the tab)."""
    defaults = DEFAULT_WEIGHTS if mode == "popular" else EXPLORE_WEIGHTS
    return {key: float(st.session_state.get(f"w_{mode}_{key}", defaults[key])) for key in DEFAULT_WEIGHTS}


def weight_sliders(mode: str) -> None:
    defaults = DEFAULT_WEIGHTS if mode == "popular" else EXPLORE_WEIGHTS
    st.caption("Defaults are tuned on real tournament teams (Popular picks) or set for exploring (Neutral, "
               "Hidden gems). Hover a slider for what it measures.")
    cols = st.columns(3)
    for i, key in enumerate(DEFAULT_WEIGHTS):
        cols[i % 3].slider(SIGNALS[key], 0.0, 1.0, float(defaults[key]), 0.05, help=HELP[key],
                           key=f"w_{mode}_{key}", disabled=(key == "meta" and mode != "popular"))


def core_set_options(name: str, dex, usage) -> list[tuple[str, object]]:
    """[(label, set)] for the core: the builder's default (most common full set on real team sheets, or the
    ladder's when there are too few sheets), the ladder's most common set, then presets. Duplicates dropped."""
    from src.presets import presets_for
    out, seen = [], set()

    def add(label, pset):
        if pset is None:
            return
        key = (to_id(pset.item or ""), pset.nature, frozenset(to_id(m) for m in pset.moves))
        if key not in seen:
            seen.add(key)
            out.append((label, pset))
    sheets = getattr(usage, "sheet_sets", None)
    default = builder_core_set(name, dex, usage)
    from src.sheet_sets import MIN_SHEETS, sheet_key
    on_sheets = bool(default and sheets and (sheets.get(sheet_key(default, dex)) or {}).get("n", 0) >= MIN_SHEETS)
    add("Most common on real team sheets" if on_sheets else "Most common set", default)
    add("Ladder's most common set", usage.popular_set(name, dex))
    for preset in presets_for(name, usage, dex)[:4]:
        add(f"{preset.name} (~{preset.weight:.0f}% of sets)", preset.pset)
    return out


def team_builder_section(team, dex, usage, fmt, mode, weights) -> None:
    with st.expander("Build a whole team around one Pokémon", expanded=not team):
        if usage is None:
            no_usage(fmt, "Needs usage stats for this format.")
            return
        sheet = usage.team_sheet_usage(dex)
        names = list(sheet)
        default = team[0].species if team and team[0].species in names else names[0]
        core_name = st.selectbox("Build around", names, index=names.index(default), key="build_core",
                                 format_func=lambda n: f"{n}  ·  {sheet[n]:.1f}%")
        mine = next((p for p in team if to_id(p.species) == to_id(core_name)), None)
        use_mine = st.checkbox(f"Use my {core_name} set", value=mine is not None, disabled=mine is None,
                               key="build_use_mine")
        if use_mine and mine:
            core_set = mine
        else:   # which set the core plays: real sheets by default, or the ladder's or a preset
            options = core_set_options(core_name, dex, usage)
            pick = st.selectbox("Its set", range(len(options)), key=f"build_core_set_{core_name}",
                                format_func=lambda i: options[i][0]) if len(options) > 1 else 0
            core_set = options[pick][1] if options else None
            if core_set is not None:
                st.caption(f"{core_set.item or 'no item'} · {core_set.nature} · " + " / ".join(core_set.moves))
        thin = thin_line(core_name, core_set, dex, usage, fmt)
        if thin:
            st.caption(thin)
        threats = core_threats(core_set, fmt)
        st.caption("Three different teams, each filled one Pokémon at a time with the top recommendation "
                   f"({MODES[mode]} style). They're ranked by one team score: how well they fit together "
                   "plus how they'd do against the meta teams, the mix that best matched real tournament "
                   "results. "
                   f"Loading a team replaces your current one. How {core_name} is usually played, with real "
                   "teams to start from: the Pokémon tab.")
        if st.button(f"Build teams around {core_name}", type="primary", width="stretch"):
            core = mine if (use_mine and mine) else (core_set or core_name)
            with st.spinner("Building teams…"):
                st.session_state["built_teams"] = build_teams(
                    core, dex, usage, doubles=fmt.is_doubles, mode=mode, weights=weights,
                    archetypes=archetypes_for(fmt.id), regulation=fmt.regulation)
            st.session_state["built_for"] = (core_name, mode)
        built = st.session_state.get("built_teams") or []
        if built:
            core_label, built_mode = st.session_state.get("built_for", ("", ""))
            st.markdown(f"**Teams around {core_label}** ({MODES.get(built_mode, built_mode)} style)")
        for n, t in enumerate(built):
            with st.container(border=True):
                theme = f" · {t.theme} team" if t.theme else ""
                weak, details = False, ""
                if t.percentile is not None:
                    from src.team_rating import details_line, is_weak, lenses, load_reference, score_line
                    seen = lenses(t.sets, dex, usage, t.chance, load_reference(fmt.regulation))
                    rated = score_line(t.percentile)
                    details = details_line(seen, t.chance)
                    weak = is_weak(seen)
                else:
                    score = t.meta_score or 0.0
                    rated = f"vs meta {score:+.2f} ({verdict(score)})"
                st.markdown(f"**Team {n + 1}**{theme} · {rated}")
                if details:
                    st.caption(f"Behind the score: {details}")
                if weak:
                    from src.team_rating import WEAK_NOTE
                    st.caption(f"⚠️ {WEAK_NOTE}")
                core_form = t.sets[0].battle_form(dex)
                covered = threats_line(t.sets, threats, core_form.name if core_form else core_label,
                                       dex, usage, fmt.is_doubles) if core_label == core_name else ""
                if covered:
                    st.caption(covered)
                cards = []
                for p in t.sets:
                    form = p.battle_form(dex)
                    cards.append(f"<div class='team-mon'><img src='{sprite(form, dex)}' alt=''><div>"
                                 f"<b>{p.species}</b> @ {p.item or 'no item'}<br>{type_badges(form.types)}"
                                 f"<br><span style='font-size:.8rem;opacity:.7'>"
                                 f"{role_text(set_roles(p, dex, fmt.is_doubles), 2)}</span></div></div>")
                st.markdown("<div class='team-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
                with st.expander("Why each Pokémon"):
                    for r in t.reasons:
                        st.markdown(f"- {r}")
                st.button("Load this team", key=f"load_built_{n}", width="stretch",
                          on_click=load_team, args=(t.sets,))

LINES = [("fit", "Pairs with"), ("clash", "Caution"), ("plan", "Plan"), ("cover", "Covers"), ("hits", "Hits"),
         ("adds", "Adds")]


SIGNAL_OF = {"fit": "synergy", "clash": "synergy", "plan": "plan", "cover": "defense", "hits": "offense",
             "adds": "roles"}


SHOWN_LINES = 2   # reasons on the card; the rest fold under "more reasons"


def card_split(row, weights: dict | None) -> tuple[str, str]:
    """(the lines that carry the most weight in this pick's score, the rest). A line's weight: its signal's
    value for this pick times the signal's weight in the current style. A Watch line always shows."""
    lines = card_lines(row["parts"], weights, as_list=True)
    if len(lines) <= SHOWN_LINES:
        return "  \n".join(t for _, t in lines), ""
    def weight(key: str) -> float:
        if key == "clash":
            return float("inf")
        sig = SIGNAL_OF[key]
        return (weights or {}).get(sig, 1.0) * float(row.get(sig, 0) or 0)
    ranked = sorted(range(len(lines)), key=lambda i: (-weight(lines[i][0]), i))
    keep = sorted(ranked[:SHOWN_LINES])
    shown = [lines[i][1] for i in keep]
    rest = [lines[i][1] for i in range(len(lines)) if i not in keep]
    return "  \n".join(shown), "  \n".join(rest)


def card_lines(parts: dict, weights: dict | None = None, as_list: bool = False):
    """The reasons as short labelled lines (Pairs with / Covers / Hits...) instead of one long sentence.
    A line whose signal is weighted to zero (Fine-tune the ranking) is left off."""
    out = []
    for key, label in LINES:
        if weights is not None and not weights.get(SIGNAL_OF[key], 1):
            continue
        text = parts.get(key)
        if text:
            for lead in ("players pair it with ", "paired often with ", "rarely run next to ", "resists ",
                         "hits ", "adds "):
                if text.startswith(lead):
                    text = ("next to " if lead == "rarely run next to " else "") + text[len(lead):]
                    break
            text = text.replace(" super effectively", "")
            if key == "cover" and "weak spots:" in text:  # the core is named once, above the list
                text = text.partition("weak spots:")[2].strip()
            if key == "hits":
                text += " (super effective)"
            if key == "clash":
                text = "rarely run " + text
            out.append((key, f"**{label}:** {text[0].upper() + text[1:] if key != 'clash' else text}"))
    return out if as_list else "  \n".join(t for _, t in out)


def pick_chances(team, dex, usage) -> dict[str, float]:
    """{root: P(players with this team pick it next)} from the learned teammate model."""
    tm = usage.teammates if usage is not None else None
    if tm is None or not team:
        return {}
    roots = [dex.sheet_id(f) for p in team if (f := p.battle_form(dex)) is not None]
    probs = tm.pick_probs(roots)
    return {r: float(probs[i]) for r, i in tm.index.items()}


def recommendations_tab(team, members, dex, usage, fmt) -> None:
    mode = mode_picker()
    weights = weights_for(mode)
    team_builder_section(team, dex, usage, fmt, mode, weights)

    st.subheader("Next Pokémon for your team")
    if len(team) >= SLOTS:
        st.info("Your team is full - remove a member (Team tab) to add one of these, or see "
                "**Suggested swaps** on the Matchups tab.")
    learned = usage is not None and usage.teammates is not None
    how_it_works(
        ("**Pairs with** comes from a model learned on real teams (tournament team lists and ladder replays): given "
         "your whole team, how much likelier players are to pick each candidate. It looks at every member at "
         "once, so it isn't fooled by two Pokémon that only show up together because both pair with a third. "
         if learned else
         "**Pairs with** is how much more often it appears next to each of your Pokémon than chance (ladder stats). ")
        + "**Covers** is the types your team is weak to that it resists, **Hits** the popular Pokémon your team "
        "can't hit super effectively that it can, **Adds** jobs your team lacks, and **Plan** how it plays into "
        "your weather, terrain, Trick Room or Tailwind. The ranking blends these with weights you can change "
        "under **Fine-tune** at the bottom.", "How picks are chosen")
    recs = recommend(members, dex, usage, doubles=fmt.is_doubles,
                     weights=weights, top_n=15, mode=mode)
    if recs.empty:
        st.info("No candidates.")
        return
    if recs.attrs.get("glue"):
        weak = ", ".join(t.title() for t in recs.attrs.get("weak_types", []))
        st.info(f"Your **{recs.attrs['glue']}** core is in place, so picks now favor covering its weak spots "
                f"({weak}) over adding more of the same.")
    if usage:
        recs.insert(2, "usually plays", [role_text(meta_roles(n, usage, dex, fmt.is_doubles), 2)
                                          for n in recs["pokemon"]])
    chances = pick_chances(team, dex, usage)
    mega_note = "second Mega Stone: you pick which one Mega Evolves each game"
    if (recs.head(10)["note"] == mega_note).any():  # say it once, not on every Mega card
        st.caption("Picks marked **2nd Mega** would be your second Mega Stone: you choose which one Mega "
                   "Evolves each game.")
    full = len(team) >= SLOTS
    top = recs.head(10)
    # a full team can't add any of them: the top 3, the rest on request (keeps the phone scroll short)
    shown_all = len(top)
    if full and not st.session_state.get("rec_show_all", False):
        top = top.head(3)
    for i, row in top.iterrows():
        if i % 2 == 0:  # a new row per pair keeps 1, 2, 3... in order when columns stack on a phone
            cols = st.columns(2)
        with cols[i % 2]:
            with st.container(border=True, key=f"rec_card_{i}"):
                form = dex.get_species(row["form"])
                img = f"<img class='card-sprite' src='{sprite(form, dex)}' alt=''>" if form is not None else ""
                sub = f"Usually plays: {row['usually plays']}" if usage else ""
                st.markdown(  # sprite beside the name (not on its own row) so cards stay short on a phone
                    f"<div class='card-head'>{img}<div><b>{i + 1}. {row['pokemon']}</b> "
                    f"<span class='rec-score' title='Overall score for your team, out of 100'>{row['score']:.0f}/100</span>"
                    + (" <span class='rec-score'>2nd Mega</span>" if row["note"] == mega_note else "") + "<br>"
                    f"{type_badges(row['types'].split('/'))}<br>"
                    f"<span class='rec-sub'>{sub}</span></div></div>",
                    unsafe_allow_html=True,
                )
                chance = chances.get(dex.sheet_id(form)) if form is not None else None
                if chance is not None and chance >= 0.005:
                    st.caption(f"Players with your team pick it next **{chance:.0%}** of the time.")
                shown, rest = card_split(row, weights)
                st.markdown(shown or "Solid all-round pick.")
                if rest:
                    with st.expander(f"{rest.count(chr(10)) + 1} more reason{'s' if rest.count(chr(10)) else ''}"):
                        st.markdown(rest)
                if row["note"] and row["note"] != mega_note:
                    st.caption(f"Note: {row['note']}")
                if not full:  # a full team is explained once above the list
                    st.button(
                        f"Add {row['pokemon']} to team",
                        key=f"rec_add_{row['pokemon']}", width="stretch",
                        on_click=add_to_team, args=(row["pokemon"], dex, usage),
                        help="Adds its most popular set to the first empty slot",
                    )
    if full and shown_all > 3:   # under the cards, so it reads "show more"
        st.toggle(f"Show all {shown_all} picks", key="rec_show_all")
    with st.expander("Fine-tune the ranking"):
        weight_sliders(mode)
        if mode == "popular":
            accuracy_note(fmt)
        st.markdown("**Score breakdown** (each signal 0-1)")
        st.dataframe(
            recs.drop(columns=["form", "starts", "extra_mega", "parts", "credited"], errors="ignore"), hide_index=True,
            width="stretch",
            column_config={
                "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%.0f"),
                **{c: st.column_config.NumberColumn(SIGNALS[c], format="%.2f", width="small")
                   for c in ["synergy", "defense", "offense", "roles", "meta", "plan"]},
                "why": st.column_config.TextColumn(width="large"),
            },
        )


SIGNALS = {"synergy": "Pairs with", "defense": "Covers", "offense": "Hits", "roles": "Adds",
           "meta": "Popularity", "plan": "Game plan"}


EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"


def accuracy_note(fmt) -> None:
    """Show how the recommender scored against real tournament teams, if an evaluation exists."""
    path = EVAL_DIR / f"{fmt.regulation}.json"
    if not fmt.is_doubles or not path.exists():
        return
    report = json.loads(path.read_text())
    tuned = report["results"].get("tuned weights", {})
    st.markdown(f"**How accurate is this?** Top-10 hit rate {tuned.get('hit@10', 0):.0%} on real "
                "tournament teams")
    st.caption(
        f"Tested on {report['test_teams']:,} teams from {report['test_tournaments']} Limitless tournaments "
        f"({report['test_dates'][0]} to {report['test_dates'][1]}): hide one member of a real team, give the "
        "other five to the recommender, and see where the hidden Pokémon ranks among about "
        f"{report['candidate_pool']} candidates. "
        + (f"The teammate model learned from the {report['pairing_teams']:,} oldest teams (and older replays) and "
           f"the weights were tuned on the next {report['train_teams']:,}" if report.get("pairing_teams") else
           f"Weights were tuned on {report['train_teams']:,} older teams")
        + " only, so these numbers are a forward-in-time test."
    )
    rows = [{"model": name, "top 1": m["hit@1"], "top 5": m["hit@5"], "top 10": m["hit@10"], "MRR": m["mrr"]}
            for name, m in report["results"].items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="percent" if c != "MRR" else "%.3f")
                                for c in ["top 1", "top 5", "top 10", "MRR"]})
