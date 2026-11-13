"""
fetch_usage.py

Downloads Smogon's monthly "chaos" usage stats for Pokemon Champions formats
and saves a trimmed copy under data/usage/.

Chaos files carry everything the app uses: usage %, each Pokemon's common
moves / items / abilities / Stat Point spreads, teammate co-occurrence, and
"checks and counters". The raw files are several MB, so only the parts the
app reads are kept (see src/usage.py:trim_chaos).

Usage:
    python scripts/fetch_usage.py                       # latest month, default formats
    python scripts/fetch_usage.py --month 2026-10
    python scripts/fetch_usage.py --format gen9championsvgc2026regmc --cutoff 1760

Smogon publishes a month's stats on the 1st of the next month, so "latest"
walks back from last month until it finds a published file.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.formats import FORMATS  # noqa: E402
from src.usage import trim_chaos  # noqa: E402

BASE_URL = "https://www.smogon.com/stats/{month}/chaos/{fmt}-{cutoff}.json"
OUT_DIR = ROOT / "data" / "usage"


def previous_months(count: int) -> list[str]:
    """['2026-10', '2026-09', ...] starting from last month."""
    first = dt.date.today().replace(day=1)
    months = []
    for _ in range(count):
        first = (first - dt.timedelta(days=1)).replace(day=1)
        months.append(first.strftime("%Y-%m"))
    return months


def fetch(month: str, fmt: str, cutoff: int) -> dict | None:
    url = BASE_URL.format(month=month, fmt=fmt, cutoff=cutoff)
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", help="YYYY-MM (default: newest published)")
    parser.add_argument("--format", action="append", dest="formats",
                        help="Showdown format id; repeatable (default: every format in src/formats.py)")
    parser.add_argument("--cutoff", type=int, help="rating cutoff override (default: per-format setting)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    formats = args.formats or list(FORMATS)
    months = [args.month] if args.month else previous_months(4)
    failures = 0

    for fmt in formats:
        cutoff = args.cutoff or (FORMATS[fmt].usage_cutoff if fmt in FORMATS else 1500)
        for month in months:
            raw = fetch(month, fmt, cutoff)
            if raw is None:
                print(f"  {fmt}-{cutoff}: no stats for {month}")
                continue
            trimmed = trim_chaos(raw, fmt=fmt, month=month, cutoff=cutoff)
            out = OUT_DIR / f"{fmt}.json"
            out.write_text(json.dumps(trimmed, separators=(",", ":")))
            print(f"{fmt}-{cutoff} {month}: {trimmed['info']['battles']} battles, "
                  f"{len(trimmed['pokemon'])} Pokemon -> {out.relative_to(ROOT)}")
            break
        else:
            print(f"WARNING: no published stats found for {fmt}")
            failures += 1

    return 1 if failures == len(formats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
