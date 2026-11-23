#!/usr/bin/env python3
"""
update_readme.py

Rewrites the result tables in README.md and docs/experiments.md from data/evaluation/*.json, between
<!-- generated:NAME --> and <!-- /generated:NAME --> markers, so the numbers
stay in step with the monthly refresh. Run after the evaluations.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EVAL = ROOT / "data" / "evaluation"
sys.path.insert(0, str(ROOT))


def load(name: str) -> dict | None:
    path = EVAL / name
    return json.loads(path.read_text()) if path.exists() else None


def recommender(r: dict) -> str:
    res = r["results"]
    rows = "\n".join(
        f"| {name} | {m['hit@1']:.1%} | {m['hit@5']:.1%} | {m['hit@10']:.1%} | {m['mrr']:.3f} |"
        for name, m in res.items())
    t, h = res["tuned weights"], res["hand-set weights"]
    pairs = (f"The teammate model learned from the {r['pairing_teams']:,} oldest teams (plus replays from "
             f"before the next tournaments) and the weights were tuned by grid search on the next "
             f"{r['train_teams']:,}"
             if r.get("pairing_teams") else
             f"The weights were tuned by grid search on {r['train_teams']:,} teams from the older tournaments")
    return f"""Tournaments are split by date. {pairs}. Every number below comes from
{r['test_teams']:,} teams in the {r['test_tournaments']} newest tournaments ({r['test_dates'][0]} to
{r['test_dates'][1]}), which neither ever saw.

| model | top 1 | top 5 | top 10 | MRR |
|---|---|---|---|---|
{rows}

- The tuned weights find the missing Pokémon **first try {t['hit@1']:.0%} of the
  time** and in the top 10 {t['hit@10']:.0%} of the time: {t['mrr'] / h['mrr'] - 1:.0%} better MRR than the
  weights the recommender originally shipped with."""


def validation(r: dict) -> str:
    m = r["models"]
    cal = m["team vs team (all 6)"]["calibration"]
    rows = "\n".join(f"| {name} | {v['accuracy']:.1%} | {v['log_loss']:.4f} |" for name, v in m.items())
    return f"""`src/validate.py` checks that score against **{r['matches']:,} real Limitless
matches** where both players' team lists are known: each pair of teams is
scored against each other, a win-chance curve is fitted on the older
{r['fit_matches']:,} matches, and it's judged on the newest {r['test_matches']:,}
({r['test_dates'][0]} to {r['test_dates'][1]}).

| model | picks the winner | log loss |
|---|---|---|
{rows}

Split into fifths by score, the side the model favors most strongly won
**{cal[-1]['actual']:.0%}** and the side it disfavors most strongly
**{cal[0]['actual']:.0%}**, close to the fitted curve
({cal[-1]['predicted']:.0%} / {cal[0]['predicted']:.0%})."""


def learned(r: dict) -> str:
    from src.evidence import team_signal_sentence
    t = r["test"]
    rows = "\n".join(f"| {name} | {v['accuracy']:.1%} | {v['log_loss']:.4f} | {v['auc']:.3f} |"
                     for name, v in t.items())
    return f"""chosen by forward-chaining cross-validation inside the older {r['train_matches']:,}
matches, and it's tested once on the newest {r['test_matches']:,}
({r['test_dates'][0]} to {r['test_dates'][1]}):

| model | picks the winner | log loss | AUC |
|---|---|---|---|
{rows}

- **Who's playing matters most.** {team_signal_sentence(r)}"""


def bring(r: dict) -> str:
    res = r["results"]
    names = {"learned": "learned bring / lead model", "usual picks": "players' usual picks (bring / lead rates)",
             "damage calcs": "damage-calc game plan", "random": "random"}
    rows = "\n".join(f"| {label} | {res['bring'][k][0]:.1%} | {res['lead'][k][0]:.1%} |" for k, label in names.items())
    return (f"{r['replays']:,} replays; tested on {r['test_sides']:,} team previews.\n\n"
            "| | bring-4 | lead pair |\n|---|---|---|\n" + rows)


def team_check(r: dict) -> str:
    raw, guarded = r["ranking"]["without bounds"], r["ranking"]["with bounds"]
    names = ["lowest quarter", "2nd quarter", "3rd quarter", "highest quarter"]
    rows = "\n".join(f"| {n} | {a['predicted']:.1%} | {a['actual']:.1%} | {b['predicted']:.1%} | {b['actual']:.1%} |"
                     for n, a, b in zip(names, raw["quarters"], guarded["quarters"]))
    search = "\n".join(f"| {s['start']} | {s['without bounds']['to']:.1%} | {s['with bounds']['to']:.1%} |"
                        for s in r["search"])
    o = r.get("objective")
    objective = ""
    if o:
        oq = "\n".join(f"| {n} | {a['actual']:.1%} | {b['actual']:.1%} |"
                       for n, a, b in zip(names, o["win chance"]["quarters"], o["team score"]["quarters"]))
        climbs = "\n".join(f"| {s['start']} | {s['team score']['from']} → {s['team score']['to']} | "
                           f"{s['team score']['win']:.1%} | {s['team score']['real_5of6']} |"
                           for s in r["search"] if "team score" in s)
        objective = f"""

**What swaps are judged by.** Ranking the same {o['teams']:,} held-out teams by **team score** (teammate fit
plus win chance, `src/team_rating.py`) vs **win chance alone**, with the teammate model also fitted before
{r['cut']}:

| teams, by | win chance alone: won | team score: won |
|---|---|---|
{oq}

Rank correlation with real records: {o['win chance']['spearman']:.3f} by win chance, {o['team score']['spearman']:.3f}
by team score (paired 95% interval for the gain: {o['gain_ci'][0]:+.3f} to {o['gain_ci'][1]:+.3f}). So swaps are judged by
team score. Keep applying the best swap that way (any role, bounds on):

| start | team score | win chance at the end | real teams sharing 5+ of its six |
|---|---|---|---|
{climbs}"""
    lo = min(s["without bounds"]["to"] for s in r["search"])
    hi = max(s["without bounds"]["to"] for s in r["search"])
    return f"""Fitted on data before {r['cut']}; bounds from {r['reference_teams']:,} real teams from before then
(the best scores {r['best_real_team']:.1%} vs the meta). **Ranking the {r['held_out_teams']:,} held-out teams**
by win chance vs the meta, then checking how they actually did:

| teams, by win chance | without bounds: said | won | with bounds: said | won |
|---|---|---|---|---|
{rows}

Rank correlation with real records: {raw['spearman']:.3f} without bounds, {guarded['spearman']:.3f} with. The
bounds moved {r['changed_share']:.1%} of real teams by more than 0.1 points.

**Keep applying the best swap** (Neutral, any role) from the most popular meta teams:

| start | ends at, without bounds | with bounds |
|---|---|---|
{search}

Without bounds the search walks to {lo:.0%}-{hi:.0%}, past every real team; with them it stops at the best
real team's score.{objective}"""


def replace(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- generated:{name} -->\n).*?(\n<!-- /generated:{name} -->)", re.S)
    if not pattern.search(text):
        print(f"no markers for {name}")
        return text
    return pattern.sub(lambda m: m.group(1) + body + m.group(2), text)


def summary(reg: str) -> str | None:
    """The README's short table: one line per shipped model, from the same evaluation files."""
    from src.evidence import team_signal_sentence
    rec, mm, bm = load(f"{reg}.json"), load(f"{reg}_match_model.json"), load(f"{reg}_bring_model.json")
    rows = []
    if rec:
        r = rec["results"]
        rows.append(f"| Recommender: find the missing member of a real tournament team (MRR) | "
                    f"{r['tuned weights']['mrr']:.3f} | {r['popularity only']['mrr']:.3f} (popularity only) | "
                    f"{rec['test_teams']:,} teams |")
    if mm:
        t = mm["test"]
        rows.append(f"| Win model: pick the winner of a real match | "
                    f"{t['learned model (skill + team)']['accuracy']:.1%} | "
                    f"{t['player skill only']['accuracy']:.1%} (ratings only) | {mm['test_matches']:,} matches |")
        rows.append(f"| Teams alone (no ratings): pick the winner | {t['team only']['accuracy']:.1%} | 50.0% (coin flip) | "
                    f"{mm['test_matches']:,} matches |")
    if bm:
        b = bm["results"]["bring"]
        rows.append(f"| Bring model: predict the 4 a player brings | {b['learned'][0]:.1%} | "
                    f"{b['usual picks'][0]:.1%} (usual picks) | {bm['test_sides']:,} team previews |")
    if not rows:
        return None
    dates = f" ({mm['test_dates'][0]} to {mm['test_dates'][1]})" if mm else ""
    table = ("| held-out test | model | baseline | tested on |\n|---|---|---|---|\n" + "\n".join(rows))
    note = team_signal_sentence(mm)
    return f"Newest held-out data{dates}; the model never saw it.\n\n{table}" + (f"\n\n{note}" if note else "")


FILES = [README, ROOT / "docs" / "experiments.md"]


def render() -> dict[Path, str]:
    """Every file with its generated blocks rewritten (nothing written)."""
    from src.formats import CURRENT
    reg = CURRENT.regulation
    blocks = {}
    for name, fn, file in (("recommender", recommender, f"{reg}.json"),
                           ("validation", validation, f"{reg}_matches.json"),
                           ("learned", learned, f"{reg}_match_model.json"),
                           ("bring", bring, f"{reg}_bring_model.json"),
                           ("teamcheck", team_check, f"{reg}_team_check.json")):
        data = load(file)
        if data:
            blocks[name] = fn(data)
    s = summary(reg)
    if s:
        blocks["summary"] = s
    out = {}
    for path in FILES:
        if not path.exists():
            continue
        text = path.read_text()
        for name, body in blocks.items():
            if f"<!-- generated:{name} -->" in text:
                text = replace(text, name, body)
        out[path] = text
    return out


def main() -> int:
    """Rewrite the tables; with --check, only report whether any file is out of date (exit 1 if so)."""
    rendered = render()
    stale = [p for p, text in rendered.items() if p.read_text() != text]
    if "--check" in sys.argv:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)} (run python scripts/update_readme.py)")
        return 1 if stale else 0
    for p in stale:
        p.write_text(rendered[p])
    return 0


if __name__ == "__main__":
    sys.exit(main())
