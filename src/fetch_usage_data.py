"""
fetch_usage_data.py

Downloads a Smogon usage stats "moveset" file for a given month/format.
These are plain text files - no scraping tools needed, just a direct download.

Smogon publishes these at:
    https://www.smogon.com/stats/{YYYY-MM}/moveset/{format}-{rating}.txt

e.g. https://www.smogon.com/stats/2026-06/moveset/gen9ou-1500.txt

The "rating" in the filename is a minimum ELO cutoff - higher cutoffs (1630,
1760) reflect a more skilled player pool but with less data volume. 1500 is
a good default: skilled enough to reflect real strategy, but with enough
games played to be statistically solid.

Usage:
    python src/fetch_usage_data.py
    python src/fetch_usage_data.py --month 2026-06 --format gen9ou --rating 1500
"""

import argparse
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASE_URL = "https://www.smogon.com/stats"

DEFAULT_FORMAT = "gen9ou"
DEFAULT_RATING = 1500


def build_url(month: str, format_name: str, rating: int) -> str:
    return f"{BASE_URL}/{month}/moveset/{format_name}-{rating}.txt"


def fetch_usage_file(month: str, format_name: str, rating: int) -> str:
    """Download the raw moveset stats text file for a given month/format/rating."""
    url = build_url(month, format_name, rating)
    print(f"Fetching {url} ...")

    response = requests.get(url, timeout=15)

    if response.status_code == 404:
        raise FileNotFoundError(
            f"No usage data found at {url}. This usually means either the month "
            f"hasn't been published yet, or that rating cutoff isn't available "
            f"for this format. Check https://www.smogon.com/stats/ for what's "
            f"actually available."
        )
    response.raise_for_status()
    return response.text


def main():
    parser = argparse.ArgumentParser(description="Fetch Smogon usage stats (moveset file).")
    parser.add_argument("--month", type=str, required=True,
                         help="Month to fetch, format YYYY-MM (e.g. 2026-06). "
                              "Check https://www.smogon.com/stats/ for available months.")
    parser.add_argument("--format", type=str, default=DEFAULT_FORMAT,
                         help=f"Smogon format code (default: {DEFAULT_FORMAT}). "
                              f"Examples: gen9ou, gen9uu, gen9vgc2026regh")
    parser.add_argument("--rating", type=int, default=DEFAULT_RATING,
                         help=f"Minimum ELO rating cutoff (default: {DEFAULT_RATING}). "
                              f"Common values: 0, 1500, 1630, 1760")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    raw_text = fetch_usage_file(args.month, args.format, args.rating)

    output_file = DATA_DIR / f"usage_{args.format}_{args.month}.txt"
    with open(output_file, "w") as f:
        f.write(raw_text)

    print(f"Done. Saved to {output_file}")


if __name__ == "__main__":
    main()