"""
synergy.py

A learned teammate model: which Pokemon belong together, fitted on real teams.

Lift-style synergy (src/usage.py pair_lift, src/cooccurrence.py) looks at one pair at a time,
so it can't tell a real partnership from two Pokemon that only show up together because both
go with a third (Incineroar and Rillaboom both pair with Sinistcha; are they partners, or
just common in the same teams?). This model scores a candidate against the whole team at
once and is fitted the way it is used - "given these five, what is the sixth?":

    P(candidate c | team T)  ∝  exp( b_c + Σ_{m in T} W[m, c] )

b_c is how often c gets picked at all; W[m, c] (symmetric) is the pull between m and c *after*
accounting for everyone else on the team. Fitted by maximum likelihood on every member of
every team left out in turn (L2-regularised, so pairs seen rarely stay near 0), on:

    - tournament team lists (src/evaluate.py load_tournament_teams)
    - ladder / Bo3 team previews from replays (src/replays.py), each player's team counted once,
      higher ratings weighted more

The pairing of W[m, c] values gives the "why": which members a candidate fits with, in
log-odds. labs/synergy_lab.py compares this against lift on held-out tournaments.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.dex import Dex

MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"
# Chosen on held-out tournaments (labs/synergy_lab.py): light regularisation, and tournament
# teams counted 3x (curated teams; the ladder adds volume and the rarer Pokemon)
L2 = 2.0
TOURNAMENT_WEIGHT = 3.0
# Replays older than this stopped helping as the meta moved: on held-out tournaments, the last
# 21-30 days scored MRR 0.656-0.657 and 45+ days 0.650 (labs/synergy_lab.py, Nov 17)
REPLAY_DAYS = 30


def recent_records(records: list[dict], end: float | None = None, days: int = REPLAY_DAYS) -> list[dict]:
    """Replays uploaded in the `days` before `end` (default: the newest one)."""
    times = [r["uploadtime"] for r in records if r.get("uploadtime")]
    if not times:
        return []
    end = end if end is not None else max(times)
    return [r for r in records if r.get("uploadtime") and end - days * 86400 <= r["uploadtime"] < end + 1]


@dataclass
class TeamRow:
    roots: tuple[str, ...]   # team-sheet ids (Megas as their base)
    weight: float
    time: float              # unix time (tournaments: their date at noon UTC)
    source: str


# A new regulation's first days: pulls start from the previous regulation's Smogon teammate stats
# instead of 0 (labs/regulation_start_lab.py: better at 1, 3, 7 and 14 days of data, gain fading).
HEAD_START_DAYS = 15
HEAD_START_STRENGTH = 0.5


def previous_lifts(usage_path: Path, dex: Dex) -> dict[tuple[str, str], float]:
    """log-lift by root pair from a regulation's Smogon stats: share of teams with both over
    (share with a x share with b), forms merged into their root, clipped to +-2."""
    import ast
    data = json.loads(Path(usage_path).read_text())["pokemon"]
    use, joint = defaultdict(float), defaultdict(float)
    for name, e in data.items():
        ra = root_of(name, dex)
        if not ra:
            continue
        u = float(e["usage"])
        use[ra] += u
        mates = e.get("teammates") or {}
        mates = mates if isinstance(mates, dict) else ast.literal_eval(mates)
        for other, pct in mates.items():
            rb = root_of(other, dex)
            if rb and rb != ra:
                joint[(ra, rb)] += u * float(pct) / 100.0
    lifts = {}
    for (a, b), j in joint.items():
        jj = (j + joint.get((b, a), j)) / 2
        if use[a] > 0 and use[b] > 0 and jj > 0:
            lifts[(a, b)] = float(np.clip(np.log(jj * 100.0 / (use[a] * use[b])), -2.0, 2.0))
    return lifts


def prior_matrix(vocab: list[str], lifts: dict, strength: float = HEAD_START_STRENGTH) -> np.ndarray:
    idx = {r: i for i, r in enumerate(vocab)}
    W0 = np.zeros((len(vocab), len(vocab)))
    for (a, b), v in lifts.items():
        if a in idx and b in idx:
            W0[idx[a], idx[b]] = strength * v
    W0 = (W0 + W0.T) / 2
    np.fill_diagonal(W0, 0.0)
    return W0


def root_of(name: str, dex: Dex) -> str | None:
    s = dex.get_species(name)
    return dex.sheet_id(s) if s is not None else None


def rating_weight(rating: float | None) -> float:
    """Ladder teams count more the higher they're rated: 0.25 unrated or at 1000, 1 at 1500+."""
    if not rating:
        return 0.25
    return float(min(1.0, max(0.25, 0.25 + 0.75 * (rating - 1000) / 500)))


def tournament_rows(teams: list[dict], dex: Dex, weight: float = 1.0) -> list[TeamRow]:
    from datetime import datetime, timezone
    rows = []
    for t in teams:
        roots = tuple(sorted({r for p in t["sets"] if (r := root_of(p.species, dex))}))
        if len(roots) >= 4:
            ts = datetime.fromisoformat(t["date"]).replace(hour=12, tzinfo=timezone.utc).timestamp()
            rows.append(TeamRow(roots, weight, ts, "tournament"))
    return rows


def replay_rows(records: list[dict], dex: Dex, weight: float = 1.0) -> list[TeamRow]:
    """One row per (player, team): a player laddering one team 40 times counts once, at their
    best rating with it."""
    best: dict[tuple, TeamRow] = {}
    for rec in records:
        for p in ("p1", "p2"):
            preview = rec["preview"][p]
            roots = tuple(sorted({r for s in preview if (r := root_of(s, dex))}))
            if len(roots) < 4:
                continue
            key = (rec["players"][p]["name"].lower(), roots)
            w = weight * rating_weight(rec["players"][p]["rating"])
            t = float(rec["uploadtime"] or 0)
            old = best.get(key)
            if old is None or w > old.weight:
                best[key] = TeamRow(roots, w, min(t, old.time) if old else t, "ladder")
    return list(best.values())


class TeammateModel:
    """P(c | team) ∝ exp(b_c + Σ_m W[m, c]). See the module docstring."""

    def __init__(self, vocab: list[str]):
        self.vocab = list(vocab)
        self.index = {r: i for i, r in enumerate(self.vocab)}
        v = len(self.vocab)
        self.b = np.zeros(v)
        self.W = np.zeros((v, v))
        self.counts = np.zeros(v)
        self.formats: list[str] = []
        self.meta: dict = {}

    # ---- fitting -----------------------------------------------------------
    def _encode(self, rows: list[TeamRow]) -> tuple[np.ndarray, np.ndarray]:
        x = np.zeros((len(rows), len(self.vocab)), dtype=np.float32)
        w = np.zeros(len(rows))
        for n, row in enumerate(rows):
            ids = [self.index[r] for r in row.roots if r in self.index]
            x[n, ids] = 1.0
            w[n] = row.weight
        keep = x.sum(1) >= 4
        return x[keep], w[keep]

    def fit(self, rows: list[TeamRow], l2: float = 2.0, epochs: int = 60, lr: float = 0.05,
            batch: int = 4096, seed: int = 0, verbose: bool = False,
            prior: np.ndarray | None = None) -> "TeammateModel":
        """prior: pulls to shrink toward instead of 0 (a head start, see head_start_prior)."""
        x, w = self._encode(rows)
        W0 = np.zeros((len(self.vocab), len(self.vocab))) if prior is None else prior
        self.W = W0.copy()
        self.counts = (x * w[:, None]).sum(0)
        rng = np.random.default_rng(seed)
        v = len(self.vocab)
        # Adam on (b, W); W kept symmetric with a zero diagonal
        mb, vb = np.zeros(v), np.zeros(v)
        mW, vW = np.zeros((v, v)), np.zeros((v, v))
        total_w = w.sum()
        step = 0
        for epoch in range(epochs):
            order = rng.permutation(len(x))
            loss_sum = 0.0
            for start in range(0, len(x), batch):
                idx = order[start:start + batch]
                xb, wb = x[idx], w[idx]
                gb, gW, loss = self._grad(xb, wb)
                # objective: mean weighted NLL + l2/2 ||W||^2 / total weight (l2 ~ "teams of
                # evidence" a pair needs before its pull moves far from 0)
                gb, gW = gb / wb.sum(), gW / wb.sum() + l2 * (self.W - W0) / total_w
                gW = (gW + gW.T) / 2
                np.fill_diagonal(gW, 0.0)
                step += 1
                for p, g, m_, v_ in ((self.b, gb, mb, vb), (self.W, gW, mW, vW)):
                    m_ *= 0.9
                    m_ += 0.1 * g
                    v_ *= 0.999
                    v_ += 0.001 * g * g
                    p -= lr * (m_ / (1 - 0.9 ** step)) / (np.sqrt(v_ / (1 - 0.999 ** step)) + 1e-8)
                loss_sum += loss
            if verbose and (epoch % 10 == 0 or epoch == epochs - 1):
                print(f"  epoch {epoch}: loss {loss_sum / total_w:.4f}")
        return self

    def _grad(self, xb: np.ndarray, wb: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        """Leave-one-out softmax over every member of every team in the batch."""
        v = len(self.vocab)
        s = xb @ self.W                              # (n, v): Σ_m W[m, :] over the whole team
        gb = np.zeros(v)
        gW = np.zeros((v, v))
        loss = 0.0
        rows, cols = np.nonzero(xb)                  # one example per (team, hidden member)
        ctx = xb[rows].copy()
        ctx[np.arange(len(rows)), cols] = 0.0        # the other members
        logits = self.b + s[rows] - self.W[cols]     # remove the hidden member's own row
        logits = np.where(ctx > 0, -1e9, logits)     # can't pick someone already on the team
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(1, keepdims=True)
        ew = wb[rows]
        loss = float(-(np.log(p[np.arange(len(rows)), cols] + 1e-12) * ew).sum())
        d = p * ew[:, None]
        d[np.arange(len(rows)), cols] -= ew          # dL/dlogits = p - y, weighted
        gb = d.sum(0)
        gW = ctx.T @ d                               # each context member's row gets (p - y)
        return gb, gW, loss

    # ---- use ----------------------------------------------------------------
    def scores(self, team: list[str]) -> np.ndarray:
        """Logit per vocab entry for joining these team roots (unknown roots ignored)."""
        ids = [self.index[r] for r in team if r in self.index]
        return self.b + self.W[ids].sum(0)

    def fit_scores(self, team: list[str]) -> np.ndarray:
        """Synergy alone: Σ_m W[m, c] (no popularity term)."""
        ids = [self.index[r] for r in team if r in self.index]
        return self.W[ids].sum(0) if ids else np.zeros(len(self.vocab))

    def pick_probs(self, team: list[str]) -> np.ndarray:
        """P(each vocab entry is the next pick | these team roots): the model's softmax with the
        team itself excluded. 'Players with your other five pick X 12% of the time.'"""
        s = self.scores(team)
        roots = set(team)
        on = np.array([r in roots for r in self.vocab])
        s = np.where(on, -np.inf, s)
        p = np.exp(s - s[~on].max())
        return p / p.sum()

    def member_probs(self, team: list[str]) -> list[float | None]:
        """fit_check's probabilities alone (the team rating needs only these)."""
        out = []
        for root in team:
            rest = [r for r in team if r != root]
            out.append(float(self.pick_probs(rest)[self.index[root]]) if root in self.index and rest else None)
        return out

    def fit_check(self, team: list[str], top: int = 3) -> list[dict]:
        """For each member: how usual it is next to the rest (probability and rank among every
        Pokemon the model knows), and what players most often run with the rest instead."""
        out = []
        for root in team:
            rest = [r for r in team if r != root]
            if root not in self.index or not rest:
                out.append({"root": root, "prob": None, "rank": None, "instead": []})
                continue
            p = self.pick_probs(rest)
            i = self.index[root]
            order = np.argsort(-p)
            out.append({"root": root, "prob": float(p[i]), "rank": int((p > p[i]).sum()) + 1,
                        "instead": [(self.vocab[j], float(p[j])) for j in order if j != i][:top]})
        return out

    def links(self, team: list[str]) -> dict[str, tuple[str, float] | None]:
        """Each member's strongest partner on this team: (partner root, pull in log-odds)."""
        out = {}
        for r in team:
            best = max(((self.pull(r, o), o) for o in team if o != r and o in self.index and r in self.index),
                       default=None)
            out[r] = (best[1], best[0]) if best else None
        return out

    def confidence(self, k: float = 100.0) -> np.ndarray:
        """0..1 per vocab entry: how much data backs it (weighted teams n -> n / (n + k)). Used to
        damp the popularity-free fit of rarely used Pokemon, whose pulls rest on few teams."""
        return self.counts / (self.counts + k)

    def pull(self, member: str, candidate: str) -> float:
        i, j = self.index.get(member), self.index.get(candidate)
        return float(self.W[i, j]) if i is not None and j is not None else 0.0

    # ---- persistence --------------------------------------------------------
    def to_json(self, meta: dict) -> dict:
        v = len(self.vocab)
        pairs = [[i, j, round(float(self.W[i, j]), 4)] for i in range(v) for j in range(i + 1, v)
                 if abs(self.W[i, j]) >= 0.02]
        return {**meta, "vocab": self.vocab, "bias": [round(float(x), 4) for x in self.b],
                "counts": [round(float(x), 2) for x in self.counts], "pairs": pairs}

    @classmethod
    def from_json(cls, data: dict) -> "TeammateModel":
        m = cls(data["vocab"])
        m.b = np.array(data["bias"], dtype=float)
        m.counts = np.array(data.get("counts", [0.0] * len(m.vocab)), dtype=float)
        m.formats = list(data.get("formats", []))
        m.meta = {k: v for k, v in data.items() if k not in ("vocab", "bias", "counts", "pairs")}
        for i, j, val in data["pairs"]:
            m.W[i, j] = m.W[j, i] = val
        return m


def build_vocab(rows: list[TeamRow], min_weight: float = 3.0) -> list[str]:
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        for root in r.roots:
            totals[root] += r.weight
    return sorted(k for k, v in totals.items() if v >= min_weight)


def load_model(regulation: str) -> TeammateModel | None:
    path = MODEL_DIR / f"{regulation}_teammates.json"
    if not path.exists():
        return None
    try:
        return TeammateModel.from_json(json.loads(path.read_text()))
    except (OSError, ValueError, KeyError):
        return None


__all__ = ["TeamRow", "TeammateModel", "tournament_rows", "replay_rows", "build_vocab", "load_model",
           "rating_weight", "root_of", "L2", "TOURNAMENT_WEIGHT", "MODEL_DIR", "math"]
