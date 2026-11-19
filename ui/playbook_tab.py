"""Playbook tab: how to play your team against Trick Room, Tailwind, weather, Psychic Terrain and setup
sweepers. What worked for real players facing each lead (src/playbook.py), next to what your team has."""

from __future__ import annotations

import streamlit as st

from src.analysis import build_members
from src.playbook import BLURB, STYLES, setter_hits, style_setters, team_tools
from ui.common import anchor_id, jump_row, sprite
from ui.theme import how_it_works

# what each choice needs from your team (a tool from src.playbook.team_tools); None: any team can
NEEDS = {
    "Taunt or Encore on the setter": ["Taunt", "Encore"],
    "Your own Trick Room": ["Trick Room"],
    "Imprison": ["Imprison"],
    "Fake Out on the setter": ["Fake Out"],
    "Fake Out on its partner": ["Fake Out"],
    "Trick Room or speed drops": ["Trick Room", "Speed drops"],
    "Your own Tailwind": ["Tailwind"],
    "Tailwind": ["Tailwind"],
    "Led your own weather setter": ["Weather"],
    "Brought your own weather setter (not leading)": ["Weather"],
    "Used Haze, Clear Smog, Roar, Whirlwind or Encore in the game": ["Haze / phazing", "Encore"],
    "Attacked the setter": None, "Both attacked the setter": None, "Both Protected": None,
}


@st.cache_data(show_spinner=False, ttl=3600)
def _book(format_id: str) -> dict | None:
    from src.playbook import load
    return load(format_id)


@st.cache_resource(show_spinner=False)
def _setters(format_id: str) -> dict:
    from src.dex import load_dex
    from src.formats import FORMATS
    from src.usage import load_usage
    return style_setters(load_usage(format_id), load_dex(FORMATS[format_id].regulation))


def _who(choice: str, tools: dict) -> list[str] | None:
    """Your Pokémon that can make this choice; None when any team can."""
    need = NEEDS.get(choice)
    if need is None:
        return None
    return sorted({m for t in need for m in tools.get(t, [])})


SHORT = {"Used Haze, Clear Smog, Roar, Whirlwind or Encore in the game": "Haze, Roar or Encore during the game",
         "Brought your own weather setter (not leading)": "Brought your own weather setter"}


def _name(choice: str) -> str:
    return SHORT.get(choice, choice)


def _verdict(c: dict) -> str:
    if c["lo"] > 0:
        return "worked"
    if c["hi"] < 0:
        return "backfired"
    return "unclear"


def playbook_tab(team, dex, usage, fmt) -> None:
    if usage is None:
        st.info("The playbook needs usage stats for this format.")
        return
    book = _book(fmt.id)
    if not book or not book.get("styles"):
        st.info("No replay data for this format yet.")
        return
    st.subheader("How to play against…")
    how_it_works(
        f"From {sum(s['games'] for s in book['styles'].values()):,} rated ladder and Bo3 games "
        f"(last {book['days']} days, both players rated {book['min_rating']}+). For each style, the games where "
        "the opponent **led** with a Pokémon that sets it up: what you can see when you pick turn 1. Each choice "
        "is scored by how much more the players who made it won than their ratings predicted, compared with "
        "players facing the same lead who **could have made it and didn't**: for Fake Out, Taunt, Trick Room, "
        "Tailwind, speed drops and Haze, players who had the move in play (on their open team sheet, used that "
        "game, or on 40%+ of that Pokémon's sets); for leading or bringing your own weather setter, players who "
        "had one in team preview. Choices any team can make (attacking the setter, double Protect) are compared "
        "with everyone else. **Worked** / **backfired**: the 90% interval is clear of zero.\n\nThese are still "
        "associations, not proof: when a player uses a move says something about the game and the player too. "
        "Your team's tools come from its moves and abilities.",
        "Where these numbers come from")
    members = build_members(team, dex) if team else []
    tools = team_tools(members) if members else {}
    setters = _setters(fmt.id)
    styles = [s for s in sorted(book["styles"], key=lambda s: -book["styles"][s]["games"]) if s in STYLES]

    # overview: for each style, the plays that worked and whether your team can make them
    rows = []
    for style in styles:
        good = [c for c in book["styles"][style]["choices"] if _verdict(c) == "worked"]
        can = [c for c in good if (w := _who(c["choice"], tools)) is None or w]
        rows.append((style, good, can))
    if members:
        jump_row(["Against"])
        st.markdown("**Your team at a glance** (plays that worked, and how many your team can make)")
        st.markdown("\n".join(
            f"- **{style}**: " + (f"{len(can)} of {len(good)}" if good else "no clear winning play")
            + (" · missing: " + ", ".join(_name(c["choice"]).lower() for c in good if c not in can) if len(can) < len(good) else "")
            for style, good, can in rows))
    else:
        st.caption("Add your team to see which of these plays it can make.")

    st.markdown(f"<div id='{anchor_id('Against')}'></div>", unsafe_allow_html=True)
    style = st.segmented_control("Against", styles, default=styles[0], key="playbook_style") or styles[0]
    data = book["styles"][style]
    names = sorted(setters.get(style, set()), key=lambda x: -usage.usage(x))[:4]
    imgs = "".join(f"<div class='mini-mon'><img src='{sprite(dex.get_species(n), dex)}' alt=''>"
                   f"<div><b>{n}</b><br><span>{usage.usage(n):.0f}% usage</span></div></div>"
                   for n in names if dex.get_species(n))
    st.markdown(f"**{style}**: {BLURB.get(style, '')}. Common setters:", unsafe_allow_html=True)
    if imgs:
        st.markdown(f"<div class='mini-row'>{imgs}</div>", unsafe_allow_html=True)

    if style == "Psychic Terrain" or any(n.startswith("Indeedee") for n in names):
        failed = data.get("failed_fake_outs", 0)
        st.info("**Indeedee brings Psychic Terrain**: Fake Out and other priority moves fail against grounded "
                "Pokémon. Fake Out still works on a Flying type or a Levitate user, or once your own terrain "
                "setter replaces the terrain." + (f" In these games {failed:,} players clicked Fake Out into the "
                                                   "terrain anyway." if failed else ""))
    st.markdown(f"**What players facing a {style} lead did** ({data['games']:,} games)")
    def line(c: dict) -> str:
        v = _verdict(c)
        who = _who(c["choice"], tools)
        yours = ""
        if members and v == "worked":
            yours = " · any team can" if who is None else (f" · yours: {', '.join(who)}" if who else " · your team can't")
        mark = {"worked": "Worked", "backfired": "Backfired", "unclear": "Unclear"}[v]
        against = ("vs players who had it and didn't" if c.get("against") == "had it, didn't"
                   else "vs everyone else")
        return (f"- **{mark}** {_name(c['choice'])}: {c['edge']:+.1f} points {against} (90% {c['lo']:+.1f} to "
                f"{c['hi']:+.1f}; {c['n']:,} players)" + yours)

    clear = [c for c in data["choices"] if _verdict(c) != "unclear"]
    unclear = [c for c in data["choices"] if _verdict(c) == "unclear"]
    st.markdown("\n".join(line(c) for c in clear) or "No choice stood out either way.")
    if unclear:
        with st.expander(f"{len(unclear)} more choice{'s' if len(unclear) != 1 else ''} with no clear effect"):
            st.markdown("\n".join(line(c) for c in unclear))

    if members:
        hits = setter_hits(members, style, setters, usage, dex, fmt.is_doubles)
        if hits:
            st.markdown("**Your hardest hit on each setter**\n" + "\n".join(f"- {n}: {h}" for n, h in hits))
        extra = []
        if (style == "Psychic Terrain" or any(n.startswith("Indeedee") for n in names)) and tools.get("Fake Out"):
            extra.append(f"Your Fake Out users ({', '.join(tools['Fake Out'])}): against an Indeedee lead, aim it at a "
                         "Flying type or a Levitate user, or click something else.")
        if style == "Setup sweepers":
            for t in ("Unaware", "Intimidate", "Taunt", "Encore", "Haze / phazing"):
                if tools.get(t):
                    extra.append(f"{t}: {', '.join(tools[t])}")
        if style == "Trick Room" and tools.get("Trick Room"):
            extra.append(f"Your own Trick Room ({', '.join(tools['Trick Room'])}) cancels theirs if it goes second.")
        if extra:
            st.markdown("\n".join(f"- {x}" for x in extra))
    st.caption("Game-by-game plans against each meta team (bring, leads, Speed order) are on the Matchups tab.")


__all__ = ["playbook_tab"]
