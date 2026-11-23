"""
train_teammates.py - fit the learned teammate model (src/synergy.py) on every tournament team
list and ladder / Bo3 replay team, and save it for the app:

    data/evaluation/<regulation>_teammates.json

Run by the Refresh data workflow after new replays and tournaments arrive. How well it predicts
real teams (and the regularisation used here) comes from labs/synergy_lab.py.

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
from src.synergy import HEAD_START_DAYS, L2, MODEL_DIR, previous_lifts, prior_matrix, TOURNAMENT_WEIGHT, REPLAY_DAYS, TeammateModel, recent_records, build_vocab, replay_rows, tournament_rows  # noqa: E402

from src.formats import FORMATS  # noqa: E402

# {regulation: Showdown formats whose replays train it}, for the current formats with replays
REGULATIONS = {f.regulation: list(f.replays) for f in FORMATS.values() if f.current and f.replays}
USAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "usage"


def head_start(regulation: str, vocab: list[str], dex, today: float | None = None):
    """(vocab, prior) from the previous regulation's Smogon stats during a regulation's first
    HEAD_START_DAYS days, else (vocab, None)."""
    fmt = next((f for f in FORMATS.values() if f.regulation == regulation and f.current and f.replays), None)
    if not fmt or not fmt.previous or not fmt.start:
        return vocab, None
    age = ((today or time.time()) - time.mktime(time.strptime(fmt.start, "%Y-%m-%d"))) / 86400
    path = USAGE_DIR / f"{fmt.previous}.json"
    if age >= HEAD_START_DAYS or not path.exists():
        return vocab, None
    lifts = previous_lifts(path, dex)
    vocab = sorted(set(vocab) | {r for pair in lifts for r in pair})
    return vocab, prior_matrix(vocab, lifts)


def train(regulation: str, formats: list[str]) -> dict | None:
    dex = load_dex(regulation)
    t_rows = tournament_rows(load_tournament_teams(regulation, dex), dex, weight=TOURNAMENT_WEIGHT)
    records = recent_records([r for f in formats for r in load_records(f)])  # the last REPLAY_DAYS
    l_rows = replay_rows(records, dex)
    rows = t_rows + l_rows
    if len(rows) < 500:
        print(f"{regulation}: only {len(rows)} teams, skipped")
        return None
    t0 = time.time()
    vocab, prior = head_start(regulation, build_vocab(rows), dex)
    model = TeammateModel(vocab).fit(rows, l2=L2, prior=prior)
    meta = {"regulation": regulation, "tournament_teams": len(t_rows), "ladder_teams": len(l_rows),
            "replays": len(records), "formats": formats, "l2": L2, "replay_days": REPLAY_DAYS, "head_start": prior is not None, "trained": time.strftime("%Y-%m-%d"),
            "seconds": round(time.time() - t0)}
    out = MODEL_DIR / f"{regulation}_teammates.json"
    out.write_text(json.dumps(model.to_json(meta), separators=(",", ":")))
    print(f"{regulation}: {meta} -> {out} ({out.stat().st_size // 1024} KB)")
    return meta


if __name__ == "__main__":
    for reg, fmts in REGULATIONS.items():
        train(reg, fmts)
