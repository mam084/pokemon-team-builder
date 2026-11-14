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

/* team tab: moves and stat points boxes */
.box-title {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 600; font-size: 1.1rem;
  color: {ink}; margin-bottom: .1rem; }}
.box-title .box-sub {{ font-family: Barlow, sans-serif; font-weight: 400; font-size: .92rem; color: {muted};
  margin-left: .4rem; }}
.stat-name {{ font-weight: 600; color: {ink}; }}
.stat-final {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 700; font-size: 1.35rem;
  text-align: right; color: {ink}; }}
.nat-up {{ color: #2f9e6a; font-size: .8em; }}
.nat-down {{ color: #d0505a; font-size: .8em; }}
[class*="st-key-stats_box"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap; gap: .6rem; }}
[class*="st-key-stats_box"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{ min-width: 0 !important; }}
[class*="st-key-stats_box"] [data-testid="stVerticalBlock"] {{ gap: .45rem; }}
[class*="st-key-stats_box"] [data-testid="stColumn"] [data-testid="stMarkdownContainer"] {{ margin: 0; }}
[class*="st-key-stats_box"] .stat-name, [class*="st-key-stats_box"] .stat-final {{ line-height: 2.5rem; }}
[class*="st-key-moves_box"] [data-testid="stVerticalBlock"] {{ gap: .6rem; }}

/* ---- team preview stage ---- */
.st-key-tp_stage {{ background: linear-gradient(180deg, {STAGE['bg2']} 0%, {STAGE['bg']} 100%);
  border-radius: .9rem; padding: 1rem 1.1rem 1.15rem; margin: .2rem 0 .6rem 0; gap: .7rem; }}
.tp-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap;
  margin-bottom: .35rem; }}
.tp-head .tp-title {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 600;
  font-size: 1.1rem; color: {STAGE['ink']}; }}
.tp-status {{ font-size: .92rem; color: {STAGE['muted']}; }}
.tp-status b {{ font-weight: 600; color: {STAGE['ink']}; }}
.tp-dot {{ display: inline-block; width: .55rem; height: .55rem; border-radius: 50%; margin-right: .4rem;
  vertical-align: .05rem; }}
/* six cards in a row; three per row on tablets and phones (never one long column) */
.st-key-tp_stage [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: .7rem; }}
.st-key-tp_stage [data-testid="stColumn"] {{ flex: 1 1 0 !important; min-width: 0 !important; width: auto !important; }}
@media (max-width: 980px) {{
  .st-key-tp_stage [data-testid="stColumn"] {{ flex: 0 0 calc((100% - 1.4rem) / 3) !important; }}
}}
/* cards: a clear border, like a slot on the preview screen */
.st-key-tp_stage [data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
.st-key-tp_stage [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height: 100%; }}
.st-key-tp_stage [data-testid="stColumn"] [data-testid="stLayoutWrapper"] {{ flex: 1 1 auto; }}
[class*="st-key-tp_slot"] {{ position: relative; flex: 1 1 auto; height: auto !important; gap: 0; border-radius: .7rem;
  padding: .55rem .6rem .7rem; min-width: 0; }}
[class*="st-key-tp_slot"]:not([class*="empty"]) {{ background: rgba(255,255,255,.05);
  border: 1.5px solid #4a5a86; }}
[class*="st-key-tp_slot_empty"] {{ border: 1.5px dashed {STAGE['line']}; justify-content: center; }}
[class*="st-key-tp_rm"] {{ position: absolute; top: .35rem; right: .35rem; width: auto !important; z-index: 2; }}
[class*="st-key-tp_rm"] button {{ min-height: 0; height: 1.6rem; width: 1.6rem; padding: 0; border-radius: 50%;
  border: none; background: rgba(255,255,255,.08); color: {STAGE['muted']}; }}
[class*="st-key-tp_rm"] button:hover {{ background: rgba(255,122,122,.22); color: #fff; }}
[class*="st-key-tp_rm"] button:focus-visible {{ outline: 2px solid {STAGE['accent']}; outline-offset: 1px; }}
[class*="st-key-tp_rm"] [data-testid="stIconMaterial"] {{ font-size: 1rem; }}
.tp-platform {{ height: 74px; display: flex; align-items: flex-end; justify-content: center;
  background: radial-gradient(ellipse 46% 16% at 50% 88%, rgba(143,166,255,.28), transparent 70%); }}
.tp-platform img {{ width: 68px; height: 68px; image-rendering: pixelated; }}
.tp-name {{ font-family: "Barlow Semi Condensed", Barlow, sans-serif; font-weight: 600; font-size: 1.02rem;
  margin-top: .2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: {STAGE['ink']}; }}
.tp-item {{ font-size: .82rem; color: {STAGE['muted']}; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; margin-bottom: .3rem; }}
.tp-mega {{ color: {STAGE['accent']}; font-weight: 600; }}
.tp-role {{ font-size: .78rem; color: {STAGE['muted']}; margin-top: .35rem; line-height: 1.3; }}
[class*="st-key-tp_slot"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
[class*="st-key-tp_slot"] [data-testid="stMarkdownContainer"] p {{ margin: 0; }}
.tp-empty {{ display: flex; flex-direction: column; justify-content: center; align-items: center;
  min-height: 150px; color: {STAGE['muted']}; }}
.tp-empty .tp-plus {{ font-size: 1.7rem; line-height: 1; opacity: .7; }}
.tp-empty .tp-open {{ font-size: .85rem; margin-top: .35rem; }}
@media (max-width: 640px) {{
  .st-key-tp_stage {{ padding: .8rem .7rem .85rem; }}
  .st-key-tp_stage [data-testid="stHorizontalBlock"] {{ gap: .45rem; }}
  .st-key-tp_stage [data-testid="stColumn"] {{ flex: 0 0 calc((100% - .9rem) / 3) !important; }}
  [class*="st-key-tp_slot"] {{ padding: .35rem .4rem .5rem; }}
  .tp-platform {{ height: 50px; }}
  .tp-platform img {{ width: 48px; height: 48px; }}
  .tp-name {{ font-size: .92rem; }}
  .tp-item {{ font-size: .74rem; margin-bottom: .2rem; }}
  .tp-role {{ display: none; }}
  .tp-empty {{ min-height: 96px; }}
  .tp-head .tp-status {{ font-size: .85rem; }}
  .app-title .app-name {{ font-size: 1.6rem; }}
}}
</style>
""", unsafe_allow_html=True)


def title_row(subtitle: str) -> None:
    st.markdown(f"<div class='app-title'><div class='app-name'>Champions Team Builder</div>"
                f"<div class='app-sub'>{html.escape(subtitle)}</div></div>", unsafe_allow_html=True)


def team_stage(dex: Dex, status_html: str) -> None:
    """The team as a team-preview lineup, in slot order: each card has a remove button,
    empty slots are dashed. Built from Streamlit containers (styled by key) so the
    remove buttons run callbacks like any other button."""
    from ui.state import read_slot, write_slot
    doubles = st.session_state.get("doubles", True)
    with st.container(key="tp_stage"):
        st.markdown("<div class='tp-head'><span class='tp-title'>Your team</span>"
                    f"<span class='tp-status'>{status_html}</span></div>", unsafe_allow_html=True)
        cols = st.columns(SLOTS, gap="small")
        for i, col in enumerate(cols):
            pset = read_slot(i)
            with col:
                if pset is None:
                    with st.container(key=f"tp_slot_empty{i}"):
                        st.markdown(f"<div class='tp-empty'><div class='tp-plus'>+</div>"
                                    f"<div class='tp-open'>Slot {i + 1}</div></div>", unsafe_allow_html=True)
                    continue
                form = pset.battle_form(dex)
                if form.is_mega:
                    held = f"{html.escape(pset.item)} <span class='tp-mega'>Mega</span>"
                else:
                    held = html.escape(pset.item) if pset.item else "No item"
                with st.container(key=f"tp_slot{i}"):
                    st.button(":material/close:", key=f"tp_rm{i}", on_click=write_slot, args=(i, None),
                              help=f"Remove {pset.species}")
                    st.markdown(
                        f"<div class='tp-platform'><img src='{sprite(form, dex)}' alt=''></div>"
                        f"<div class='tp-name'>{html.escape(pset.nickname or pset.species)}</div>"
                        f"<div class='tp-item'>{held}</div>"
                        f"<div class='tp-types'>{type_badges(form.types)}</div>"
                        f"<div class='tp-role'>{role_text(set_roles(pset, dex, doubles), 2)}</div>",
                        unsafe_allow_html=True)


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
