"""
check_sprites.py - which Mega / battle-only formes have their own Showdown sprite?

Showdown has gen5-style sprites for most older Megas but not every newer one. The app shows
the Mega's sprite when this check found one and the base Pokemon's otherwise. Writes
data/dex/<regulation>_sprites.json; run by the Refresh data workflow.

    python scripts/check_sprites.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dex import SPRITE_URL, load_dex  # noqa: E402
from src.formats import FORMATS  # noqa: E402


def main() -> None:
    for regulation in sorted({f.regulation for f in FORMATS.values() if f.current}):
        dex = load_dex(regulation)
        forms = sorted({s.sprite for s in dex.species.values() if s.is_mega or s.battle_only})
        found = []
        for sprite in forms:
            try:
                r = requests.head(SPRITE_URL.format(sprite), timeout=15, allow_redirects=True)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    found.append(sprite)
            except requests.RequestException:
                pass
            time.sleep(0.1)
        out = ROOT / "data" / "dex" / f"{regulation}_sprites.json"
        out.write_text(json.dumps({"checked": len(forms), "available": found}, indent=1))
        print(f"{regulation}: {len(found)} of {len(forms)} Mega/battle formes have sprites -> {out}")


if __name__ == "__main__":
    main()
