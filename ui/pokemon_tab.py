"""Pokémon tab: how one Pokémon is played. Who it's paired with, the team styles it shows up on, the sets
real players run, what it beats and what beats it, real teams to start from, then the ladder detail."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dex import Dex
from src.paste import export_paste
from src.presets import presets_for
from src.roles import meta_roles, role_text
from src.stats import format_sps
from src.usage import UsageData
from ui import core_report as R
from ui.common import SLOTS, anchor_id, jump_row, sprite, type_badges, no_usage
from ui.meta_tab import bar_section, replay_line, species_effect, what_wins_section
from ui.state import add_set_to_team


def _mini_cards(entries: list[tuple[str, str]], dex: Dex) -> str:
    """Small sprite + name + one line, in a row that wraps (three fit across a phone)."""
    cells = []
    for name, sub in entries:
        s = dex.get_species(name)
        img = f"<img src='{sprite(s, dex)}' alt=''>" if s is not None else ""
        cells.append(f"<div class='mini-mon'>{img}<div><b>{name}</b><br><span>{sub}</span></div></div>")
    return "<div class='mini-row'>" + "".join(cells) + "</div>"


def _build_around(base: str, team_size: int) -> None:
    """Open the builder (on the empty Team screen, else Recommendations) with this Pokémon picked."""
    st.session_state["build_core"] = base
    st.session_state["main_tabs"] = "Team" if team_size == 0 else "Recommendations"


def _section(title: str, sub: str = "") -> None:
    st.markdown(f"<div class='box-title' id='{anchor_id(title)}'>{title}"
                + (f" <span class='box-sub'>{sub}</span>" if sub else "") + "</div>", unsafe_allow_html=True)


def pokemon_tab(dex: Dex, usage: UsageData | None, team_size: int, fmt) -> None:
    if usage is None:
        no_usage(fmt, "No usage stats for this format yet.")
        return
    from src.builder import core_set as builder_set
    from ui.analysis_tab import _tournament_teams
    options = [n for n, _ in usage.ranked()]
    name = st.selectbox("Pokémon", options, key="poke_name",
                        help="Sorted by usage. Megas have their own entry. Or tap one in **The meta** at the bottom.")
    species = dex.get_species(name)
    if species is None:
        return
    pset = builder_set(name, dex, usage)
    form = pset.battle_form(dex) if pset else species
    root = dex.sheet_id(species)
    doubles = fmt.is_doubles

    # header
    st.markdown(  # sprite beside the name, so the header stays one block on a phone
        f"<div class='card-head'><img class='card-sprite' src='{sprite(species, dex)}' alt=''><div>"
        f"<div class='box-title' style='margin:0'>{name}</div>{type_badges(species.types)} · "
        f"{usage.usage(name):.1f}% of ladder teams ({usage.window()})</div></div>", unsafe_allow_html=True)
    st.markdown("**Usually plays:** " + role_text(meta_roles(name, usage, dex, doubles), 6, True))
    sheet_names = usage.team_sheet_usage(dex)
    base = next((n for n in sheet_names if dex.get_species(n) and dex.sheet_id(dex.get_species(n)) == root), None)
    b = st.columns(2)
    if base:
        b[0].button(f"Build a team around {base}", type="primary", width="stretch", key="poke_build",
                    on_click=_build_around, args=(base, team_size))
    if team_size < SLOTS and pset is not None:
        b[1].button(f"Add {name} to my team", width="stretch", on_click=add_set_to_team, args=(pset,),
                    key="poke_add")

    jump_row(["Usually paired with", "How it's built", "Against the top 30", "Real teams with it", "The meta"])

    # results, in one line each
    idx = R.index(fmt.id)
    row = (idx or {}).get("pokemon", {}).get(root)
    teams = _tournament_teams(fmt.regulation)
    tour = None
    results = []
    if row:
        mega = form is not None and form.is_mega and row.get("mega_rated")
        n, won, exp = ((row["mega_rated"], row["mega_rated_won"], row["mega_expected"]) if mega else
                       (row["rated"], row["rated_won"], row["rated_expected"]))
        when = f"{idx['from'][5:].replace('-', '/')}–{idx['to'][5:].replace('-', '/')}"
        results.append(f"**Ladder & Bo3** ({when}, on {row.get('players', 0):,} players' teams): "
                       + ("when it Mega Evolved, " if mega else "when brought, ") + R.vs_ratings(won, n, exp) + ".")
    if teams:
        from src.core_report import tournament_core
        tour = tournament_core(root, teams, dex, form.required_item if form is not None and form.is_mega else None)
        if tour["teams"]:
            w, l = tour["wins"], tour["losses"]
            results.append(f"**Tournaments:** {tour['teams']:,} team{'s' if tour['teams'] != 1 else ''} went "
                           f"{w:,}–{l:,} ({w / max(w + l, 1):.0%}, against {tour['base']:.0%} for all teams).")
    if results:
        st.markdown("\n".join(f"- {x}" for x in results))
        st.caption("Skill decides most games, so each win rate sits next to what the players' ratings alone would "
                   "predict. Better than expected means the Pokémon itself is pulling weight.")
    thin = R.thin_line(name, pset, dex, usage, fmt, counts=False)
    if thin:
        st.caption(thin)

    # partners and team styles
    if row and row.get("partners"):
        partners = dict(zip(R.names(row["partners"], dex), row["partners"].values()))
        _section("Usually paired with", "share of its teams")
        top = list(partners.items())
        st.markdown(_mini_cards([(k, f"{v:.0%}") for k, v in top[:3]], dex), unsafe_allow_html=True)
        if len(top) > 3:
            st.caption("Also: " + R.pct_list(dict(top[3:]), n=4))
    if row and row.get("styles"):
        _section("Team styles", "its teams carry a setter for")
        st.markdown(" · ".join(f"**{k}** {v:.0%}" for k, v in row["styles"].items()))

    # how it's built
    _section("How it's built")
    sheet = None
    if pset is not None and getattr(usage, "sheet_sets", None):
        from src.sheet_sets import MIN_SHEETS, sheet_key
        sheet = usage.sheet_sets.get(sheet_key(pset, dex))
    if pset is not None:
        from src.sheet_sets import MODE_SHARE
        if sheet and sheet["n"] >= MIN_SHEETS:
            source = ("the full set most players run on real team sheets" if sheet.get("mode_n", 0) >= MODE_SHARE * sheet["n"]
                      else "the four moves most often on real team sheets")
        else:
            source = "ladder stats (too few team sheets yet)"
        ability = f"{form.abilities[0]} (as a Mega)" if form is not None and form.is_mega else pset.ability
        st.markdown(f"**{pset.species}** @ {pset.item or 'no item'} · {ability} · {pset.nature}  \n"
                    + " / ".join(pset.moves) + f"  \n<span class='rec-sub'>The set used everywhere in the app (autofill, builder, Matchups): {source}.</span>",
                    unsafe_allow_html=True)
    if sheet and sheet["n"] >= 3:
        name_of = lambda m: dex.moves[m]["name"] if m in dex.moves else m  # noqa: E731
        st.caption(f"Moves on {sheet['n']} players' team sheets: "
                   + R.pct_list({name_of(m): v for m, v in sheet.get("moves", {}).items()}, n=6)
                   + (f" · natures: {tour and R.pct_list(tour['natures'], n=3) or ''}" if tour and tour["natures"] else ""))

    # matchups
    if pset is not None:
        calcs = R.matchups(fmt.id, fmt.regulation, export_paste([pset]), doubles)
        after = R.setup(fmt.id, fmt.regulation, export_paste([pset]), doubles)
        if calcs["beats"] or calcs["threats"]:
            _section("Against the top 30", "damage calcs, one-on-one")
            c = st.columns(2)
            with c[0]:
                st.markdown("**Beats**")
                st.markdown(_mini_cards([(n, x) for n, x in calcs["beats"][:4]], dex), unsafe_allow_html=True)
            with c[1]:
                st.markdown("**Beaten by**")
                st.markdown(_mini_cards([(n, x) for n, x in calcs["threats"][:4]], dex) if calcs["threats"]
                            else "Nothing in the top 30 beats it one-on-one.", unsafe_allow_html=True)
        if after:
            from src.setup import boost_text
            lo, hi = after["speed"]
            text = (f"**After one {after['move']}** ({boost_text(after['boosts'])}"
                    + (f"; Speed {lo} → {hi}" if hi != lo else "") + "), if it gets the turn: "
                    f"KOs {after['ohko'][1]} of the top {after['total']} in one hit ({after['ohko'][0]} before)")
            if after["beats"]:
                text += "; now beats " + ", ".join(n for n, _ in after["beats"][:4])
            if after["outspeeds"]:
                text += f"; outspeeds {len(after['outspeeds'])} more"
            st.markdown(text + ".")

    # real teams
    proven = []
    for t in (row or {}).get("teams", []):
        proven.append((f"Ladder{' Bo3' if t['bo3'] else ''} win, {t['rating']} rated, "
                       f"{t['date'][5:].replace('-', '/')}: " + ", ".join(t["team"]), t["team"]))
    if tour:
        from src.similar_teams import ordinal
        for t in tour["best"]:
            place = f"{ordinal(t['placing'])} of {t['players']}" if t.get("placing") else "Tournament"
            proven.append((f"{place} ({t['wins']}–{t['losses']}), {t['date'][5:].replace('-', '/')}: "
                           + ", ".join(t["team"]), t["team"]))
    if proven:
        _section("Real teams with it")
        pick = st.selectbox("Real team", range(len(proven)), key="poke_proven", label_visibility="collapsed",
                            format_func=lambda i: proven[i][0])
        st.button("Load this team", key="poke_proven_load", width="stretch",
                  on_click=R.load_real, args=(proven[pick][1], name, pset, dex, usage),
                  help="Replaces your team. Each Pokémon gets the set the builder would give it.")

    # the ladder detail, folded away
    source = "replays" if usage.from_replays else f"Smogon {usage.info.get('month', '')}"
    with st.expander(f"Ladder stats ({source}, each move counted on its own): moves, items, spreads, presets"):
        learned = species_effect(name, dex, fmt.regulation)
        if learned:
            st.caption(learned)
        replay = replay_line(name, dex, fmt.id)
        if replay:
            st.markdown(replay)
        c1, c2 = st.columns(2)
        with c1:
            bar_section("Moves", usage.section(name, "moves"), dex, "moves", 10)
            bar_section("Abilities", usage.section(name, "abilities"), dex, "abilities", 4)
        with c2:
            bar_section("Items", usage.section(name, "items"), dex, "items", 8)
            bar_section("Teammates", usage.section(name, "teammates"), dex, "teammates", 8)
        spreads = usage.section(name, "spreads")
        if spreads:
            st.markdown("**Common spreads** (nature: HP/Atk/Def/SpA/SpD/Spe Stat Points)")
            sp = pd.DataFrame([(k.replace(":", " · ", 1), round(v)) for k, v in list(spreads.items())[:6]],
                              columns=["spread", "% of sets"])
            st.dataframe(sp, hide_index=True, width="stretch",
                         column_config={"% of sets": st.column_config.NumberColumn(format="%d%%")})
        counters = usage.section(name, "counters")
        if counters:
            st.markdown("**Checks & counters** (how often each KOs or forces it out)")
            st.dataframe(pd.DataFrame(list(counters.items()), columns=["Pokémon", "% KO / switch"]),
                         hide_index=True, width="stretch")
        presets = [p for p in presets_for(name, usage, dex) if p.source == name] or presets_for(name, usage, dex)
        if presets:
            st.markdown("**Presets** (assembled from the most common items, moves and spreads)")
            for i, preset in enumerate(presets[:3]):
                with st.container(border=True):
                    st.markdown(f"**{preset.name}** · ~{preset.weight:.0f}% of sets  \n"
                                f"{preset.pset.ability} · {format_sps(preset.pset.sps) or 'no Stat Points'}  \n"
                                + " / ".join(preset.pset.moves))
                    if team_size < SLOTS:
                        st.button("Add to team", key=f"poke_preset_{name}_{i}", width="stretch",
                                  on_click=add_set_to_team, args=(preset.pset,))
    meta_section(dex, usage, fmt)


def _open_from_board(names: list[str]) -> None:
    rows = st.session_state.get("poke_board", {}).get("selection", {}).get("rows", [])
    if rows:
        st.session_state["poke_name"] = names[rows[0]]


def _change(a: float, b: float) -> str:
    """'5% → 7%', with a decimal when whole percents would read as no change ('4.6% → 5.2%')."""
    if f"{a:.0%}" == f"{b:.0%}":
        return f"{a:.1%} → {b:.1%}"
    return f"{a:.0%} → {b:.0%}"


def _open_rising() -> None:
    """Tapped a riser: open it at the top of this tab (the pill doesn't stay selected)."""
    pick = st.session_state.get("rising_pick")
    if pick:
        st.session_state["poke_name"] = pick
    st.session_state["rising_pick"] = None


def rising_section(dex: Dex, usage: UsageData, fmt) -> None:
    """Rising this week (src/replays.rising): the biggest gains in team share over last week."""
    from src.replays import day_range, load_rising
    up = load_rising(fmt.id)
    if not up or not up.get("pokemon"):
        return
    names = usage.team_sheet_usage(dex)
    by_root = {}
    for n in names:   # the usage entry to open for each team-sheet id (the base, not a Mega entry)
        sp = dex.get_species(n)
        if sp is not None:
            by_root.setdefault(dex.sheet_id(sp), n)
    rows = [(by_root.get(r["id"]) or (dex.get_species(r["id"]).name if dex.get_species(r["id"]) else r["id"]), r)
            for r in up["pokemon"]]
    shown = {n: r for n, r in rows if n in set(names)}
    if not shown:
        return
    before = (up.get("before_first_day"), up.get("before_last_day"))
    if not all(before):   # a summary from before weeks started on Sunday
        from datetime import date, timedelta
        start = date.fromisoformat(up["first_day"])
        before = ((start - timedelta(days=7)).isoformat(), (start - timedelta(days=1)).isoformat())
    st.pills(f"**Rising this week**: share of teams {day_range(*before)} → "
             f"{day_range(up['first_day'], up['last_day'])} (tap to open)", list(shown),
             key="rising_pick", on_change=_open_rising,
             format_func=lambda n: f"{n}  {_change(shown[n]['before'], shown[n]['share'])}")
    st.caption(f"Biggest gains in share of teams this week vs last ({up['teams']:,} vs {up['teams_before']:,} "
               f"teams, players rated {up['min_rating']}+). Weeks start on Sunday (UTC); early on a Sunday it "
               "compares the last two full weeks. In past weeks, 84% of risers were still above their old share "
               "the week after, so these point at where the ladder is heading, not just noise "
               "(labs/rising_lab.py)."
               + (f" The usage board below covers the {usage.window()}, so it won't match either week exactly."
                  if usage.recent else ""))


def meta_section(dex: Dex, usage: UsageData, fmt) -> None:
    """The usage leaderboard (tap a row to open that Pokémon above) and what wins games."""
    _section("The meta")
    if usage.from_replays:
        r = usage.recent
        from src.replays import day_range
        st.caption(f"Usage and sets: {r['teams']:,} teams from ladder and Bo3 replays, "
                   f"{day_range(r['first_day'], r['last_day'])} (updated twice a day). Smogon's monthly stats for "
                   "this regulation aren't out yet; Pokémon without enough open team sheets use their last "
                   "regulation's sets.")
    elif usage.recent:
        r = usage.recent
        from src.replays import day_range
        st.caption(f"Usage: {r['teams']:,} teams from ladder and Bo3 replays, {day_range(r['first_day'], r['last_day'])}, "
                   f"players rated {r['min_rating']}+ (updated twice a day). Sets, items and spreads: Smogon ladder "
                   f"stats for {usage.info['month']}.")
    rising_section(dex, usage, fmt)
    col = f"usage %, {usage.window()}"
    board = pd.DataFrame(usage.ranked(60), columns=["Pokémon", col])
    names = list(board["Pokémon"])
    board.index += 1
    st.dataframe(board, width="stretch", height=360, key="poke_board", on_select=lambda: _open_from_board(names),
                 selection_mode="single-row",
                 column_config={col: st.column_config.ProgressColumn(
                     col, min_value=0, max_value=float(board[col].max()), format="%.1f%%")})
    st.caption("Tap a row to open that Pokémon at the top of this tab.")
    what_wins_section(fmt.regulation, dex)


__all__ = ["pokemon_tab", "meta_section"]
