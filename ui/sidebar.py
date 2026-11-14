"""Sidebar: format picker, data info, paste import/export, example team."""

from __future__ import annotations

import streamlit as st

from src.dex import Dex, load_dex
from src.formats import DEFAULT_FORMAT, FORMATS
from src.paste import export_paste, parse_paste
from src.usage import UsageData, load_usage
from ui.state import current_team, load_team
from ui.url_state import share_link

SAMPLE_TEAM = """Garganacl @ Leftovers
Ability: Purifying Salt
EVs: 32 HP / 2 Def / 32 SpD
Careful Nature
- Salt Cure
- Body Press
- Iron Defense
- Wide Guard

Garchomp @ Garchompite Z
Ability: Rough Skin
EVs: 2 HP / 32 SpA / 32 Spe
Timid Nature
- Draco Meteor
- Earth Power
- Flamethrower
- Protect

Rillaboom @ Miracle Seed
Ability: Grassy Surge
EVs: 32 HP / 32 Atk / 2 SpD
Adamant Nature
- Fake Out
- Grassy Glide
- Wood Hammer
- U-turn

Sinistcha @ Mental Herb
Ability: Hospitality
EVs: 32 HP / 32 Def / 2 SpD
Bold Nature
- Matcha Gotcha
- Rage Powder
- Strength Sap
- Protect

Incineroar @ Sitrus Berry
Ability: Intimidate
EVs: 32 HP / 2 Atk / 32 SpD
Careful Nature
- Fake Out
- Flare Blitz
- Parting Shot
- Throat Chop

Gholdengo @ Life Orb
Ability: Good as Gold
EVs: 2 HP / 32 SpA / 32 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Nasty Plot
- Protect
"""


def sidebar() -> tuple[str, Dex, UsageData | None]:
    with st.sidebar:
        if st.session_state.get("format") not in FORMATS:
            st.session_state["format"] = DEFAULT_FORMAT
        fmt_id = st.selectbox("Format", list(FORMATS), key="format", format_func=lambda f: FORMATS[f].label)
        fmt = FORMATS[fmt_id]
        dex = load_dex(fmt.regulation)
        usage = load_usage(fmt_id)
        st.caption(f"{fmt.active} · bring 6, pick {fmt.pick} · Level 50 · 66 Stat Points")
        if usage:
            info = usage.info
            st.caption(f"Usage: Smogon {info['month']}, {info['battles']:,} battles rated {info['cutoff']}+")
        else:
            st.caption("No usage stats for this format yet - recommendations use type and role fit only.")
        st.toggle("Auto-fill popular sets", value=True, key="autofill",
                  help="When you pick a Pokémon, fill in its most-used item, ability, spread and moves.")

        st.divider()
        st.subheader("Import / export")
        paste = st.text_area("Showdown paste", height=150, placeholder="Paste a team here…",
                             label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("Import", width="stretch", disabled=not paste.strip()):
            team, warnings = parse_paste(paste, dex)
            load_team(team)
            st.session_state["import_warnings"] = warnings
            st.rerun()
        if c2.button("Example team", width="stretch",
                     help="A Garganacl team for VGC Reg M-C"):
            team, _ = parse_paste(SAMPLE_TEAM, dex)
            load_team(team)
            st.rerun()
        notice = st.session_state.pop("url_notice", None)
        if notice:
            st.success(notice)
        for w in st.session_state.pop("import_warnings", []):
            st.warning(w)

        team = current_team()
        if team:
            text = export_paste(team)
            with st.expander("Export paste"):
                st.code(text, language=None)
            st.download_button("Download .txt", text, file_name="champions-team.txt", width="stretch")

            st.divider()
            st.subheader("Share")
            st.caption("This page's address always holds your current team, so a refresh or a bookmark "
                       "keeps it. Copy the link below to send it to someone.")
            st.code(share_link(team, fmt_id), language=None, wrap_lines=True)
        if st.button("Clear team", width="stretch", type="secondary"):
            load_team([])
            st.rerun()
        st.caption("Light or dark: ⋮ menu (top right), then Settings.")
        st.caption(f"Legality data: Pokémon Showdown ({dex.format_name}), exported {dex.generated_at}.")
    return fmt_id, dex, usage
