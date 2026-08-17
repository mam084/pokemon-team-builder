"""
clean_data.py

Reads the raw JSON pulled by fetch_data.py and turns it into a tidy pandas
DataFrame, saved as a CSV for fast loading in the Streamlit app.

Usage:
    python src/clean_data.py
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_FILE = DATA_DIR / "pokemon_raw.json"
OUTPUT_FILE = DATA_DIR / "pokemon_clean.csv"


def load_raw_data() -> list[dict]:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"{INPUT_FILE} not found. Run fetch_data.py first to generate it."
        )
    with open(INPUT_FILE) as f:
        return json.load(f)


def build_dataframe(raw_data: list[dict]) -> pd.DataFrame:
    """Flatten the nested raw records into one row per Pokemon."""
    rows = []

    for entry in raw_data:
        stats = entry["stats"]
        types = entry["types"]

        rows.append({
            "id": entry["id"],
            "name": entry["name"],
            "type_1": types[0] if len(types) > 0 else None,
            "type_2": types[1] if len(types) > 1 else None,
            "hp": stats["hp"],
            "attack": stats["attack"],
            "defense": stats["defense"],
            "special_attack": stats["special-attack"],
            "special_defense": stats["special-defense"],
            "speed": stats["speed"],
            "abilities": ", ".join(entry["abilities"]),
            "sprite": entry["sprite"],
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("id").reset_index(drop=True)
    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add a couple of simple derived stats that are handy for the dashboard."""
    stat_cols = ["hp", "attack", "defense", "special_attack", "special_defense", "speed"]
    df["base_stat_total"] = df[stat_cols].sum(axis=1)
    return df


def validate(df: pd.DataFrame) -> None:
    """Basic sanity checks - cheap insurance against a silent bad fetch."""
    missing_stats = df[df[["hp", "attack", "defense"]].isnull().any(axis=1)]
    if not missing_stats.empty:
        print(f"WARNING: {len(missing_stats)} rows have missing stat values:")
        print(missing_stats[["id", "name"]].to_string(index=False))

    duplicate_ids = df[df.duplicated("id", keep=False)]
    if not duplicate_ids.empty:
        print(f"WARNING: {len(duplicate_ids)} duplicate IDs found:")
        print(duplicate_ids[["id", "name"]].to_string(index=False))


def main():
    print(f"Loading raw data from {INPUT_FILE}...")
    raw_data = load_raw_data()

    print(f"Building DataFrame from {len(raw_data)} records...")
    df = build_dataframe(raw_data)
    df = add_derived_columns(df)

    validate(df)

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nDone. Saved {len(df)} rows to {OUTPUT_FILE}")
    print("\nPreview:")
    print(df.head())


if __name__ == "__main__":
    main()