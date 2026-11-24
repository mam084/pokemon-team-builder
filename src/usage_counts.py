"""
usage_counts.py - how many visits, which tabs get opened and which features get used, so the owner can
see what players actually use. Counts only: nothing about who visited, no team, no IP.

Off unless the app's secrets hold the same GitHub token as the error reports (src/error_report.py).
Counts collect in memory and go out at most once an hour, on a background thread, into one issue in the
repo ("App usage", label app-usage): a table of the last 30 days, with the full numbers as JSON at the
bottom of the issue so later updates add to them. If an update fails, the counts are kept for the next.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter

from src.error_report import REPO, _api

TITLE = "App usage"
LABEL = "app-usage"
FLUSH_EVERY = 3600.0
DAYS_SHOWN = 30
COLUMNS = ["visits", "tab: Analysis", "tab: Matchups", "tab: Battle plan", "tab: Playbook", "tab: Damage calc",
           "tab: Recommendations", "tab: Pokémon", "example team", "pasted a team", "team from a link",
           "find swaps", "battle plan vs a team"]

log = logging.getLogger("pokemon-team-builder")
_pending: Counter = Counter()
_lock = threading.Lock()
_last_flush = time.monotonic()
_issue_number: int | None = None


def count(event: str) -> None:
    """Add one to today's count of event (UTC day)."""
    with _lock:
        _pending[(time.strftime("%Y-%m-%d", time.gmtime()), event)] += 1


def _parse(body: str) -> dict[str, dict[str, int]]:
    m = re.search(r"```json\n(.*?)\n```", body or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return {d: {e: int(n) for e, n in ev.items()} for d, ev in data.items()}
    except (ValueError, AttributeError, TypeError):
        return {}


def render(data: dict[str, dict[str, int]]) -> str:
    """The issue body: a table of the last DAYS_SHOWN days, then every count as JSON."""
    days = sorted(data, reverse=True)[:DAYS_SHOWN]
    cols = COLUMNS + sorted({e for d in days for e in data[d]} - set(COLUMNS))
    head = "| day | " + " | ".join(c.replace("tab: ", "") for c in cols) + " |"
    sep = "|---" * (len(cols) + 1) + "|"
    rows = [f"| {d} | " + " | ".join(str(data[d].get(c, 0)) for c in cols) + " |" for d in days]
    return ("Updated by the app about once an hour (src/usage_counts.py). Counts only: nothing about who "
            "visited. Days are UTC; a visit is one browser session.\n\n" + "\n".join([head, sep] + rows)
            + "\n\n<details><summary>All counts (the app adds to these)</summary>\n\n```json\n"
            + json.dumps(data, sort_keys=True) + "\n```\n</details>\n")


def _find_issue(token: str) -> tuple[int | None, str]:
    global _issue_number
    if _issue_number is not None:
        issue = _api(token, "GET", f"/repos/{REPO}/issues/{_issue_number}")
        return _issue_number, issue.get("body") or ""
    q = f'repo:{REPO} is:issue is:open label:{LABEL} in:title "{TITLE}"'
    from urllib.parse import quote
    for item in _api(token, "GET", f"/search/issues?q={quote(q)}").get("items", []):
        if item["title"] == TITLE:
            _issue_number = item["number"]
            return _issue_number, item.get("body") or ""
    return None, ""


def _flush(token: str, batch: Counter) -> None:
    global _issue_number
    try:
        number, body = _find_issue(token)
        data = _parse(body)
        for (day, event), n in batch.items():
            data.setdefault(day, {})
            data[day][event] = data[day].get(event, 0) + n
        if number is None:
            made = _api(token, "POST", f"/repos/{REPO}/issues", {"title": TITLE, "body": render(data),
                                                                  "labels": [LABEL]})
            _issue_number = made.get("number")
        else:
            _api(token, "PATCH", f"/repos/{REPO}/issues/{number}", {"body": render(data)})
    except Exception as e:   # counting must never break anything: keep them for the next try
        log.warning("couldn't update the usage counts: %s", e)
        with _lock:
            _pending.update(batch)


def maybe_flush(token: str | None, force: bool = False) -> bool:
    """Send what's been counted if an hour has passed (or force). True if an update went out."""
    global _last_flush
    if not token:
        return False
    with _lock:
        now = time.monotonic()
        if not _pending or (not force and now - _last_flush < FLUSH_EVERY):
            return False
        _last_flush = now
        batch = Counter(_pending)
        _pending.clear()
    threading.Thread(target=_flush, args=(token, batch), daemon=True).start()
    return True


__all__ = ["count", "maybe_flush", "render"]
