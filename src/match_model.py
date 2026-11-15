"""
match_model.py

A model of who wins real tournament matches, learned from data.

The Matchups tab's score is hand-built: damage calcs both ways plus Speed, one
pairing at a time. It can't see support (screens, Fake Out, Tailwind...), and
hand-picking how much support should count made predictions worse
(src/validate.py). So instead this module *learns* what matters from Limitless
matches where both players' team lists are known.

Every feature is a difference "player 1 minus player 2", so swapping the
players flips the sign of every feature:

- matchup: the hand-built team-vs-team score, bring-4 score, mean best damage
  each way, OHKO / 2HKO counts each way, share of pairings won on Speed
- support tools: how many of each side's Pokemon carry Fake Out, Intimidate,
  Tailwind, Trick Room, screens, redirection, Wide Guard, sleep, Taunt,
  Encore, Helping Hand, spread speed control, priority, weather / terrain
- context: Trick Room x how slow the team is, Tailwind x how fast it is
- Pokemon: which species each side has (+1 / -1 / 0), kept to species seen on
  enough team sheets, so the model can learn "Pokemon X wins more than its calcs
  say" - which is where support Pokemon show up.

Models are L2-regularized logistic regressions (interpretable: each support
tool gets a coefficient in win-probability points), compared with boosted
trees, all fitted on older tournaments and judged on the newest 30%. The
regularization strength is chosen by forward-chaining cross-validation inside
the training period only.

    python -m src.match_model      # builds features, trains, writes data/evaluation/<reg>_match_model.json
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis import Member, build_members
from src.dex import Dex, load_dex
from src.evaluate import TOURNAMENT_DIR, load_tournament_teams
from itertools import combinations

from src.matchup import MAX_HITS, build_archetypes, pair_parts, scores_from_parts, side_support
from src.swaps import SwapEngine
from src.usage import load_usage

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "evaluation"
_NO_SUPPORT = side_support([])
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

# --------------------------------------------------------------------------
# Support tools: (moves, abilities)
# --------------------------------------------------------------------------
TOOLS: dict[str, tuple[set[str], set[str]]] = {
    "Fake Out": ({"fakeout"}, set()),
    "Intimidate": (set(), {"intimidate"}),
    "Tailwind": ({"tailwind"}, set()),
    "Trick Room": ({"trickroom"}, set()),
    "Reflect": ({"reflect", "auroraveil"}, set()),
    "Light Screen": ({"lightscreen", "auroraveil"}, set()),
    "Redirection": ({"followme", "ragepowder"}, {"lightningrod", "stormdrain"}),
    "Wide Guard": ({"wideguard"}, set()),
    "Sleep": ({"spore", "sleeppowder", "hypnosis", "yawn", "darkvoid", "lovelykiss"}, set()),
    "Taunt": ({"taunt"}, set()),
    "Encore": ({"encore"}, set()),
    "Helping Hand": ({"helpinghand"}, set()),
    "Speed drops": ({"icywind", "electroweb", "bulldoze", "rocktomb", "scaryface"}, set()),
    "Paralysis": ({"thunderwave", "nuzzle", "glare", "stunspore"}, set()),
    "Burn": ({"willowisp"}, set()),
    "Priority attack": (set(), set()),   # filled from move priority below
    "Weather": ({"raindance", "sunnyday", "sandstorm", "snowscape", "chillyreception"},
                {"drizzle", "drought", "sandstream", "snowwarning", "orichalcumpulse"}),
    "Terrain": ({"psychicterrain", "grassyterrain", "electricterrain", "mistyterrain"},
                {"psychicsurge", "grassysurge", "electricsurge", "mistysurge", "hadronengine"}),
    "Setup": ({"swordsdance", "nastyplot", "calmmind", "dragondance", "bulkup", "quiverdance",
               "shellsmash", "irondefense", "coil", "shiftgear", "bellydrum", "victorydance",
               "tidyup", "workup", "agility", "rockpolish"}, set()),
    "Recovery": ({"recover", "roost", "slackoff", "softboiled", "moonlight", "morningsun",
                  "synthesis", "shoreup", "strengthsap", "wish", "milkdrink"}, {"regenerator"}),
}


def tools_of(m: Member) -> set[str]:
    moves = {mv["id"] for mv in m.moves}
    out = {name for name, (mv, ab) in TOOLS.items() if moves & mv or m.ability_id in ab}
    if any(mv["priority"] > 0 and mv["category"] != "Status" and mv["id"] != "fakeout" for mv in m.moves):
        out.add("Priority attack")
    return out


def side_profile(members: list[Member]) -> dict[str, float]:
    tools = [tools_of(m) for m in members]
    prof = {f"tool: {t}": float(sum(t in ts for ts in tools)) for t in TOOLS}
    spe = [m.form.base_stats["spe"] for m in members]
    prof["base speed (mean)"] = float(np.mean(spe)) if spe else 0.0
    prof["bulk (mean)"] = float(np.mean([m.stats["hp"] * (m.stats["def"] + m.stats["spd"]) / 2
                                         for m in members]) / 10000) if members else 0.0
    # context: a Trick Room setter matters more on a slow team, Tailwind on a fast one
    slow = max(0.0, (90 - prof["base speed (mean)"]) / 30)
    fast = max(0.0, (prof["base speed (mean)"] - 70) / 30)
    prof["Trick Room x slow team"] = min(prof["tool: Trick Room"], 1.0) * slow
    prof["Tailwind x fast team"] = min(prof["tool: Tailwind"], 1.0) * fast
    prof["has Mega"] = float(any(m.form.is_mega for m in members))
    return prof


def _hits(pct: np.ndarray) -> np.ndarray:
    safe = np.where(pct > 0, pct, 1.0)
    return np.where(pct > 0, np.minimum(MAX_HITS, np.ceil(100 / safe - 1e-9)), MAX_HITS)


def _score(m: np.ndarray) -> float:
    return float(m.max(axis=0).mean() - (-m).max(axis=1).mean())


_COMBOS: dict[tuple[int, int], np.ndarray] = {}


def _bring(m: np.ndarray, n: int = 4) -> float:
    """matchup.best_bring's score, vectorized over every n-of-6 (it runs for every candidate swap)."""
    if m.shape[0] <= n:
        return _score(m)
    combos = _COMBOS.setdefault((m.shape[0], n), np.array(list(combinations(range(m.shape[0]), n))))
    sub = m[combos]                                   # (combos, n, their team)
    score = sub.max(axis=1).mean(axis=1) - (-sub).max(axis=2).mean(axis=1)
    tie = sub.mean(axis=(1, 2))
    return float(score[np.lexsort((tie, score))[-1]])


def matchup_features(parts: dict[str, np.ndarray], ma=None, mb=None) -> dict[str, float]:
    """Antisymmetric summaries of the pair parts (player 1 = rows)."""
    base = scores_from_parts(parts, _NO_SUPPORT, _NO_SUPPORT, False, strength=0.0)
    h2h = _score(base)
    bring_a, bring_b = _bring(base), _bring(-base.T)
    a_hits, b_hits = _hits(parts["a_pct"]), _hits(parts["b_pct"])
    return {
        "matchup score": h2h,
        "bring-4 score": float(bring_a - bring_b),
        "best damage (mean %)": float(np.minimum(parts["a_pct"], 150).max(axis=1).mean()
                                      - np.minimum(parts["b_pct"], 150).max(axis=0).mean()) / 100,
        "OHKOs": float((a_hits <= 1).sum() - (b_hits <= 1).sum()) / 6,
        "2HKOs": float((a_hits <= 2).sum() - (b_hits <= 2).sum()) / 6,
        "outspeeds (share)": float((parts["a_spe"] > parts["b_spe"]).mean()
                                   - (parts["a_spe"] < parts["b_spe"]).mean()),
    }


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------
def _sides(teams: dict, dex: Dex) -> dict:
    out = {}
    for key, t in teams.items():
        sets = t["sets"]
        megas = [i for i, p in enumerate(sets) if p.is_mega(dex)]
        out[key] = build_members(sets, dex, evolve=megas[0] if megas else None)
    return out


def build_dataset(regulation: str = "regmc", format_id: str = "gen9championsvgc2026regmc",
                  cache: bool = True, verbose: bool = True) -> pd.DataFrame:
    """One row per decided match with both team lists: features, species, outcome."""
    path = CACHE_DIR / f"{regulation}_match_features.pkl"
    matches_path = TOURNAMENT_DIR / f"{regulation}_matches.json"
    if cache and path.exists() and path.stat().st_mtime > matches_path.stat().st_mtime:
        return pd.read_pickle(path)
    dex, usage = load_dex(regulation), load_usage(format_id)
    teams = {(t["tournament"], t["player"]): t for t in load_tournament_teams(regulation, dex, usage=usage)}
    matches = json.loads(matches_path.read_text())["matches"]
    used = {(m["tournament"], p) for m in matches for p in (m["p1"], m["p2"])}
    teams = {k: v for k, v in teams.items() if k in used}
    members = _sides(teams, dex)
    engine = SwapEngine(build_archetypes(usage, dex), usage, dex, True)
    meta, profiles, species, pop = {}, {}, {}, {}
    for key, t in teams.items():
        meta[key] = engine.overall(t["sets"])
        profiles[key] = side_profile(members[key])
        species[key] = sorted({dex.sheet_id(s) for p in t["sets"] if (s := dex.get_species(p.species))})
        pop[key] = float(np.mean([usage.species_usage(p.species, dex) for p in t["sets"]]))
    rows, start = [], time.time()
    for n, m in enumerate(matches):
        a, b = (m["tournament"], m["p1"]), (m["tournament"], m["p2"])
        if a not in teams or b not in teams or m["winner"] not in (m["p1"], m["p2"]):
            continue
        ma, mb = members[a], members[b]
        row = {"tournament": m["tournament"], "date": teams[a]["date"], "round": m.get("round"),
               "phase": m.get("phase"), "p1": m["p1"], "p2": m["p2"],
               "won": int(m["winner"] == m["p1"]), "species_a": species[a], "species_b": species[b]}
        row.update(matchup_features(pair_parts(ma, mb), ma, mb))
        row["score vs meta"] = meta[a] - meta[b]
        row["popularity"] = (pop[a] - pop[b]) / 10
        for k in profiles[a]:
            row[k] = profiles[a][k] - profiles[b][k]
        rows.append(row)
        if verbose and n % 2000 == 0:
            print(f"  {n}/{len(matches)} matches, {time.time() - start:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    if cache:
        CACHE_DIR.mkdir(exist_ok=True)
        df.to_pickle(path)
    return df


# --------------------------------------------------------------------------
# Feature sets and models
# --------------------------------------------------------------------------
MATCHUP = ["matchup score", "bring-4 score", "best damage (mean %)", "OHKOs", "2HKOs", "outspeeds (share)"]
CONTEXT = ["score vs meta", "popularity", "base speed (mean)", "bulk (mean)", "has Mega"]
SUPPORT = [f"tool: {t}" for t in TOOLS]
INTERACT = ["Trick Room x slow team", "Tailwind x fast team"]
SKILL = ["skill (Elo)", "experience"]


def add_skill(df: pd.DataFrame, regulation: str) -> pd.DataFrame:
    """Each player's Elo and games played *before* the match (src/ratings.py), as features:
    the Elo log-odds of player 1 winning and the difference in log games played."""
    from src.ratings import K_BASE, NEW_BOOST, ordered_matches, run
    pre = {(r["tournament"], r.get("phase"), r.get("round"), r["p1"], r["p2"]): r
           for r in run(ordered_matches(regulation), K_BASE, NEW_BOOST)}
    rows = [pre.get((t, ph, rd, a, b)) for t, ph, rd, a, b in
            zip(df["tournament"], df["phase"], df["round"], df["p1"], df["p2"])]
    df = df.copy()
    df["skill (Elo)"] = [((r["r1"] - r["r2"]) / 400 * math.log(10)) if r else 0.0 for r in rows]
    df["experience"] = [(math.log1p(r["g1"]) - math.log1p(r["g2"])) if r else 0.0 for r in rows]
    return df


def species_matrix(df: pd.DataFrame, vocab: list[str]) -> np.ndarray:
    index = {s: i for i, s in enumerate(vocab)}
    out = np.zeros((len(df), len(vocab)))
    for r, (sa, sb) in enumerate(zip(df["species_a"], df["species_b"])):
        for s in sa:
            if s in index:
                out[r, index[s]] += 1
        for s in sb:
            if s in index:
                out[r, index[s]] -= 1
    return out


def species_vocab(df: pd.DataFrame, min_sheets: int = 40) -> list[str]:
    counts: dict[str, int] = {}
    for sa, sb in zip(df["species_a"], df["species_b"]):
        for s in list(sa) + list(sb):
            counts[s] = counts.get(s, 0) + 1
    return sorted(s for s, c in counts.items() if c >= min_sheets)


class Logit:
    """L2-regularized logistic regression on antisymmetric features, fitted on both
    orientations of every match (so it has no 'player 1' bias and needs no intercept)."""

    def __init__(self, c: float = 1.0, n_shrunk: int = 0, shrink: float = 1.0):
        """The last n_shrunk columns (species) are penalized 1/shrink^2 times harder."""
        self.c, self.n_shrunk, self.shrink = c, n_shrunk, shrink

    def fit(self, x: np.ndarray, y: np.ndarray) -> "Logit":
        from sklearn.linear_model import LogisticRegression
        self.scale_ = np.sqrt((x ** 2).mean(axis=0)) + 1e-9   # antisymmetric: centered at 0 by construction
        if self.n_shrunk:
            self.scale_[-self.n_shrunk:] /= self.shrink
        z = x / self.scale_
        model = LogisticRegression(C=self.c, fit_intercept=False, max_iter=2000)
        model.fit(np.vstack([z, -z]), np.concatenate([y, 1 - y]))
        self.coef_ = model.coef_[0] / self.scale_    # per raw feature unit
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-(x @ self.coef_)))


class Trees:
    """Gradient-boosted trees, fitted on both orientations; predictions averaged over both."""

    def __init__(self, **kw):
        self.kw = {"max_iter": 300, "learning_rate": 0.03, "max_leaf_nodes": 15, "min_samples_leaf": 80,
                   "l2_regularization": 1.0, **kw}

    def fit(self, x: np.ndarray, y: np.ndarray) -> "Trees":
        from sklearn.ensemble import HistGradientBoostingClassifier
        self.model = HistGradientBoostingClassifier(**self.kw, random_state=0)
        self.model.fit(np.vstack([x, -x]), np.concatenate([y, 1 - y]))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        p = self.model.predict_proba(x)[:, 1]
        q = self.model.predict_proba(-x)[:, 1]
        return (p + 1 - q) / 2


def metrics(p: np.ndarray, y: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import roc_auc_score
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "accuracy": float(np.mean((p > 0.5) == (y == 1))),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((p - y) ** 2)),
        "auc": float(roc_auc_score(y, p)),
    }


def time_split(df: pd.DataFrame, test_share: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks: older tournaments train, the newest test_share of tournaments test."""
    order = df.groupby("tournament")["date"].first().sort_values(kind="stable")
    n_test = max(1, round(len(order) * test_share))
    test_t = set(order.index[-n_test:])
    test = df["tournament"].isin(test_t).to_numpy()
    return ~test, test


def forward_cv(df: pd.DataFrame, make_x, make_model, folds: int = 3) -> float:
    """Mean log loss over forward-chaining folds inside df (train older, validate next)."""
    order = df.groupby("tournament")["date"].first().sort_values(kind="stable").index.tolist()
    chunk = len(order) // (folds + 1)
    losses = []
    for f in range(1, folds + 1):
        tr = df["tournament"].isin(order[:chunk * f]).to_numpy()
        va = df["tournament"].isin(order[chunk * f: chunk * (f + 1)]).to_numpy()
        x_tr, x_va = make_x(df[tr], df), make_x(df[va], df)
        model = make_model().fit(x_tr, df["won"].to_numpy()[tr].astype(float))
        losses.append(metrics(model.predict(x_va), df["won"].to_numpy()[va].astype(float))["log_loss"])
    return float(np.mean(losses))


# --------------------------------------------------------------------------
# Training, evaluation and export
# --------------------------------------------------------------------------
FEATURES = MATCHUP + CONTEXT + SUPPORT + INTERACT   # what the app can know about two teams
TOLERANCE = 0.0005  # per-Pokemon effects must beat the simpler model by this much CV log loss


def _design(part: pd.DataFrame, vocab: list[str], features: list[str]) -> np.ndarray:
    if not vocab:
        return part[features].to_numpy(float)
    return np.hstack([part[features].to_numpy(float), species_matrix(part, vocab)])


def _bootstrap_gain(loss_base: np.ndarray, loss_new: np.ndarray, n: int = 2000, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    d = loss_base - loss_new
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]


def _losses(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _choose(train: pd.DataFrame, features: list[str], vocab: list[str]) -> tuple[float, float, float]:
    """(cv log loss, C, shrink) by forward-chaining CV inside the training period."""
    best = None
    for c in (0.0003, 0.001, 0.003, 0.01):
        for w in ((0.3, 0.5) if vocab else (1.0,)):
            cv = forward_cv(train, lambda part, full: _design(part, vocab, features),
                            lambda c=c, w=w: Logit(c, len(vocab), w))
            if best is None or cv < best[0]:
                best = (cv, c, w)
    return best


def train_and_report(regulation: str = "regmc", format_id: str = "gen9championsvgc2026regmc",
                     boot: int = 200, verbose: bool = True) -> dict:
    """
    Fits P(player 1 wins) from team features *and* player skill (Elo before the match),
    so team effects are measured between equally rated players. The app predicts with
    skill set to equal, i.e. "your team vs theirs, same players".
    """
    df = add_skill(build_dataset(regulation, format_id, verbose=verbose), regulation)
    y = df["won"].to_numpy(float)
    tr, te = time_split(df)
    train = df[tr]
    features = SKILL + FEATURES

    # 1. settings and whether per-Pokemon effects earn their place, on the training period only
    plain = _choose(train, features, [])
    vocab_tr = species_vocab(train, 40)
    with_sp = _choose(train, features, vocab_tr)
    use_species = with_sp[0] < plain[0] - TOLERANCE
    cv, c, w = with_sp if use_species else plain
    vocab = vocab_tr if use_species else []
    if verbose:
        print(f"CV log loss: without Pokémon effects {plain[0]:.5f}, with {with_sp[0]:.5f} -> "
              f"{'with' if use_species else 'without'}; C={c}", flush=True)

    # 2. judge on the newest tournaments against simpler models
    def fit_predict(cols, voc, c_, w_):
        m = Logit(c_, len(voc), w_).fit(_design(train, voc, cols), y[tr])
        return m.predict(_design(df[te], voc, cols))

    yt = y[te]
    preds = {
        "learned model (skill + team)": fit_predict(features, vocab, c, w),
        "player skill only": fit_predict(SKILL, [], _choose(train, SKILL, [])[1], 1.0),
        "team only": fit_predict(FEATURES, [], _choose(train, FEATURES, [])[1], 1.0),
        "damage-calc matchup score": fit_predict(["matchup score"], [], c, 1.0),
        "popularity only": fit_predict(["popularity"], [], c, 1.0),
    }
    models = {name: {k: round(v, 4) for k, v in metrics(p, yt).items()} for name, p in preds.items()}
    models["coin flip"] = {"accuracy": 0.5, "log_loss": round(math.log(2), 4), "brier": 0.25, "auc": 0.5}
    main = preds["learned model (skill + team)"]
    gains = {
        "team beyond skill": _bootstrap_gain(_losses(preds["player skill only"], yt), _losses(main, yt)),
        "learned vs damage-calc score": _bootstrap_gain(_losses(preds["damage-calc matchup score"], yt),
                                                        _losses(main, yt)),
    }
    order = np.argsort(main)
    calibration = [{"predicted": round(float(main[i].mean()), 3), "actual": round(float(yt[i].mean()), 3),
                    "matches": int(len(i))} for i in np.array_split(order, 5)]

    # 3. refit on everything for the app, with tournament-level bootstrap intervals
    vocab_all = species_vocab(df, 40) if use_species else []
    x_all = _design(df, vocab_all, features)
    full = Logit(c, len(vocab_all), w).fit(x_all, y)
    tournaments = df["tournament"].unique()
    rng = np.random.default_rng(1)
    rows_by_t = {t: np.flatnonzero(df["tournament"].to_numpy() == t) for t in tournaments}
    draws = []
    for _ in range(boot):
        pick = rng.choice(tournaments, len(tournaments))
        idx = np.concatenate([rows_by_t[t] for t in pick])
        draws.append(Logit(c, len(vocab_all), w).fit(x_all[idx], y[idx]).coef_)
    draws = np.array(draws)
    lo, hi = np.percentile(draws, 5, axis=0), np.percentile(draws, 95, axis=0)
    names = features + [f"species: {s}" for s in vocab_all]
    share = (x_all != 0).mean(axis=0)
    effects = [{"feature": n, "coef": round(float(b), 5), "lo90": round(float(a), 5), "hi90": round(float(z), 5),
                "points": round(float(b) * 25, 2), "differs_in": round(float(sh), 4)}
               for n, b, a, z, sh in zip(names, full.coef_, lo, hi, share)]

    from src.ratings import K_BASE, NEW_BOOST
    return {
        "regulation": regulation, "matches": int(len(df)), "train_matches": int(tr.sum()),
        "test_matches": int(te.sum()),
        "test_dates": [str(df[te]["date"].min()), str(df[te]["date"].max())],
        "settings": {"C": c, "shrink": w, "cv_log_loss": round(cv, 5), "species_effects": use_species,
                     "cv_without_species": round(plain[0], 5), "cv_with_species": round(with_sp[0], 5),
                     "elo_k": K_BASE, "elo_new_boost": NEW_BOOST},
        "test": models, "gain_ci95": {k: [round(g, 5) for g in v] for k, v in gains.items()},
        "calibration": calibration,
        "model": {"features": features, "species": vocab_all, "coef": [round(float(b), 6) for b in full.coef_]},
        "effects": effects,
    }


# --------------------------------------------------------------------------
# Predicting a matchup in the app
# --------------------------------------------------------------------------
def load_model(regulation: str) -> dict | None:
    path = EVAL_DIR / f"{regulation}_match_model.json"
    return json.loads(path.read_text()) if path.exists() else None


def team_side(members: list[Member], sets, dex: Dex, usage, engine: SwapEngine | None,
              meta: float | None = None) -> dict:
    """What the model needs about one team, computed once per team."""
    return {
        "members": members,
        "profile": side_profile(members),
        "meta": meta if meta is not None else (engine.overall(sets) if engine is not None else 0.0),
        "popularity": float(np.mean([usage.species_usage(p.species, dex) for p in sets])) if sets else 0.0,
        "species": sorted({dex.sheet_id(s) for p in sets if (s := dex.get_species(p.species))}),
    }


GROUPS = {"Damage calcs": ["matchup score", "bring-4 score", "best damage (mean %)", "OHKOs", "2HKOs"],
          "Speed": ["outspeeds (share)", "base speed (mean)", "Trick Room x slow team", "Tailwind x fast team"],
          "Bulk": ["bulk (mean)"], "Strength vs the meta": ["score vs meta", "popularity", "has Mega"]}


def predict_match(model: dict, a: dict, b: dict, parts: dict | None = None) -> float:
    """P(team a beats team b) from the learned model."""
    return 1 / (1 + math.exp(-sum(c for _, c in contributions(model, a, b, parts))))


def contributions(model: dict, a: dict, b: dict, parts: dict | None = None) -> list[tuple[str, float]]:
    """Each feature's push on the log-odds that a wins (positive = toward a)."""
    m = model["model"]
    row = matchup_features(parts if parts is not None else pair_parts(a["members"], b["members"]),
                           a["members"], b["members"])
    row["skill (Elo)"] = row["experience"] = 0.0   # the app compares teams, not players
    row["score vs meta"] = a["meta"] - b["meta"]
    row["popularity"] = (a["popularity"] - b["popularity"]) / 10
    for k in a["profile"]:
        row[k] = a["profile"][k] - b["profile"][k]
    x = [row.get(f, 0.0) for f in m["features"]]
    index = {s: i for i, s in enumerate(m["species"])}
    sp = [0.0] * len(index)
    for s in a["species"]:
        if s in index:
            sp[index[s]] += 1
    for s in b["species"]:
        if s in index:
            sp[index[s]] -= 1
    names = m["features"] + [f"species: {s}" for s in m["species"]]
    return [(n, float(c) * v) for n, c, v in zip(names, m["coef"], x + sp) if v]


def explain(model: dict, a: dict, b: dict, parts: dict | None = None, top: int = 3) -> tuple[list, list]:
    """The biggest reasons for and against team a, in win-percentage points (grouped, readable)."""
    species_name = {}
    grouped: dict[str, float] = {}
    for name, c in contributions(model, a, b, parts):
        group = next((g for g, fs in GROUPS.items() if name in fs), None)
        if group is None and name.startswith("tool: "):
            group = name[len("tool: "):]
        elif group is None and name.startswith("species: "):
            group = "Pokémon picks"
            species_name[name] = c
        grouped[group or name] = grouped.get(group or name, 0.0) + c
    points = {g: 25 * c for g, c in grouped.items() if abs(25 * c) >= 0.5}
    pros = sorted(((g, v) for g, v in points.items() if v > 0), key=lambda kv: -kv[1])[:top]
    cons = sorted(((g, v) for g, v in points.items() if v < 0), key=lambda kv: kv[1])[:top]
    return pros, cons


if __name__ == "__main__":
    report = train_and_report()
    out = EVAL_DIR / f"{report['regulation']}_match_model.json"
    out.write_text(json.dumps(report, indent=1))
    for name, r in report["test"].items():
        print(f"{name:30s} acc {r['accuracy']:.3f}  log loss {r['log_loss']:.4f}  auc {r['auc']:.3f}")
    print("log-loss gains (95% CI):", report["gain_ci95"])
    print(f"-> {out}")
