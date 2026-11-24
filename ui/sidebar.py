"""Sidebar: format picker, data info, paste import/export, example team."""

from __future__ import annotations

import streamlit as st

from src.dex import Dex, load_dex
from src.formats import DEFAULT_FORMAT, FORMATS
from src.paste import export_paste, parse_paste
from src.usage_counts import count
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


NEXT = "Next: the **Matchups** tab shows how it does against the meta."
# A regulation's hand-picked example (checked to grade well); one without gets its newest big tournament
# winner, and before its first tournaments the last regulation's pick if it's still legal.
PINNED = {"regmc": (SAMPLE_TEAM, "the team that won a 121-player Reg M-C tournament on Nov 14 (10-1)")}
MIN_PLAYERS = 32     # a winner of a smaller event says little
RECENT_DAYS = 14     # among the last two weeks' winners, the biggest event


@st.cache_data(show_spinner=False)
def _newest_winner(regulation: str, format_id: str) -> tuple[str, str] | None:
    """(paste, description) of the winner of the biggest recent tournament in the regulation, legal in it."""
    from datetime import date, timedelta
    from src.evaluate import TOURNAMENT_DIR, load_tournament_teams
    from src.legality import check_team
    path = TOURNAMENT_DIR / f"{regulation}.json"
    if not path.exists():
        return None
    import json
    rows = [r for r in json.loads(path.read_text()).get("teams", [])
            if r.get("placing") == 1 and (r.get("players") or 0) >= MIN_PLAYERS and r.get("date")]
    if not rows:
        return None
    since = (date.fromisoformat(max(r["date"] for r in rows)) - timedelta(days=RECENT_DAYS)).isoformat()
    wanted = {(r.get("tournament"), r.get("player")) for r in rows if r["date"] >= since}
    dex = load_dex(regulation)
    teams = load_tournament_teams(regulation, dex, usage=load_usage(format_id),
                                  keep=lambda r: (r.get("tournament"), r.get("player")) in wanted)
    teams = [t for t in teams if not any(i.level == "error" for i in check_team(t["sets"], dex))]
    if not teams:
        return None
    best = max(teams, key=lambda t: (t.get("players") or 0, t.get("date") or ""))
    day = date.fromisoformat(best["date"])
    record = f" ({best['wins']}-{best['losses']})" if best.get("wins") is not None else ""
    return (export_paste(best["sets"]),
            f"the team that won a {best['players']}-player tournament on {day:%b} {day.day}{record}; "
            "team lists don't show Stat Points, so its spreads are the most common ones")


def example_for(fmt_id: str, dex: Dex) -> tuple[str, str] | None:
    """(paste, description) of the example team for a format, or None when there's nothing legal to show."""
    fmt = FORMATS[fmt_id]
    if fmt.regulation in PINNED:
        return PINNED[fmt.regulation]
    if fmt.is_doubles:
        found = _newest_winner(fmt.regulation, fmt_id)
        if found:
            return found
    from src.legality import check_team
    prev = FORMATS.get(fmt.previous) or next((f for f in FORMATS.values() if f.regulation != fmt.regulation
                                              and f.regulation in PINNED), None)
    if prev and prev.regulation in PINNED:
        paste, text = PINNED[prev.regulation]
        team, warnings = parse_paste(paste, dex)
        if len(team) == 6 and not warnings and not any(i.level == "error" for i in check_team(team, dex)):
            return paste, f"{text}, from the last regulation until this one has tournaments of its own"
    return None


def load_example(dex: Dex) -> None:
    count("example team")
    fmt_id = st.session_state.get("format", DEFAULT_FORMAT)
    found = example_for(fmt_id if fmt_id in FORMATS else DEFAULT_FORMAT, dex)
    if not found:
        st.session_state["url_notice"] = "No example team for this format yet: its first tournaments are still to come."
        return
    paste, text = found
    load_team(parse_paste(paste, dex)[0])
    st.session_state["url_notice"] = f"Loaded the example: {text}. {NEXT}"


def import_paste(dex: Dex, key: str) -> None:
    """Callback: load the team pasted into the text area `key`, keeping any warnings to show."""
    team, warnings = parse_paste(st.session_state.get(key, ""), dex)
    if team:
        count("pasted a team")
    load_team(team)
    st.session_state["import_warnings"] = warnings


def notices() -> None:
    """Import / link messages, shown in the page (the sidebar is hidden on a phone)."""
    # On the first visit the page reruns once more when the browser's saved teams arrive; a message popped
    # on the run before that was never seen ("Loaded a team from the link"), so keep it until then.
    from ui.team_store import store
    take = st.session_state.pop if store().ready else st.session_state.get
    notice = take("url_notice", None)
    if notice:
        st.success(notice)
    for w in take("import_warnings", None) or []:
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
        example = example_for(fmt_id, dex)
        c2.button("Example team", width="stretch", disabled=example is None,
                  help=(example[1][0].upper() + example[1][1:]) if example else "None yet for this format",
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
        from ui.start_here import feedback_url
        st.caption(f"[Send feedback]({feedback_url()}): something confusing, wrong or missing.")
        st.caption("Light or dark: ⋮ menu (top right), then Settings.")
        st.caption(f"Legality data: Pokémon Showdown ({dex.format_name}), exported {dex.generated_at}.")
    return fmt_id, dex, usage
