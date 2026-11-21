"""make_load_teams.py - 120 random real tournament teams as share-link tokens, for scripts/load_test.py."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.share import encode_team  # noqa: E402
from src.usage import load_usage  # noqa: E402

if __name__ == "__main__":
    dex, usage = load_dex("regmc"), load_usage("gen9championsvgc2026regmc")
    teams = [t for t in load_tournament_teams("regmc", dex, usage=usage) if len(t["sets"]) == 6]
    random.seed(11)
    out = Path(__file__).resolve().parent.parent / "data" / "load_test_teams.json"
    out.write_text(json.dumps([encode_team(t["sets"]) for t in random.sample(teams, 120)]))
    print(f"wrote {out}")
