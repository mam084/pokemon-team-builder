"""
Visual layer: page CSS and the "team preview" stage.

Design idea: the most recognizable screen in VGC is team preview - your six
lined up before a battle. The team strip is drawn as that stage, a deep-navy
band that stays dark in both themes, and is the one bold element on the page.
Everything else stays quiet: Streamlit's own widgets, restyled lightly, on a
cool slate page with a single cobalt accent (see .streamlit/config.toml).
"""

from __future__ import annotations

import html

import streamlit as st

from src.dex import Dex
from src.roles import role_text, set_roles
from src.team import PokemonSet
from ui.common import SLOTS, sprite, type_badges

STAGE = {"bg": "#18213a", "bg2": "#202b4a", "line": "#2e3b5f", "ink": "#eef1f8", "muted": "#a9b3c9",
         "accent": "#8fa6ff", "ok": "#5fd39a", "bad": "#ff7a7a"}


def is_dark() -> bool:
    theme = getattr(getattr(st, "context", None), "theme", None)
    return getattr(theme, "type", None) == "dark"


def inject_css() -> None:
    dark = is_dark()
    surface = "#192133" if dark else "#ffffff"
    border = "#2b3549" if dark else "#dbe1ea"
    muted = "#9aa5ba" if dark else "#5d6779"
    ink = "#e7ebf3" if dark else "#17202e"
    st.markdown(f"""
<style>
/* page rhythm */
.block-container {{ padding-top: 2.2rem; max-width: 1240px; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* title row */
.app-title {{ display: flex; align-items: baseline; column-gap: 1rem; row-gap: .15rem; flex-wrap: wrap;
  margin: 0 0 .95rem 0; }}
.app-title .app-name {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 700;
  font-size: 2rem; letter-spacing: -.01em; line-height: 1.1; color: {ink}; }}
.app-title .app-sub {{ color: {muted}; font-size: .98rem; }}

/* tabs: heavier, more spacious */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.4rem; border-bottom: 1px solid {border}; }}
.stTabs [data-baseweb="tab"] {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif;
  font-weight: 600; font-size: 1.05rem; padding: .55rem 0; }}
.stTabs [data-baseweb="tab"] p {{ font-size: 1.05rem; }}

/* bordered containers read as raised cards, not outlines */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{ }}
div[data-testid="stVerticalBlockBorderWrapper"][style*="border"] {{ background: {surface}; }}

/* captions are secondary, not a second body font size */
[data-testid="stCaptionContainer"] {{ color: {muted}; line-height: 1.45; }}

/* metrics */
[data-testid="stMetricLabel"] p {{ color: {muted}; font-size: .9rem; }}
[data-testid="stMetricValue"] {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; }}

/* expanders: quieter headers */
[data-testid="stExpander"] details summary p {{ font-weight: 500; }}

/* sidebar */
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ font-size: 1.05rem; margin-top: .4rem; }}

/* ---- team preview stage ---- */
.tp-stage {{ background: linear-gradient(180deg, {STAGE['bg2']} 0%, {STAGE['bg']} 100%);
  border-radius: .9rem; padding: 1rem 1.1rem 1.15rem; margin: .2rem 0 1rem 0; color: {STAGE['ink']}; }}
.tp-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1rem;
  margin-bottom: .75rem; flex-wrap: wrap; }}
.tp-head .tp-title {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 600;
  font-size: 1.1rem; color: {STAGE['ink']}; }}
.tp-status {{ font-size: .92rem; color: {STAGE['muted']}; }}
.tp-status b {{ font-weight: 600; }}
.tp-dot {{ display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin-right: .4rem;
  vertical-align: .05rem; }}
.tp-slots {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: .7rem; }}
@media (max-width: 980px) {{ .tp-slots {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (max-width: 640px) {{
  .tp-stage {{ padding: .8rem .7rem .85rem; }}
  .tp-slots {{ grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .45rem; }}
  .tp-slot {{ padding: .35rem .4rem .5rem; }}
  .tp-platform {{ height: 50px; }}
  .tp-platform img {{ width: 48px; height: 48px; }}
  .tp-name {{ font-size: .92rem; }}
  .tp-item {{ font-size: .74rem; margin-bottom: .2rem; }}
  .tp-role {{ display: none; }}
  .tp-empty {{ min-height: 96px; }}
  .tp-head .tp-status {{ font-size: .85rem; }}
  .app-title .app-name {{ font-size: 1.6rem; }}
}}
.tp-slot {{ background: rgba(255,255,255,.035); border: 1px solid {STAGE['line']}; border-radius: .7rem;
  padding: .55rem .6rem .7rem; min-width: 0; }}
.tp-platform {{ height: 74px; display: flex; align-items: flex-end; justify-content: center;
  background: radial-gradient(ellipse 46% 16% at 50% 88%, rgba(143,166,255,.28), transparent 70%); }}
.tp-platform img {{ width: 68px; height: 68px; image-rendering: pixelated; }}
.tp-name {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 600; font-size: 1.02rem;
  margin-top: .2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: {STAGE['ink']}; }}
.tp-item {{ font-size: .82rem; color: {STAGE['muted']}; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; margin-bottom: .3rem; }}
.tp-mega {{ color: {STAGE['accent']}; font-weight: 600; }}
.tp-role {{ font-size: .78rem; color: {STAGE['muted']}; margin-top: .35rem; line-height: 1.3; }}
.tp-empty {{ border-style: dashed; background: transparent; display: flex; flex-direction: column;
  justify-content: center; align-items: center; min-height: 150px; color: {STAGE['muted']}; }}
.tp-empty .tp-plus {{ font-size: 1.7rem; line-height: 1; opacity: .7; }}
.tp-empty .tp-open {{ font-size: .85rem; margin-top: .35rem; }}
</style>
""", unsafe_allow_html=True)


def title_row(subtitle: str) -> None:
    st.markdown(f"<div class='app-title'><div class='app-name'>Champions Team Builder</div>"
                f"<div class='app-sub'>{html.escape(subtitle)}</div></div>", unsafe_allow_html=True)


def team_stage(team: list[PokemonSet], dex: Dex, status_html: str) -> None:
    """The team as a team-preview lineup: six slots, empty ones dashed."""
    doubles = st.session_state.get("doubles", True)
    slots = []
    for pset in team:
        form = pset.battle_form(dex)
        if form.is_mega:
            held = f"{html.escape(pset.item)} <span class='tp-mega'>Mega</span>"
        else:
            held = html.escape(pset.item) if pset.item else "No item"
        slots.append(
            "<div class='tp-slot'>"
            f"<div class='tp-platform'><img src='{sprite(form, dex)}' alt=''></div>"
            f"<div class='tp-name'>{html.escape(pset.nickname or pset.species)}</div>"
            f"<div class='tp-item'>{held}</div>"
            f"<div>{type_badges(form.types)}</div>"
            f"<div class='tp-role'>{role_text(set_roles(pset, dex, doubles), 2)}</div>"
            "</div>"
        )
    for _ in range(SLOTS - len(team)):
        slots.append("<div class='tp-slot tp-empty'><div class='tp-plus'>+</div>"
                     "<div class='tp-open'>Open slot</div></div>")
    st.markdown(
        "<div class='tp-stage'><div class='tp-head'><span class='tp-title'>Your team</span>"
        f"<span class='tp-status'>{status_html}</span></div>"
        f"<div class='tp-slots'>{''.join(slots)}</div></div>",
        unsafe_allow_html=True,
    )


def status_html(errors: int, warnings: int, size: int, fmt_label: str) -> str:
    if size == 0:
        return "Pick Pokémon on the Team tab, or try the example team in the sidebar"
    if errors:
        return (f"<span class='tp-dot' style='background:{STAGE['bad']}'></span>"
                f"<b>{errors} rule problem{'s' if errors > 1 else ''}</b> (details below)")
    if size < SLOTS:
        return (f"<span class='tp-dot' style='background:{STAGE['muted']}'></span>"
                f"{size} of 6 so far, no rule problems")
    note = f", {warnings} note{'s' if warnings > 1 else ''}" if warnings else ""
    return f"<span class='tp-dot' style='background:{STAGE['ok']}'></span><b>Legal</b> for {html.escape(fmt_label)}{note}"


def how_it_works(text: str, label: str = "How this works") -> None:
    """Methodology goes behind a toggle so sections open with results, not paragraphs."""
    with st.expander(label):
        st.markdown(text)
