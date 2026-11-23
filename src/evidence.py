"""
evidence.py - what the held-out numbers actually support, in one place.

The app, the README and the weekly health check all describe whether the team adds anything to the win
model beyond the players' ratings. That answer changes as new tournaments arrive, so it is worked out from
the newest 95% interval every time instead of being written into the text.
"""

from __future__ import annotations

ADDS, UNCLEAR, HURTS = "adds", "unclear", "hurts"


def team_signal(learned: dict | None) -> str | None:
    """ADDS when the log-loss gain of team features over ratings alone is above zero across the whole 95%
    interval, HURTS when it's below zero across it, UNCLEAR when the interval spans zero."""
    if not learned:
        return None
    ci = learned.get("gain_ci95", {}).get("team beyond skill")
    if not ci:
        return None
    lo, hi = ci
    if lo > 0:
        return ADDS
    if hi < 0:
        return HURTS
    return UNCLEAR


def team_signal_sentence(learned: dict | None) -> str:
    """One plain sentence for the app and README."""
    verdict = team_signal(learned)
    if verdict is None:
        return ""
    lo, hi = learned["gain_ci95"]["team beyond skill"]
    ci = f"log-loss gain {lo:+.4f} to {hi:+.4f} over ratings alone, 95% paired bootstrap"
    if verdict == ADDS:
        return f"The team adds a small but real signal on top of the players' ratings ({ci})."
    if verdict == HURTS:
        return f"On the newest matches the team made predictions worse than ratings alone ({ci})."
    return (f"On the newest matches, the team's extra signal on top of the players' ratings is too small to "
            f"tell apart from zero ({ci}). Treat team-vs-team win chances as a rough guide.")


__all__ = ["team_signal", "team_signal_sentence", "ADDS", "UNCLEAR", "HURTS"]
