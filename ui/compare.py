"""
compare.py - two versions of your team, side by side (Matchups tab).

Save a version, change the team (edit it, or apply a swap: that saves the version before it if nothing is
saved yet), and the Matchups tab shows what changed: overall win chance, each meta team, and which threats
gained or lost an answer. Both versions go through the same cached tables as the Matchups tab itself.

Several changes in a row: each time the Matchups tab shows a new version of the team, it's recorded as a
step (a burst of edits on the Team tab between visits is one step). The section then also shows what the
last change did on its own, lists every step with its win chance, and can undo one step or go back to any.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ui.state import load_team, write_slot

SAVED = "saved_version"   # {"key": team_key, "label": str}
STEPS = "version_steps"   # team keys since the save, oldest first; [0] is always the saved version
TOP_THREATS = 10
MAX_STEPS = 10            # saved version + the 9 latest changes


def save_version(key: str, label: str) -> None:
    st.session_state[SAVED] = {"key": key, "label": label}
    st.session_state[STEPS] = [key]


def clear_version() -> None:
    st.session_state.pop(SAVED, None)
    st.session_state.pop(STEPS, None)


def _steps() -> list[str]:
    """The recorded steps, starting from the saved version (which may have come in from a link)."""
    ss = st.session_state
    saved = ss.get(SAVED)
    if not saved:
        return []
    steps = ss.get(STEPS)
    if not steps or steps[0] != saved["key"]:
        steps = ss[STEPS] = [saved["key"]]
    return steps


def record_step(key: str) -> list[str]:
    """Note the team as it is now. Back to an earlier step (by hand or with Undo) cuts the later ones."""
    steps = _steps()
    if not steps:
        return steps
    if key in steps:
        del steps[steps.index(key) + 1:]
    else:
        steps.append(key)
        if len(steps) > MAX_STEPS:
            del steps[1]            # keep the saved version; drop the oldest change
    return steps


def go_to_step(i: int) -> None:
    from ui.matchups_tab import _unkey
    steps = _steps()
    if 0 <= i < len(steps):
        load_team(_unkey(steps[i]))
        del steps[i + 1:]


def undo_step() -> None:
    go_to_step(len(_steps()) - 2)


def restore_version() -> None:
    go_to_step(0)


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


def _pts(change: float, is_chance: bool) -> str:
    """'+3 pts' / '-0.12'; a change that rounds to nothing reads 'no change', not '-0 pts'."""
    if is_chance:
        n = round(change * 100)
        return (f"{n:+d} pt" + ("s" if abs(n) != 1 else "")) if n else "no change"
    return f"{change:+.2f}" if abs(change) >= 0.005 else "no change"


def _last_change(fmt_id: str, steps: list[str], team, is_chance: bool) -> str:
    """'**Last change** (Out: Gallade · In: Venusaur): win chance -1 pts; worse against Tailwind -3 pts'."""
    from ui.matchups_tab import _unkey
    prev_table, prev_vals, prev_avg, _ = _versus(fmt_id, steps[-2])
    _, now_vals, now_avg, _ = _versus(fmt_id, steps[-1])
    what = "win chance" if is_chance else "overall"
    bits = [f"{what} {_pts(now_avg - prev_avg, is_chance)}"]
    moves = now_vals - prev_vals
    i = int(np.argmax(np.abs(moves)))
    if abs(moves[i]) >= (0.02 if is_chance else 0.05):
        word = "biggest gain" if moves[i] > 0 else "biggest drop"
        bits.append(f"{word}: {prev_table['archetype'].iloc[i]} ({_pts(moves[i], is_chance)})")
    return f"**Last change** ({team_diff(_unkey(steps[-2]), team)}): " + "; ".join(bits)


def _history(fmt_id: str, steps: list[str], label: str, is_chance: bool) -> pd.DataFrame:
    from ui.matchups_tab import _unkey
    rows = []
    for i, key in enumerate(steps):
        avg = _versus(fmt_id, key)[2]
        change = label if i == 0 else team_diff(_unkey(steps[i - 1]), _unkey(key))
        rows.append({"step": "Saved" if i == 0 else f"Change {i}", "what changed": change,
                     "win chance" if is_chance else "overall": avg * 100 if is_chance else avg})
    return pd.DataFrame(rows)


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
    steps = record_step(key)
    if saved["key"] == key:
        st.caption(f"Your team is the same as the saved version ({saved['label']}). Change it on the Team tab, "
                   "or apply a swap below, and the comparison shows up here.")
        st.button("Clear saved version", key="clear_version", on_click=clear_version)
        return

    old_table, old_vals, old_avg, is_chance = _versus(fmt_id, saved["key"])
    new_table, new_vals, new_avg, _ = _versus(fmt_id, key)
    n = len(steps) - 1
    st.markdown(f"**Now vs {saved['label']}**" + (f" ({n} changes)" if n > 1 else "")
                + f" · {team_diff(old_team, team)}")
    c = st.container(key="metric_row_compare").columns(3)
    if is_chance:
        d = _pts(new_avg - old_avg, True)
        c[0].metric("Win chance", f"{new_avg:.0%}", None if d == "no change" else d,
                    help=f"Was {old_avg:.0%}. Usage-weighted average against the meta teams.")
        fav_new, fav_old = int((new_vals >= FAVORED).sum()), int((old_vals >= FAVORED).sum())
        bad_new, bad_old = int((new_vals <= 1 - FAVORED).sum()), int((old_vals <= 1 - FAVORED).sum())
    else:
        d = _pts(new_avg - old_avg, False)
        c[0].metric("Overall", f"{new_avg:+.2f}", None if d == "no change" else d, help=f"Was {old_avg:+.2f}")
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
    if n > 1:   # several changes: what the latest one did by itself, and every step so far
        st.markdown(_last_change(fmt_id, steps, team, is_chance))
        with st.expander(f"Your {n} changes, step by step"):
            hist = _history(fmt_id, steps, saved["label"], is_chance)
            score_col = "win chance" if is_chance else "overall"
            st.dataframe(hist, hide_index=True, width="stretch", column_config={
                "step": st.column_config.TextColumn(pinned=True),
                score_col: st.column_config.NumberColumn(format="%.0f%%" if is_chance else "%+.2f")})
            back = st.selectbox("Go back to", range(n), key="step_pick",
                                format_func=lambda i: hist["step"].iloc[i] + (
                                    f" ({hist[score_col].iloc[i]:.0f}%)" if is_chance else ""))
            st.button("Go back to this step", key="go_step", on_click=go_to_step, args=(back,),
                      help="Puts the team back as it was at that step. Later steps are dropped.")
    with st.expander("Every meta team, both versions"):
        cfg = {"was": st.column_config.NumberColumn(format="%.0f%%" if is_chance else "%+.2f"),
               "now": st.column_config.NumberColumn(format="%.0f%%" if is_chance else "%+.2f"),
               "change": st.column_config.NumberColumn(format="%+.0f" if is_chance else "%+.2f"),
               "meta team": st.column_config.TextColumn(pinned=True)}
        st.dataframe(rows, hide_index=True, width="stretch", column_config=cfg)
    b = st.container(key="button_row_compare").columns(4 if n > 1 else 3)   # one row on phones too (theme.py)
    if n > 1:
        b[0].button("Undo last", key="undo_step", on_click=undo_step, width="stretch",
                    help="Undo only the most recent change.")
    b[-3].button("Undo all", key="restore_version", on_click=restore_version, width="stretch",
                 help=f"Undo every change: back to the saved version ({saved['label']}).")
    b[-2].button("Keep this", key="resave_version", on_click=save_version, args=(key, "saved version"),
                 width="stretch", help="Save the team as it is now, and compare the next change to it.")
    b[-1].button("Clear", key="clear_version", on_click=clear_version, width="stretch",
                 help="Forget the saved version.")


__all__ = ["compare_section", "apply_swap", "save_version", "restore_version", "clear_version",
           "record_step", "go_to_step", "undo_step", "team_diff", "threat_changes", "SAVED", "STEPS"]
