"""
fetch_data.py

Pulls Pokemon data from PokeAPI (https://pokeapi.co/) and caches it as raw JSON
so we don't have to hit the API every time we run the app.

Fetches are done concurrently (a handful of requests in flight at once) since
this is an I/O-bound task - most of the time per request is spent waiting on
the network, not on CPU, so parallelizing gives a big speedup for minimal
added complexity.

Also resumable: if pokemon_raw.json already has some Pokemon in it, this
script skips re-fetching them. Useful if a run gets interrupted, or you're
expanding an existing range.

Usage:
    python src/fetch_data.py                        # fetches Gen 1 (#1-151) by default
    python src/fetch_data.py --start 1 --end 1025    # full national dex
    python src/fetch_data.py --start 1 --end 1025 --workers 20   # more parallelism
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://pokeapi.co/api/v2/pokemon/"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "pokemon_raw.json"

# How many requests to have in flight at once. PokeAPI has no hard published
# rate limit, but keep this modest to stay a good citizen of a free public API.
DEFAULT_WORKERS = 10


def fetch_pokemon(pokemon_id: int) -> dict:
    """Fetch and lightly trim the raw PokeAPI response for a single Pokemon."""
    response = requests.get(f"{BASE_URL}{pokemon_id}", timeout=10)
    response.raise_for_status()
    raw = response.json()

    stats = {s["stat"]["name"]: s["base_stat"] for s in raw["stats"]}

    return {
        "id": raw["id"],
        "name": raw["name"],
        "types": [t["type"]["name"] for t in raw["types"]],
        "abilities": [a["ability"]["name"] for a in raw["abilities"]],
        "stats": {
            "hp": stats.get("hp"),
            "attack": stats.get("attack"),
            "defense": stats.get("defense"),
            "special-attack": stats.get("special-attack"),
            "special-defense": stats.get("special-defense"),
            "speed": stats.get("speed"),
        },
        "sprite": raw["sprites"]["front_default"],
    }


def load_existing() -> dict[int, dict]:
    """Load whatever's already cached, keyed by id, so we can skip re-fetching it."""
    if not OUTPUT_FILE.exists():
        return {}
    with open(OUTPUT_FILE) as f:
        existing = json.load(f)
    return {entry["id"]: entry for entry in existing}


def fetch_range(start_id: int, end_id: int, workers: int, existing: dict[int, dict]) -> list[dict]:
    """
    Fetch a range of Pokemon by national dex ID, in parallel, skipping any
    IDs already present in `existing`. Prints progress as results come in
    (order of completion, not dex order, since requests finish out of order).
    """
    ids_to_fetch = [i for i in range(start_id, end_id + 1) if i not in existing]
    skipped = (end_id - start_id + 1) - len(ids_to_fetch)
    if skipped:
        print(f"Skipping {skipped} already-cached Pokemon.")

    results = dict(existing)  # start with what we already have
    total = len(ids_to_fetch)

    if total == 0:
        print("Nothing new to fetch.")
        return sorted(results.values(), key=lambda p: p["id"])

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_id = {executor.submit(fetch_pokemon, i): i for i in ids_to_fetch}

        completed = 0
        for future in as_completed(future_to_id):
            pokemon_id = future_to_id[future]
            completed += 1
            try:
                data = future.result()
                results[pokemon_id] = data
                print(f"[{completed}/{total}] Fetched #{pokemon_id}: {data['name']}")
            except requests.exceptions.RequestException as e:
                print(f"[{completed}/{total}] FAILED #{pokemon_id}: {e}")

    return sorted(results.values(), key=lambda p: p["id"])


def main():
    parser = argparse.ArgumentParser(description="Fetch Pokemon data from PokeAPI.")
    parser.add_argument("--start", type=int, default=1, help="Starting national dex ID (default: 1)")
    parser.add_argument("--end", type=int, default=151, help="Ending national dex ID (default: 151, Gen 1)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                         help=f"Number of concurrent requests (default: {DEFAULT_WORKERS})")
    parser.add_argument("--fresh", action="store_true",
                         help="Ignore any existing cached data and re-fetch everything")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing = {} if args.fresh else load_existing()

    print(f"Fetching Pokemon #{args.start} to #{args.end} from PokeAPI ({args.workers} workers)...")
    pokemon_data = fetch_range(args.start, args.end, args.workers, existing)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(pokemon_data, f, indent=2)

    print(f"\nDone. Saved {len(pokemon_data)} Pokemon to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()