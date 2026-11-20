"""Sidebar: format picker, data info, paste import/export, example team."""

from __future__ import annotations

import streamlit as st

from src.dex import Dex, load_dex
from src.formats import DEFAULT_FORMAT, FORMATS
from src.paste import export_paste, parse_paste
from src.usage import UsageData, load_usage
from ui.state import current_team, load_team
from ui.url_state import share_link

# A real winning team: 1st of 121 players (10-1) at a Limitless tournament on 2026-11-14. The app
# grades it Strong; the old example (Garganacl, 0.1% of teams) graded Weak, a poor first impression.
SAMPLE_TEAM = """Aerodactyl @ Aerodactylite
Ability: Unnerve
EVs: 2 HP / 32 Atk / 32 Spe
Jolly Nature
- Rock Slide
- Dual Wingbeat
- Tailwind
- Wide Guard

Sylveon @ Fairy Feather
Ability: Pixilate
EVs: 25 HP / 28 Def / 10 SpA / 3 Spe
Modest Nature
- Hyper Voice
- Quick Attack
- Hyper Beam
- Detect

Charizard @ Charizardite Y
Ability: Blaze
EVs: 2 HP / 32 SpA / 32 Spe
Modest Nature
- Heat Wave
- Weather Ball
- Solar Beam
- Protect

Kingambit @ Focus Sash
Ability: Defiant
EVs: 32 HP / 32 Atk / 2 SpD
Adamant Nature
- Kowtow Cleave
- Sucker Punch
- Iron Head
- Low Kick

Farigiraf @ Sitrus Berry
Ability: Armor Tail
EVs: 32 HP / 20 Def / 14 SpD
Relaxed Nature
- Psychic
- Thunderbolt
- Trick Room
- Protect

Garchomp @ Life Orb
Ability: Rough Skin
EVs: 2 HP / 32 Atk / 32 Spe
Jolly Nature
- Dragon Claw
- Stomping Tantrum
- Earthquake
- Protect
"""


EXAMPLE_NOTE = "Loaded the example: the team that won a 121-player tournament on Nov 14 (10-1)."


def load_example(dex: Dex) -> None:
    load_team(parse_paste(SAMPLE_TEAM, dex)[0])
    st.session_state["url_notice"] = EXAMPLE_NOTE


def import_paste(dex: Dex, key: str) -> None:
    """Callback: load the team pasted into the text area `key`, keeping any warnings to show."""
    team, warnings = parse_paste(st.session_state.get(key, ""), dex)
    load_team(team)
    st.session_state["import_warnings"] = warnings


def notices() -> None:
    """Import / link messages, shown in the page (the sidebar is hidden on a phone)."""
    notice = st.session_state.pop("url_notice", None)
    if notice:
        st.success(notice)
    for w in st.session_state.pop("import_warnings", []):
        st.warning(w)


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
            if usage.from_replays:
                r = usage.recent
                from src.replays import day_range
                st.caption(f"Usage and sets: replays {day_range(r['first_day'], r['last_day'])} ({r['teams']:,} teams). "
                           "Smogon's monthly stats for this regulation aren't out yet.")
            elif usage.recent:
                r = usage.recent
                from src.replays import day_range
                st.caption(f"Usage: replays {day_range(r['first_day'], r['last_day'])} ({r['teams']:,} teams "
                           f"rated {r['min_rating']}+); sets: Smogon {info['month']}")
            else:
                st.caption(f"Usage: Smogon {info['month']}, {info['battles']:,} battles rated {info['cutoff']}+")
        else:
            st.caption("No usage stats for this format yet - recommendations use type and role fit only.")
        st.toggle("Auto-fill popular sets", value=True, key="autofill",
                  help="When you pick a Pokémon, fill in its most-used item, ability, spread and moves.")

        st.divider()
        st.subheader("Import / export")
        paste = st.text_area("Showdown paste", height=150, placeholder="Paste a team here…",
                             label_visibility="collapsed", key="paste_side")
        c1, c2 = st.columns(2)
        c1.button("Import", width="stretch", disabled=not paste.strip(),
                  on_click=import_paste, args=(dex, "paste_side"))
        c2.button("Example team", width="stretch", help="The team that won a 121-player Reg M-C tournament on Nov 14",
                  on_click=load_example, args=(dex,))

        team = current_team()
        if team:
            text = export_paste(team)
            with st.expander("Export paste"):
                st.code(text, language=None)
            st.download_button("Download .txt", text, file_name="champions-team.txt", width="stretch")

            st.divider()
            st.subheader("Share")
            st.caption("This page's address always holds your current team (and Compare's saved version), "
                       "so a refresh or a bookmark keeps it. To keep several teams, use My teams on the Team tab.")
            with st.expander("Copy a link to this team"):  # the link is long: keep it out of the way
                st.code(share_link(team, fmt_id), language=None, wrap_lines=True)
        st.button("Clear team", width="stretch", type="secondary", on_click=load_team, args=([],))
        st.caption("Light or dark: ⋮ menu (top right), then Settings.")
        st.caption(f"Legality data: Pokémon Showdown ({dex.format_name}), exported {dex.generated_at}.")
    return fmt_id, dex, usage
