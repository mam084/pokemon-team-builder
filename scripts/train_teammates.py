"""
train_teammates.py - fit the learned teammate model (src/synergy.py) on every tournament team
list and ladder / Bo3 replay team, and save it for the app:

    data/evaluation/regmc_teammates.json

Run by the Refresh data workflow after new replays and tournaments arrive. How well it predicts
real teams (and the regularisation used here) comes from scripts/synergy_lab.py.

    python scripts/train_teammates.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dex import load_dex  # noqa: E402
from src.evaluate import load_tournament_teams  # noqa: E402
from src.replays import load_records  # noqa: E402
from src.synergy import L2, MODEL_DIR, TOURNAMENT_WEIGHT, TeammateModel, build_vocab, replay_rows, tournament_rows  # noqa: E402

REGULATIONS = {"regmc": ["gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3"]}


def train(regulation: str, formats: list[str]) -> dict | None:
    dex = load_dex(regulation)
    t_rows = tournament_rows(load_tournament_teams(regulation, dex), dex, weight=TOURNAMENT_WEIGHT)
    records = [r for f in formats for r in load_records(f)]
    l_rows = replay_rows(records, dex)
    rows = t_rows + l_rows
    if len(rows) < 500:
        print(f"{regulation}: only {len(rows)} teams, skipped")
        return None
    t0 = time.time()
    model = TeammateModel(build_vocab(rows)).fit(rows, l2=L2)
    meta = {"regulation": regulation, "tournament_teams": len(t_rows), "ladder_teams": len(l_rows),
            "replays": len(records), "formats": formats, "l2": L2, "trained": time.strftime("%Y-%m-%d"),
            "seconds": round(time.time() - t0)}
    out = MODEL_DIR / f"{regulation}_teammates.json"
    out.write_text(json.dumps(model.to_json(meta), separators=(",", ":")))
    print(f"{regulation}: {meta} -> {out} ({out.stat().st_size // 1024} KB)")
    return meta


if __name__ == "__main__":
    for reg, fmts in REGULATIONS.items():
        train(reg, fmts)
