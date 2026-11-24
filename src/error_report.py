"""
error_report.py - a tab that breaks for a visitor opens (or adds to) a GitHub issue, so the owner hears
about it without waiting for someone to fill in the feedback form.

Off unless the app's secrets hold a GitHub token (Community Cloud: Manage app > Settings > Secrets):

    github_token = "github_pat_..."   # fine-grained, this repository only, Issues: read and write

One issue per distinct error (same tab, exception type, and the line in this repo's code it came from),
labelled app-error. A repeat adds a comment, at most once an hour per error from each running app, so a
busy bug can't flood the repo. Reports go out on a background thread: the visitor never waits for GitHub,
and a failed report is only logged.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "mam084/pokemon-team-builder"
LABEL = "app-error"
REPEAT_EVERY = 3600.0
ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("pokemon-team-builder")
_sent: dict[str, float] = {}
_lock = threading.Lock()


def signature(tab: str, exc: BaseException) -> str:
    """'Matchups: KeyError at src/swaps.py:412': the deepest frame in this repo's own code."""
    where = ""
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename)
        if ROOT in path.parents and "site-packages" not in path.parts:
            where = f" at {path.relative_to(ROOT).as_posix()}:{frame.lineno}"
    return f"{tab}: {type(exc).__name__}{where}"


def _body(sig: str, exc: BaseException, link: str) -> str:
    tb = "".join(traceback.format_exception(exc)).replace(str(ROOT) + "/", "")
    return (f"**{sig}**\n\nA visitor's page hit this on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}.\n\n"
            f"Team (open to reproduce): {link or 'none'}\n\n```\n{tb[-6000:]}\n```")


def _api(token: str, method: str, path: str, data: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "pokemon-team-builder"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read() or b"{}")


def _send(token: str, sig: str, body: str) -> None:
    try:
        title = f"[app error] {sig}"
        q = urllib.parse.quote(f'repo:{REPO} is:issue is:open label:{LABEL} in:title "{sig}"')
        found = [i for i in _api(token, "GET", f"/search/issues?q={q}").get("items", []) if i["title"] == title]
        if found:
            _api(token, "POST", f"/repos/{REPO}/issues/{found[0]['number']}/comments", {"body": "Again:\n\n" + body})
        else:
            _api(token, "POST", f"/repos/{REPO}/issues", {"title": title, "body": body, "labels": [LABEL]})
    except Exception as e:   # reporting must never break anything
        log.warning("couldn't report the error to GitHub: %s", e)


def report(tab: str, exc: BaseException, link: str, token: str | None) -> bool:
    """Log the error and, with a token, report it to GitHub in the background. True if a report went out."""
    sig = signature(tab, exc)
    log.error("%s (team %s)\n%s", sig, link, "".join(traceback.format_exception(exc)))
    if not token:
        return False
    now = time.monotonic()
    with _lock:
        if now - _sent.get(sig, -REPEAT_EVERY) < REPEAT_EVERY:
            return False
        _sent[sig] = now
    threading.Thread(target=_send, args=(token, sig, _body(sig, exc, link)), daemon=True).start()
    return True


__all__ = ["report", "signature"]
