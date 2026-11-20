"""
compare.py - two versions of your team, side by side (Matchups tab).

Save a version, change the team (edit it, or apply a swap: that saves the version before it if nothing is
saved yet), and the Matchups tab shows what changed: overall win chance, each meta team, and which threats
gained or lost an answer. Both versions go through the same cached tables as the Matchups tab itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ui.state import load_team, write_slot

SAVED = "saved_version"   # {"key": team_key, "label": str}
TOP_THREATS = 10


def save_version(key: str, label: str) -> None:
    st.session_state[SAVED] = {"key": key, "label": label}


def clear_version() -> None:
    st.session_state.pop(SAVED, None)


def restore_version() -> None:
    from ui.matchups_tab import _unkey
    saved = st.session_state.get(SAVED)
    if saved:
        load_team(_unkey(saved["key"]))


def apply_swap(slot: int, pset, before_key: str, out_name: str) -> None:
    """Apply swap: keep the team as it was (unless a version is already saved), then swap."""
    if SAVED not in st.session_state:
        save_version(before_key, f"before swapping out {out_name}")
    write_slot(slot, pset)
    st.toast(f"Swapped {out_name} → {pset.species}. Compare versions (above) shows what changed.")


def team_diff(old, new) -> str:
    """'Out: A, B · In: C, D', plus members whose set changed."""
    def name(p):
        return p.nickname or p.species
    olds, news = {p.species: p for p in old}, {p.species: p for p in new}
    out = [name(p) for s, p in olds.items() if s not in news]
    inn = [name(p) for s, p in news.items() if s not in olds]
    changed = [name(p) for s, p in news.items() if s in olds and p.to_dict() != olds[s].to_dict()]
    bits = ([f"Out: {', '.join(out)}"] if out else []) + ([f"In: {', '.join(inn)}"] if inn else []) + \
           ([f"New set: {', '.join(changed)}"] if changed else [])
    return " · ".join(bits) or "Same Pokémon, same sets"


def _versus(fmt_id: str, key: str):
    """(per-meta-team values, usage-weighted average, is_chance) for one version."""
    from ui.matchups_tab import cached_meta_matchups, learned_chances, learned_meta_sides
    from src.match_model import cap_chance
    table = cached_meta_matchups(fmt_id, key)
    weights = table["popularity"].to_numpy()
    chances = learned_chances(fmt_id, key)
    if chances:
        model = learned_meta_sides(fmt_id)[0]
        return table, np.array(chances), cap_chance(model, float(np.average(chances, weights=weights))), True
    scores = table["score"].to_numpy()
    return table, scores, float(np.average(scores, weights=weights)), False


def threat_changes(old: pd.DataFrame, new: pd.DataFrame) -> tuple[list[str], list[str]]:
    """(now answered, no longer answered) among the top threats of either version."""
    if old.empty or new.empty:
        return [], []
    o = old.set_index("pokemon")["answers"]
    n = new.set_index("pokemon")["answers"]
    names = list(dict.fromkeys(list(new["pokemon"].head(TOP_THREATS)) + list(old["pokemon"].head(TOP_THREATS))))
    gained = [p for p in names if p in o and p in n and o[p] == "none" and n[p] != "none"]
    lost = [p for p in names if p in o and p in n and o[p] != "none" and n[p] == "none"]
    return gained, lost


def compare_section(fmt_id: str, team, fmt) -> None:
    from ui.common import section
    from ui.matchups_tab import FAVORED, _unkey, cached_threats, team_key
    section("Compare versions")
    key = team_key(team)
    saved = st.session_state.get(SAVED)
    if not saved:
        st.caption("Save this version, then change the team (or apply a swap below, which saves the version "
                   "before it for you) to see what got better and what got worse.")
        st.button("Save this version", key="save_version", on_click=save_version, args=(key, "saved version"))
        return
    old_team = _unkey(saved["key"])
    if saved["key"] == key:
        st.caption(f"Your team is the same as the saved version ({saved['label']}). Change it on the Team tab, "
                   "or apply a swap below, and the comparison shows up here.")
        st.button("Clear saved version", key="clear_version", on_click=clear_version)
        return

    old_table, old_vals, old_avg, is_chance = _versus(fmt_id, saved["key"])
    new_table, new_vals, new_avg, _ = _versus(fmt_id, key)
    st.markdown(f"**Now vs {saved['label']}** · {team_diff(old_team, team)}")
    c = st.container(key="metric_row_compare").columns(3)
    if is_chance:
        c[0].metric("Win chance", f"{new_avg:.0%}", f"{(new_avg - old_avg) * 100:+.0f} pts",
                    help=f"Was {old_avg:.0%}. Usage-weighted average against the meta teams.")
        fav_new, fav_old = int((new_vals >= FAVORED).sum()), int((old_vals >= FAVORED).sum())
        bad_new, bad_old = int((new_vals <= 1 - FAVORED).sum()), int((old_vals <= 1 - FAVORED).sum())
    else:
        c[0].metric("Overall", f"{new_avg:+.2f}", f"{new_avg - old_avg:+.2f}", help=f"Was {old_avg:+.2f}")
        fav_new, fav_old = int((new_vals >= 0.25).sum()), int((old_vals >= 0.25).sum())
        bad_new, bad_old = int((new_vals <= -0.25).sum()), int((old_vals <= -0.25).sum())
    c[1].metric("Favorable", fav_new, f"{fav_new - fav_old:+d}" if fav_new != fav_old else None)
    c[2].metric("Unfavorable", bad_new, f"{bad_new - bad_old:+d}" if bad_new != bad_old else None,
                delta_color="inverse")

    # each meta team, biggest moves first (the meta teams are the same list for both versions)
    scale = 100 if is_chance else 1
    rows = pd.DataFrame({"meta team": new_table["archetype"],
                         "was": old_vals * scale, "now": new_vals * scale})
    rows["change"] = rows["now"] - rows["was"]
    rows = rows.reindex(rows["change"].abs().sort_values(ascending=False).index)
    up = rows[rows["change"] >= (2 if is_chance else 0.05)]
    down = rows[rows["change"] <= -(2 if is_chance else 0.05)]
    unit = " pts" if is_chance else ""
    fmt_row = (lambda r: f"{r['meta team']}: {r['change']:+.0f}{unit}") if is_chance else \
        (lambda r: f"{r['meta team']}: {r['change']:+.2f}")
    lines = []
    if len(up):
        lines.append("**Better against:** " + "; ".join(fmt_row(r) for _, r in up.head(3).iterrows()))
    if len(down):
        lines.append("**Worse against:** " + "; ".join(fmt_row(r) for _, r in down.head(3).iterrows()))
    gained, lost = threat_changes(cached_threats(fmt_id, saved["key"]), cached_threats(fmt_id, key))
    if gained:
        lines.append("**Now answered:** " + ", ".join(gained))
    if lost:
        lines.append("**No longer answered:** " + ", ".join(lost))
    st.markdown("  \n".join(lines) if lines else "About the same against every meta team, and the same "
                                                  "threats are answered.")
    with st.expander("Every meta team, both versions"):
        cfg = {"was": st.column_config.NumberColumn(format="%.0f%%" if is_chance else "%+.2f"),
               "now": st.column_config.NumberColumn(format="%.0f%%" if is_chance else "%+.2f"),
               "change": st.column_config.NumberColumn(format="%+.0f" if is_chance else "%+.2f"),
               "meta team": st.column_config.TextColumn(pinned=True)}
        st.dataframe(rows, hide_index=True, width="stretch", column_config=cfg)
    b = st.container(key="button_row_compare").columns(3)   # one row on phones too (theme.py)
    b[0].button("Go back", key="restore_version", on_click=restore_version, width="stretch",
                help=f"Put the team back to the saved version ({saved['label']}).")
    b[1].button("Keep this", key="resave_version", on_click=save_version, args=(key, "saved version"),
                width="stretch", help="Save the team as it is now, and compare the next change to it.")
    b[2].button("Clear", key="clear_version", on_click=clear_version, width="stretch",
                help="Forget the saved version.")


__all__ = ["compare_section", "apply_swap", "save_version", "restore_version", "clear_version",
           "team_diff", "threat_changes", "SAVED"]
