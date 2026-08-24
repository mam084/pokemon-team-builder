"""
fetch_data.py

Pulls Pokemon data from PokeAPI (https://pokeapi.co/) and caches it as raw JSON
so we don't have to hit the API every time we run the app.

IMPORTANT: fetches by NAME using PokeAPI's full paginated list, not by
sequential national dex ID. Alternate/regional forms (e.g. Slowking-Galar,
Ogerpon-Wellspring) have IDs outside the normal 1-1025 dex range, so an
ID-range fetch silently misses every one of them - which matters a lot here,
since competitive teams (and Smogon's usage data) use these forms constantly.
Fetching the full name list instead guarantees we get everything PokeAPI
knows about, forms included.

Fetches are done concurrently (a handful of requests in flight at once) since
this is an I/O-bound task. Also resumable: if pokemon_raw.json already has
some Pokemon in it, this script skips re-fetching them.

Usage:
    python src/fetch_data.py                     # fetches everything (all forms)
    python src/fetch_data.py --limit 50           # fetch just the first 50 (quick test)
    python src/fetch_data.py --workers 20          # more parallelism
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://pokeapi.co/api/v2/pokemon/"
LIST_URL = "https://pokeapi.co/api/v2/pokemon"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "pokemon_raw.json"

# How many requests to have in flight at once. PokeAPI has no hard published
# rate limit, but keep this modest to stay a good citizen of a free public API.
DEFAULT_WORKERS = 10


def fetch_pokemon_list() -> list[str]:
    """
    Fetch every Pokemon name PokeAPI knows about (base species + alternate
    forms) via its paginated list endpoint. A single request with a large
    limit gets everything in one shot - the full list is under 1,500 entries.
    """
    response = requests.get(LIST_URL, params={"limit": 20000}, timeout=15)
    response.raise_for_status()
    results = response.json()["results"]
    return [entry["name"] for entry in results]


def fetch_pokemon(name: str) -> dict:
    """Fetch and lightly trim the raw PokeAPI response for a single Pokemon (by name)."""
    response = requests.get(f"{BASE_URL}{name}", timeout=10)
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


def load_existing() -> dict[str, dict]:
    """Load whatever's already cached, keyed by name, so we can skip re-fetching it."""
    if not OUTPUT_FILE.exists():
        return {}
    with open(OUTPUT_FILE) as f:
        existing = json.load(f)
    return {entry["name"]: entry for entry in existing}


def fetch_all(names: list[str], workers: int, existing: dict[str, dict]) -> list[dict]:
    """Fetch every name in `names` (in parallel), skipping any already in `existing`."""
    names_to_fetch = [n for n in names if n not in existing]
    skipped = len(names) - len(names_to_fetch)
    if skipped:
        print(f"Skipping {skipped} already-cached Pokemon.")

    results = dict(existing)
    total = len(names_to_fetch)

    if total == 0:
        print("Nothing new to fetch.")
        return sorted(results.values(), key=lambda p: p["id"])

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_name = {executor.submit(fetch_pokemon, n): n for n in names_to_fetch}

        completed = 0
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            completed += 1
            try:
                data = future.result()
                results[name] = data
                print(f"[{completed}/{total}] Fetched: {name}")
            except requests.exceptions.RequestException as e:
                print(f"[{completed}/{total}] FAILED {name}: {e}")

    return sorted(results.values(), key=lambda p: p["id"])


def main():
    parser = argparse.ArgumentParser(description="Fetch Pokemon data from PokeAPI (all forms included).")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                         help=f"Number of concurrent requests (default: {DEFAULT_WORKERS})")
    parser.add_argument("--fresh", action="store_true",
                         help="Ignore any existing cached data and re-fetch everything")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only fetch the first N names from the list (useful for quick testing)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching full Pokemon name list from PokeAPI...")
    names = fetch_pokemon_list()
    if args.limit:
        names = names[:args.limit]
    print(f"Found {len(names)} names to process.")

    existing = {} if args.fresh else load_existing()

    print(f"Fetching Pokemon data ({args.workers} workers)...")
    pokemon_data = fetch_all(names, args.workers, existing)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(pokemon_data, f, indent=2)

    print(f"\nDone. Saved {len(pokemon_data)} Pokemon to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()