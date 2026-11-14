"""Damage calc tab: any of your Pokemon or a meta Pokemon's popular set, against any other."""

from __future__ import annotations

import pandas as pd
import streamlit as st

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


def _side(label: str, options: dict[str, PokemonSet], default: int, key: str, dex: Dex, stats: list[str]):
    names = list(options)
    choice = st.selectbox(label, names, index=min(default, len(names) - 1), key=f"calc_{key}")
    pset = options[choice]
    st.caption(_set_caption(pset, dex))
    cols = st.columns(len(stats))
    boosts = {s: cols[i].selectbox(f"{STAT_LABELS[s]} stage", STAGES, index=6, key=f"calc_{key}_{s}",
                                   format_func=lambda v: f"{v:+d}" if v else "0")
              for i, s in enumerate(stats)}
    return pset, {s: v for s, v in boosts.items() if v}


def damage_tab(team: list[PokemonSet], dex: Dex, usage: UsageData | None, fmt) -> None:
    options = _choices(team, usage, dex)
    if len(options) < 2:
        st.info("Add Pokémon to your team (or pick a format with usage data) to run calcs.")
        return
    how_it_works("Level 50 Champions damage, using the same formula and rounding as Pokémon Showdown "
                 "(checked roll-for-roll against Showdown's engine in the test suite). Pick any of your Pokémon "
                 "or a meta Pokémon's most popular set on either side.", "About these numbers")

    left, right = st.columns(2)
    with left:
        attacker, att_boosts = _side("Attacker", options, 0, "att", dex, ["atk", "spa", "def"])
    with right:
        defender, def_boosts = _side("Defender", options, len(team) if len(team) < len(options) else 1,
                                     "def", dex, ["def", "spd"])
        full_hp = st.checkbox("Defender at full HP", value=True,
                              help="Matters for Multiscale and Shadow Shield.")

    st.markdown("**Field**")
    fc = st.columns(4)
    weather = WEATHER[fc[0].selectbox("Weather", list(WEATHER), key="calc_weather")]
    terrain = TERRAIN[fc[1].selectbox("Terrain", list(TERRAIN), key="calc_terrain")]
    screen = fc[2].checkbox("Reflect / Light Screen", key="calc_screen")
    crit = fc[3].checkbox("Critical hit", key="calc_crit")
    gc = st.columns(4)
    helping = gc[0].checkbox("Helping Hand", key="calc_hh", disabled=not fmt.is_doubles)
    spread_both = gc[1].checkbox("Spread moves hit both foes", value=True, key="calc_spread",
                                 disabled=not fmt.is_doubles,
                                 help="In doubles, moves that hit both foes do 75% damage.")
    both_ways = gc[2].checkbox("Also show the defender's attacks", key="calc_both")

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
            rows.append({
                "move": move["name"], "damage": f"{result.min}-{result.max}",
                "% of HP": f"{result.min_pct:.1f}-{result.max_pct:.1f}%",
                "max %": min(result.max_pct, 100.0), "result": result.verdict,
                "notes": "; ".join(result.notes),
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

    show(attacker, defender, att_boosts, def_boosts,
         f"{attacker.nickname or attacker.species} → {defender.nickname or defender.species}")
    if both_ways:
        reverse_att = {s: v for s, v in def_boosts.items() if s in {"atk", "spa"}}
        show(defender, attacker, reverse_att, {},
             f"{defender.nickname or defender.species} → {attacker.nickname or attacker.species}")
    if to_id(attacker.item) == "choicescarf" or to_id(defender.item) == "choicescarf":
        st.caption("Choice Scarf only changes Speed, so it doesn't affect these numbers.")
