"""
keep_awake.py - visit the live app so Streamlit Community Cloud doesn't put it to sleep.

Community Cloud hibernates an app after 12 hours without a visitor (pushes don't count), and the next
visitor then gets a "gone to sleep" page with a button to wake it. A real browser visit every few hours
keeps it up; if it's already asleep, this clicks the button and waits for the app to come back.

    python scripts/keep_awake.py https://<your-app>.streamlit.app

Exits 1 if the app doesn't come up, so the workflow run shows red. Needs playwright (+ chromium).
"""

from __future__ import annotations

import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

WAKE = "Yes, get this app back up"
UP = '[role="tab"]'          # the app's main tabs: rendered once the app has started


def app_frame(page):
    """Community Cloud serves the app inside an iframe; locally it's the page itself."""
    for frame in page.frames:
        if frame.locator(UP).count():
            return frame
    return None


def main(url: str) -> int:
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        # ?keepawake=1 so the visit isn't counted as a player's (src/usage_counts.py)
        page.goto(url + ("&" if "?" in url else "?") + "keepawake=1", wait_until="domcontentloaded",
                  timeout=120_000)
        for _ in range(60):                      # up to ~5 minutes: a woken app reinstalls and restarts
            if app_frame(page):
                print(f"up: {url}")
                return 0
            wake = page.get_by_role("button", name=WAKE)
            if wake.count():
                print("asleep: waking it")
                wake.first.click()
            try:
                page.wait_for_timeout(5_000)
            except PlaywrightTimeout:
                pass
        print(f"didn't come up within 5 minutes: {url}")
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].startswith("http"):
        print("usage: python scripts/keep_awake.py https://<your-app>.streamlit.app")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
