"""Damage calc tab: any of your Pokemon or a meta Pokemon's popular set, against any other."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.setup import boost_text, setup_move

from src.damage import Battler, Field, calculate
from src.dex import STAT_LABELS, Dex, to_id
from src.stats import format_sps
from src.team import PokemonSet
from src.usage import UsageData
from ui.theme import how_it_works

WEATHER = {"None": None, "Sun": "sun", "Rain": "rain", "Sand": "sand", "Snow": "snow"}
TERRAIN = {"None": None, "Grassy": "grassy", "Electric": "electric", "Psychic": "psychic", "Misty": "misty"}
STAGES = list(range(-6, 7))


def _choices(team: list[PokemonSet], usage: UsageData | None, dex: Dex) -> dict[str, PokemonSet]:
    options: dict[str, PokemonSet] = {}
    for pset in team:
        options[f"Yours: {pset.nickname or pset.species}"] = pset
    if usage is not None:
        for name, _ in usage.ranked(60):
            pset = usage.popular_set(name, dex)
            if pset is not None:
                options[f"Meta: {name}"] = pset
    return options


def _set_caption(pset: PokemonSet, dex: Dex) -> str:
    form = pset.battle_form(dex)
    ability = pset.battle_ability(dex)
    return (f"{form.name} @ {pset.item or 'no item'} · {ability} · {pset.nature} · "
            f"{format_sps(pset.sps) or 'no Stat Points'}")


def _pick(label: str, options: dict[str, PokemonSet], default: int, key: str, dex: Dex) -> PokemonSet:
    names = list(options)
    choice = st.selectbox(label, names, index=min(default, len(names) - 1), key=f"calc_{key}")
    pset = options[choice]
    st.caption(_set_caption(pset, dex))
    return pset


def _stages(label: str, key: str, stats: list[str]) -> dict:
    cols = st.columns(len(stats))
    ss = st.session_state
    # a stage set by "Apply one Dragon Dance" lives in session state: no widget default then
    boosts = {s: cols[i].selectbox(f"{label} {STAT_LABELS[s]}", STAGES, key=f"calc_{key}_{s}",
                                   format_func=lambda v: f"{v:+d}" if v else "0",
                                   **({} if f"calc_{key}_{s}" in ss else {"index": 6}))
              for i, s in enumerate(stats)}
    return {s: v for s, v in boosts.items() if v}


def _apply_setup(boosts: dict) -> None:
    """One use of the attacker's setup move, on top of the stages already set (capped at +6)."""
    ss = st.session_state
    for stat in ("atk", "spa", "def"):
        if boosts.get(stat):
            ss[f"calc_att_{stat}"] = max(-6, min(6, int(ss.get(f"calc_att_{stat}", 0)) + boosts[stat]))


def damage_tab(team: list[PokemonSet], dex: Dex, usage: UsageData | None, fmt) -> None:
    options = _choices(team, usage, dex)
    if len(options) < 2:
        st.info("Add Pokémon to your team (or pick a format with usage data) to run calcs.")
        return

    left, right = st.columns(2)
    with left:
        attacker = _pick("Attacker", options, 0, "att", dex)
    with right:
        defender = _pick("Defender", options, len(team) if len(team) < len(options) else 1, "def", dex)
    results = st.container()  # the numbers come first; the knobs that change them go below
    both_ways = st.toggle("Also show the defender's attacks", key="calc_both")

    ss = st.session_state
    on = sum(1 for k in ("calc_att_atk", "calc_att_spa", "calc_att_def", "calc_def_def", "calc_def_spd")
             if ss.get(k, 0)) + sum(1 for k in ("calc_screen", "calc_crit", "calc_hh") if ss.get(k)) \
        + sum(1 for k in ("calc_weather", "calc_terrain") if ss.get(k, "None") != "None") \
        + (0 if ss.get("calc_full_hp", True) else 1)
    with st.expander("Stat stages, weather and field" + (f" ({on} set)" if on else "")):
        att_boosts = _stages("Attacker", "att", ["atk", "spa", "def"])
        def_boosts = _stages("Defender", "def", ["def", "spd"])
        fc = st.columns(2)
        weather = WEATHER[fc[0].selectbox("Weather", list(WEATHER), key="calc_weather")]
        terrain = TERRAIN[fc[1].selectbox("Terrain", list(TERRAIN), key="calc_terrain")]
        gc = st.columns(3)
        screen = gc[0].checkbox("Reflect / Light Screen", key="calc_screen")
        crit = gc[1].checkbox("Critical hit", key="calc_crit")
        helping = gc[2].checkbox("Helping Hand", key="calc_hh", disabled=not fmt.is_doubles)
        hc = st.columns(2)
        spread_both = hc[0].checkbox("Spread moves hit both foes", value=True, key="calc_spread",
                                     disabled=not fmt.is_doubles,
                                     help="In doubles, moves that hit both foes do 75% damage.")
        full_hp = hc[1].checkbox("Defender at full HP", value=True, key="calc_full_hp",
                                 help="Matters for Multiscale and Shadow Shield.")
    how_it_works("Level 50 Champions damage, using the same formula and rounding as Pokémon Showdown "
                 "(checked roll-for-roll against Showdown's engine in the test suite). Pick any of your Pokémon "
                 "or a meta Pokémon's most popular set on either side.", "About these numbers")

    def table(att: PokemonSet, dfn: PokemonSet, ab: dict, db: dict) -> pd.DataFrame:
        a = Battler.from_set(att, dex, ab)
        d = Battler.from_set(dfn, dex, db)
        d.full_hp = full_hp
        rows = []
        for move_name in att.moves:
            move = dex.get_move(move_name)
            if move is None or move["category"] == "Status":
                continue
            spread = fmt.is_doubles and spread_both and move.get("spread", False)
            result = calculate(a, d, move, Field(doubles=fmt.is_doubles, spread=spread, weather=weather,
                                                 terrain=terrain, helping_hand=helping, screen=screen, crit=crit))
            rows.append({  # most telling first, so a phone shows it without scrolling sideways
                "move": move["name"], "% of HP": f"{result.min_pct:.1f}-{result.max_pct:.1f}%",
                "result": result.verdict, "max %": min(result.max_pct, 100.0),
                "damage": f"{result.min}-{result.max}", "notes": "; ".join(result.notes),
            })
        return pd.DataFrame(rows)

    def show(att, dfn, ab, db, title):
        st.markdown(f"**{title}**")
        df = table(att, dfn, ab, db)
        if df.empty:
            st.caption("No damaging moves.")
            return
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"max %": st.column_config.ProgressColumn("max %", min_value=0, max_value=100,
                                                                             format="%.0f%%")})

    with results:
        show(attacker, defender, att_boosts, def_boosts,
             f"{attacker.nickname or attacker.species} → {defender.nickname or defender.species}")
        if both_ways:
            reverse_att = {s: v for s, v in def_boosts.items() if s in {"atk", "spa"}}
            show(defender, attacker, reverse_att, {},
                 f"{defender.nickname or defender.species} → {attacker.nickname or attacker.species}")
        found = setup_move(attacker)
        if found:
            move, boosts = found
            st.button(f"Apply one {move} ({boost_text(boosts)})", key="calc_setup",
                      on_click=_apply_setup, args=(boosts,),
                      help="Adds its stat stages to the attacker below. Assumes it gets the turn to set up.")
        if to_id(attacker.item) == "choicescarf" or to_id(defender.item) == "choicescarf":
            st.caption("Choice Scarf only changes Speed, so it doesn't affect these numbers.")
