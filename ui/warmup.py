"""Warm the swap search once per server, in the background, so the first Matchups visit after a reboot
isn't the slow one. Runs the search for the example team (src/swaps.SwapEngine caches each candidate's
calcs against the meta teams, and any team reuses most of them). Same code, same results, earlier."""

from __future__ import annotations

import os
import threading

import streamlit as st

WARM = os.environ.get("PTB_WARMUP", "1") != "0"   # PTB_WARMUP=0 turns it off (timing tests)


@st.cache_resource(show_spinner=False)
def start(fmt_id: str) -> threading.Thread | None:
    """Start the warm-up for this format once per server process."""
    if not WARM:
        return None
    from src.dex import load_dex
    from src.formats import FORMATS
    from src.paste import parse_paste
    from src.swaps import suggest_swaps
    from src.usage import load_usage
    from src.swaps import mode_pool
    from ui.matchups_tab import swap_engine_for
    from ui.sidebar import SAMPLE_TEAM
    fmt = FORMATS[fmt_id]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt_id)
    if usage is None:
        return None
    engine = swap_engine_for(fmt_id)   # built here, on the script thread; the thread only does arithmetic
    team = parse_paste(SAMPLE_TEAM, dex)[0]
    pool = mode_pool(usage, "neutral", dex)   # the default swap style

    def work() -> None:
        try:
            suggest_swaps(team, dex, usage, engine, pool=pool, top_n=8)
        except Exception:   # a warm-up must never take the app down
            pass

    thread = threading.Thread(target=work, name=f"warmup-{fmt_id}", daemon=True)
    thread.start()
    return thread


__all__ = ["start"]
