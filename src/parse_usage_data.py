"""
parse_usage_data.py

Parses a Smogon moveset stats .txt file (as downloaded by fetch_usage_data.py)
into tidy structures:
  - usage_summary.csv: one row per (pokemon, tier) - raw count, avg weight, viability ceiling
  - teammates.csv: one row per (pokemon, teammate, co-occurrence %, tier) - this is
    the long/tidy format the recommender is built on.

Supports multiple tiers: run this once per tier (gen9ou, gen9uu, etc.) and
each run adds/replaces that tier's rows in the shared output files, rather
than overwriting the whole file. This lets the dashboard offer a tier
selector without needing separate files per tier.

The moveset file format looks like:

    +----------------------------------------+
    | Great Tusk                             |
    +----------------------------------------+
    | Raw count: 458159                      |
    | Avg. weight: 0.6416342689066006        |
    | Viability Ceiling: 91                  |
    +----------------------------------------+
    | Abilities                              |
    | Protosynthesis 100.000%                |
    +----------------------------------------+
    ... (Items, Spreads, Moves, Tera Types) ...
    +----------------------------------------+
    | Teammates                              |
    | Gholdengo 29.643%                      |
    | Kingambit 25.427%                      |
    ...
    +----------------------------------------+

Each Pokemon's block always ends after its Teammates section, then the next
Pokemon's block begins.

Usage:
    python src/parse_usage_data.py --input data/usage_gen9ou_2026-06.txt --tier gen9ou
    python src/parse_usage_data.py --input data/usage_gen9uu_2026-06.txt --tier gen9uu
"""

import argparse
import re
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

BORDER_RE = re.compile(r"^\+-+\+$")
ENTRY_RE = re.compile(r"^(.*\S)\s+([\d.]+)%$")  # e.g. "Heavy-Duty Boots 29.305%"

# Section headers that appear between the stats block and the Teammates section.
# We only need Teammates for the recommender, but recognizing all of them lets
# the parser correctly track where "Teammates" starts.
SECTION_HEADERS = {"Abilities", "Items", "Spreads", "Moves", "Tera Types", "Teammates", "Checks and Counters"}


def strip_pipes(line: str) -> str:
    """Turn '| Great Tusk                             |' into 'Great Tusk'."""
    return line.strip().strip("|").strip()


def chunk_file(text: str) -> list[list[str]]:
    """
    Split the raw file into chunks of content lines, using the '+---+' border
    lines as delimiters. Each chunk is a list of stripped, non-empty content
    lines between two borders.
    """
    chunks = []
    current = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if BORDER_RE.match(line.strip()):
            if current:
                chunks.append(current)
                current = []
            continue
        content = strip_pipes(line)
        if content:
            current.append(content)

    if current:
        chunks.append(current)

    return chunks


def parse_entries(lines: list[str]) -> list[tuple[str, float]]:
    """Parse lines like 'Gholdengo 29.643%' into [(name, pct), ...], skipping 'Other'."""
    entries = []
    for line in lines:
        match = ENTRY_RE.match(line)
        if not match:
            continue
        name, pct = match.group(1), float(match.group(2))
        if name == "Other":
            continue
        entries.append((name, pct))
    return entries


def parse_stats_block(lines: list[str]) -> dict:
    """Parse the 'Raw count / Avg. weight / Viability Ceiling' chunk."""
    stats = {"raw_count": None, "avg_weight": None, "viability_ceiling": None}
    for line in lines:
        if line.startswith("Raw count:"):
            stats["raw_count"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("Avg. weight:"):
            stats["avg_weight"] = float(line.split(":", 1)[1].strip())
        elif line.startswith("Viability Ceiling:"):
            stats["viability_ceiling"] = int(line.split(":", 1)[1].strip())
    return stats


def parse_moveset_file(text: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Walk the chunked file positionally: each Pokemon record is a name chunk,
    followed by a stats chunk, followed by zero or more section chunks whose
    header is a known SECTION_HEADERS name (Abilities, Items, Spreads, Moves,
    Tera Types, Teammates, Checks and Counters - in whatever order they
    appear). The first chunk whose header is NOT a known section marks the
    start of the next Pokemon's record.

    This is deliberately order/presence-agnostic rather than assuming a fixed
    section sequence, so it won't break if a section is missing for some
    Pokemon or if Smogon changes the section order in a future format.
    """
    chunks = chunk_file(text)
    summary_rows = []
    teammate_rows = []

    i = 0
    n = len(chunks)

    while i < n:
        current_name = chunks[i][0]
        i += 1
        if i >= n:
            break  # malformed trailing chunk with no stats block - nothing more to parse

        stats = parse_stats_block(chunks[i])
        summary_rows.append({"pokemon": current_name, **stats})
        i += 1

        while i < n and chunks[i][0] in SECTION_HEADERS:
            header = chunks[i][0]
            if header == "Teammates":
                for teammate, pct in parse_entries(chunks[i][1:]):
                    teammate_rows.append({
                        "pokemon": current_name,
                        "teammate": teammate,
                        "co_occurrence_pct": pct,
                    })
            # Other sections (Abilities, Items, Spreads, Moves, Tera Types,
            # Checks and Counters) are intentionally skipped for now - not
            # needed until later stages.
            i += 1

    summary_df = pd.DataFrame(summary_rows).drop_duplicates(subset="pokemon").reset_index(drop=True)
    teammates_df = pd.DataFrame(teammate_rows)

    return summary_df, teammates_df


def load_existing_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=columns)


def main():
    parser = argparse.ArgumentParser(description="Parse a Smogon moveset stats file.")
    parser.add_argument("--input", type=str, required=True,
                         help="Path to the raw .txt file from fetch_usage_data.py")
    parser.add_argument("--tier", type=str, required=True,
                         help="Tier/format label for this file, e.g. gen9ou, gen9uu, gen9ru. "
                              "Stored as a column so multiple tiers can coexist in the same output files.")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"{input_path} not found. Run fetch_usage_data.py first.")

    text = input_path.read_text()
    summary_df, teammates_df = parse_moveset_file(text)
    summary_df["tier"] = args.tier
    teammates_df["tier"] = args.tier

    summary_path = DATA_DIR / "usage_summary.csv"
    teammates_path = DATA_DIR / "teammates.csv"

    # Accumulate: replace any existing rows for this tier, keep rows for
    # other tiers untouched, so running this script for gen9ou then gen9uu
    # builds up one combined file rather than each run overwriting the last.
    existing_summary = load_existing_or_empty(
        summary_path, ["pokemon", "raw_count", "avg_weight", "viability_ceiling", "tier"]
    )
    existing_summary = existing_summary[existing_summary["tier"] != args.tier]
    combined_summary = pd.concat([existing_summary, summary_df], ignore_index=True)

    existing_teammates = load_existing_or_empty(
        teammates_path, ["pokemon", "teammate", "co_occurrence_pct", "tier"]
    )
    existing_teammates = existing_teammates[existing_teammates["tier"] != args.tier]
    combined_teammates = pd.concat([existing_teammates, teammates_df], ignore_index=True)

    combined_summary.to_csv(summary_path, index=False)
    combined_teammates.to_csv(teammates_path, index=False)

    print(f"Parsed {len(summary_df)} Pokemon for tier '{args.tier}'.")
    print(f"Saved summary ({len(combined_summary)} total rows across all tiers) to {summary_path}")
    print(f"Saved teammates ({len(combined_teammates)} total rows across all tiers) to {teammates_path}")
    print("\nSummary preview:")
    print(summary_df.head())
    print("\nTeammates preview:")
    print(teammates_df.head())


if __name__ == "__main__":
    main()