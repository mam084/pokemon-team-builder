#!/usr/bin/env python3
"""
update_readme.py

Rewrites the README's result tables from data/evaluation/*.json, between
<!-- generated:NAME --> and <!-- /generated:NAME --> markers, so the numbers
stay in step with the monthly refresh. Run after the evaluations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EVAL = ROOT / "data" / "evaluation"


def load(name: str) -> dict | None:
    path = EVAL / name
    return json.loads(path.read_text()) if path.exists() else None


def recommender(r: dict) -> str:
    res = r["results"]
    rows = "\n".join(
        f"| {name} | {m['hit@1']:.1%} | {m['hit@5']:.1%} | {m['hit@10']:.1%} | {m['mrr']:.3f} |"
        for name, m in res.items())
    t, h = res["tuned weights"], res["hand-set weights"]
    pairs = (f"Synergy learned tournament pairings from the {r['pairing_teams']:,} oldest teams and the "
             f"weights were tuned by grid search on the next {r['train_teams']:,}"
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
    t, g = r["test"], r["gain_ci95"]
    rows = "\n".join(f"| {name} | {v['accuracy']:.1%} | {v['log_loss']:.4f} | {v['auc']:.3f} |"
                     for name, v in t.items())
    return f"""chosen by forward-chaining cross-validation inside the older {r['train_matches']:,}
matches, and it's tested once on the newest {r['test_matches']:,}
({r['test_dates'][0]} to {r['test_dates'][1]}):

| model | picks the winner | log loss | AUC |
|---|---|---|---|
{rows}

- **Who's playing matters most**, but the team adds real signal on top: log-loss
  gain {g['team beyond skill'][0]:+.4f} to {g['team beyond skill'][1]:+.4f} over ratings alone (95% paired bootstrap)."""


def bring(r: dict) -> str:
    res = r["results"]
    names = {"learned": "learned bring / lead model", "usual picks": "players' usual picks (bring / lead rates)",
             "damage calcs": "damage-calc game plan", "random": "random"}
    rows = "\n".join(f"| {label} | {res['bring'][k][0]:.1%} | {res['lead'][k][0]:.1%} |" for k, label in names.items())
    return (f"{r['replays']:,} replays; tested on {r['test_sides']:,} team previews.\n\n"
            "| | bring-4 | lead pair |\n|---|---|---|\n" + rows)


def replace(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- generated:{name} -->\n).*?(\n<!-- /generated:{name} -->)", re.S)
    if not pattern.search(text):
        print(f"no markers for {name}")
        return text
    return pattern.sub(lambda m: m.group(1) + body + m.group(2), text)


def main() -> None:
    text = README.read_text()
    for name, fn, file in (("recommender", recommender, "regmc.json"),
                           ("validation", validation, "regmc_matches.json"),
                           ("learned", learned, "regmc_match_model.json"),
                           ("bring", bring, "regmc_bring_model.json")):
        data = load(file)
        if data:
            text = replace(text, name, fn(data))
    README.write_text(text)


if __name__ == "__main__":
    main()
