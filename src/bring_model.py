"""
bring_model.py

Which four will a player bring, and which two will they lead with? Learned
from Showdown replays (src/replays.py), because the damage-calc game plan
barely beats picking at random (check_game_plans).

For each Pokemon on a team preview, against the opponent's preview:

- how often players bring / lead it at all (its smoothed rate in older replays)
- how it does in this matchup: average pair score, pairings it wins, how badly
  it's threatened, how many of their Pokemon it's your best answer to
- what it does: Fake Out, Tailwind, Trick Room, Intimidate, redirection, Wide
  Guard, weather / terrain, holds a Mega Stone (and whether the team has two)
- its Speed rank on the team, and whether the opponent can set Trick Room

Two logistic regressions, P(brought) and P(leads), are fitted on older replays
and judged on the newest: the top 4 by P(brought) and the top 2 by P(leads)
are compared with what players really did. The rates in the first feature come
from replays older still, so nothing is learned from the games it's tested on.

    python -m src.bring_model    # writes data/evaluation/<reg>_bring_model.json
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

import numpy as np

from src.analysis import Member, build_members
from src.dex import Dex
from src.match_model import tools_of
from src.matchup import pair_matrix, side_support
from src.replay_parse import PLAYERS
from src.replays import _sets_for, load_records

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"
FORMATS = list(__import__("src.formats", fromlist=["CURRENT"]).CURRENT.replays)
PRIOR_N = 20  # pseudo-count pulling a Pokemon's bring / lead rate toward the average

TOOL_FEATURES = ["Fake Out", "Tailwind", "Trick Room", "Intimidate", "Redirection", "Wide Guard",
                 "Weather", "Terrain", "Setup", "Speed drops"]
FEATURES = (["bring rate (log-odds)", "lead rate (log-odds)", "pair score (mean)", "pairings won",
             "worst threat", "best answer to", "speed rank", "opponent has Trick Room",
             "Mega Stone", "Mega Stone x two Megas"] + [f"tool: {t}" for t in TOOL_FEATURES])


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


def rates(records: list[dict]) -> dict:
    """Smoothed bring and lead rates per Pokemon (on preview), plus the averages."""
    seen, brought, led = Counter(), Counter(), Counter()
    for rec in records:
        for p in PLAYERS:
            for s in set(rec["preview"][p]):
                seen[s] += 1
            brought.update(set(rec["brought"][p]))
            led.update(set(rec["leads"][p]))
    total = sum(seen.values()) or 1
    avg_b, avg_l = sum(brought.values()) / total, sum(led.values()) / total
    return {"avg_bring": avg_b, "avg_lead": avg_l,
            "bring": {s: (brought[s] + PRIOR_N * avg_b) / (n + PRIOR_N) for s, n in seen.items()},
            "lead": {s: (led[s] + PRIOR_N * avg_l) / (n + PRIOR_N) for s, n in seen.items()}}


def member_features(members: list[Member], theirs: list[Member], names: list[str], prior: dict,
                    dex: Dex, matrix=None) -> np.ndarray:
    """One row per member (names: how each member is listed on preview, for the rates)."""
    if matrix is None:
        matrix = pair_matrix(members, theirs)
    values = matrix.to_numpy()
    best_rows = values.argmax(axis=0)                 # who answers each of theirs best
    speeds = [m.stats["spe"] for m in members]
    order = sorted(range(len(members)), key=lambda i: -speeds[i])
    rank = {i: r / max(1, len(members) - 1) for r, i in enumerate(order)}
    their_tr = float(side_support(theirs).trick_room)
    megas = sum(1 for m in members if m.pset is not None and m.pset.is_mega(dex))
    rows = []
    for i, m in enumerate(members):
        tools = tools_of(m)
        stone = float(m.pset is not None and m.pset.is_mega(dex))
        rows.append([
            _logit(prior["bring"].get(names[i], prior["avg_bring"])),
            _logit(prior["lead"].get(names[i], prior["avg_lead"])),
            float(values[i].mean()), float((values[i] >= 0.5).sum()) / len(theirs),
            float(values[i].min()), float((best_rows == i).sum()) / len(theirs),
            rank[i], their_tr, stone, stone * float(megas >= 2),
            *[float(t in tools) for t in TOOL_FEATURES],
        ])
    return np.array(rows)


def build_rows(records: list[dict], dex: Dex, usage, prior: dict, max_games: int | None = None,
               seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    """Feature rows with labels (brought, led) and a side id per row. Only sides that showed
    at least four Pokemon count (shorter games hide the fourth pick)."""
    if max_games and len(records) > max_games:
        records = random.Random(seed).sample(records, max_games)
    xs, yb, yl, groups = [], [], [], []
    for rec in records:
        for p, q in (("p1", "p2"), ("p2", "p1")):
            if len(set(rec["brought"][p])) < 4 or len(set(rec["leads"][p])) < 2:
                continue
            mine, theirs = _sets_for(rec, p, dex, usage), _sets_for(rec, q, dex, usage)
            preview = list(dict.fromkeys(rec["preview"][p]))
            if len(mine) != len(preview) or len(theirs) < 4:
                continue
            ma, mb = build_members(mine, dex, evolve=None), build_members(theirs, dex, evolve=None)
            x = member_features(ma, mb, preview, prior, dex)
            xs.append(x)
            yb += [float(s in rec["brought"][p]) for s in preview]
            yl += [float(s in rec["leads"][p]) for s in preview]
            groups += [(rec["id"], p)] * len(preview)
    if not xs:
        return np.zeros((0, len(FEATURES))), np.zeros(0), np.zeros(0), []
    return np.vstack(xs), np.array(yb), np.array(yl), groups


def _fit(x: np.ndarray, y: np.ndarray, c: float):
    from sklearn.linear_model import LogisticRegression
    scale = x.std(axis=0) + 1e-9
    mean = x.mean(axis=0)
    model = LogisticRegression(C=c, max_iter=3000).fit((x - mean) / scale, y)
    coef = model.coef_[0] / scale
    return {"coef": coef.tolist(), "intercept": float(model.intercept_[0] - (mean * coef).sum())}


def predict(model: dict, x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(x @ np.array(model["coef"]) + model["intercept"])))


def _score_picks(probs: np.ndarray, y: np.ndarray, groups: list, k: int) -> tuple[float, float]:
    """Mean overlap of the top-k picks with the real ones, and exact-match rate."""
    by_side: dict = {}
    for i, g in enumerate(groups):
        by_side.setdefault(g, []).append(i)
    overlap = exact = 0.0
    for idx in by_side.values():
        top = set(sorted(idx, key=lambda i: -probs[i])[:k])
        real = {i for i in idx if y[i] == 1}
        overlap += len(top & real) / max(1, len(real))
        exact += top == real
    n = len(by_side) or 1
    return overlap / n, exact / n


def train_and_report(dex: Dex, usage, formats=FORMATS, max_games: int | None = None) -> dict:
    records = []
    for fmt in formats:
        records += load_records(fmt)
    records.sort(key=lambda r: r["uploadtime"] or 0)
    n = len(records)
    prior_part, train_part, test_part = records[: n // 2], records[n // 2: 3 * n // 4], records[3 * n // 4:]
    prior = rates(prior_part)
    x_tr, b_tr, l_tr, _ = build_rows(train_part, dex, usage, prior, max_games)
    x_te, b_te, l_te, g_te = build_rows(test_part, dex, usage, prior, max_games)
    report = {"replays": n, "prior_games": len(prior_part), "train_sides": len(_groups(train_part)),
              "test_sides": len(set(g_te)), "results": {}}
    best = {}
    for label, y_tr, y_te, k in (("bring", b_tr, b_te, 4), ("lead", l_tr, l_te, 2)):
        # C by a simple split inside the training period
        cut = int(len(y_tr) * 0.7) // 6 * 6
        choice = None
        for c in (0.01, 0.1, 1.0):
            m = _fit(x_tr[:cut], y_tr[:cut], c)
            p = np.clip(predict(m, x_tr[cut:]), 1e-6, 1 - 1e-6)
            loss = -np.mean(y_tr[cut:] * np.log(p) + (1 - y_tr[cut:]) * np.log(1 - p))
            if choice is None or loss < choice[0]:
                choice = (loss, c)
        model = _fit(x_tr, y_tr, choice[1])
        best[label] = model
        learned = _score_picks(predict(model, x_te), y_te, g_te, k)
        prior_only = _score_picks(x_te[:, 0 if label == "bring" else 1], y_te, g_te, k)
        calc = _score_picks(x_te[:, 2], y_te, g_te, k)
        rnd = _score_picks(np.random.default_rng(0).random(len(y_te)), y_te, g_te, k)
        report["results"][label] = {
            "learned": [round(v, 4) for v in learned], "usual picks": [round(v, 4) for v in prior_only],
            "damage calcs": [round(v, 4) for v in calc], "random": [round(v, 4) for v in rnd], "C": choice[1]}
    # refit on all replays for the app, with rates from all of them
    prior_all = rates(records)
    x_all, b_all, l_all, _ = build_rows(records[n // 2:], dex, usage, prior_all, max_games)
    report["model"] = {"features": FEATURES,
                       "bring": _fit(x_all, b_all, report["results"]["bring"]["C"]),
                       "lead": _fit(x_all, l_all, report["results"]["lead"]["C"]),
                       "rates": {"avg_bring": prior_all["avg_bring"], "avg_lead": prior_all["avg_lead"],
                                 "bring": {k: round(v, 4) for k, v in prior_all["bring"].items()},
                                 "lead": {k: round(v, 4) for k, v in prior_all["lead"].items()}}}
    return report


def _groups(records: list[dict]) -> list:
    return [(r["id"], p) for r in records for p in PLAYERS]


def load_model(regulation: str) -> dict | None:
    path = EVAL_DIR / f"{regulation}_bring_model.json"
    return json.loads(path.read_text()) if path.exists() else None


def pick(model: dict, members: list[Member], theirs: list[Member], matrix, dex: Dex,
         keep: str | None = None) -> tuple[list, list, list]:
    """(bring 4, lead 2, P(brought) per member) for the app's game plan. `keep`: a member
    (the one Mega Evolving) that comes no matter what; the model fills the other spots.
    The model rates both holders of two Mega Stones alike, so the app decides which Mega
    by calcs (src.matchup.best_variant) and only asks the model for the rest."""
    m = model["model"]
    names = [x.pset.species if x.pset is not None else x.label for x in members]
    feats = member_features(members, theirs, names, m["rates"], dex, matrix)
    pb, pl = predict(m["bring"], feats), predict(m["lead"], feats)
    order = sorted(range(len(members)), key=lambda i: -pb[i])
    if keep is not None and keep in [x.label for x in members]:
        k = [x.label for x in members].index(keep)
        order = [k] + [i for i in order if i != k]
        order = order[:4]
        order.sort(key=lambda i: -pb[i])
    bring = [members[i].label for i in order[:4]]
    lead = [members[i].label for i in sorted(order[:4], key=lambda i: -pl[i])[:2]]
    return bring, lead, [float(v) for v in pb]


if __name__ == "__main__":
    from src.dex import load_dex
    from src.usage import load_usage
    # a sample keeps the monthly retrain to minutes once there are 100k+ replays
    from src.formats import DEFAULT_FORMAT, FORMATS
    report = train_and_report(load_dex(FORMATS[DEFAULT_FORMAT].regulation), load_usage(DEFAULT_FORMAT),
                              max_games=12000)
    out = EVAL_DIR / "regmc_bring_model.json"
    out.write_text(json.dumps(report, indent=1))
    for label, r in report["results"].items():
        print(label, {k: v for k, v in r.items()})
    print(f"-> {out}")
