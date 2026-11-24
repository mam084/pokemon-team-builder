# Pokémon Champions Team Builder

[![Tests](https://github.com/mam084/pokemon-team-builder/actions/workflows/tests.yml/badge.svg)](https://github.com/mam084/pokemon-team-builder/actions/workflows/tests.yml)
[![Refresh data](https://github.com/mam084/pokemon-team-builder/actions/workflows/refresh-data.yml/badge.svg)](https://github.com/mam084/pokemon-team-builder/actions/workflows/refresh-data.yml)

A team builder for **Pokémon Champions** VGC (Reg M-C, plus Battle Stadium Singles) that learns from real
results. It checks your team against the regulation, scores it against the meta with real damage calcs, finds
swaps that fix your worst matchups, and plans the game against the six you're facing. Every model it ships is
tested on newer matches it never saw, and the app says how much each number can be trusted.

![Defensive matchup heatmap and role checklist](docs/screenshot.png)

## What it does

- **Build a legal team** from the regulation's real pool, with Champions rules (level 50, 66 Stat Points),
  one-click popular sets, Showdown paste import/export, and the whole team kept in the page link.
- **Analyze it**: defensive heatmap, role checklist, speed tiers and offensive coverage.
- **Matchups vs the meta**: about 10 meta teams rebuilt from teammate data, every pairing decided by damage
  calcs in both directions, a learned win chance, the biggest threats, and swaps that fix them.
- **Recommendations** in three styles: Popular picks, Neutral, and **Hidden gems** (unusual picks that win
  more than their players' ratings predict).
- **Battle plan and Playbook**: what to bring and lead against a team, and what wins against Trick Room,
  Tailwind, weather and setup.

Full tour: [docs/features.md](docs/features.md).

## Results at a glance

<!-- generated:summary -->
Newest held-out data (2026-11-17 to 2026-11-23); the model never saw it.

| held-out test | model | baseline | tested on |
|---|---|---|---|
| Recommender: find the missing member of a real tournament team (MRR) | 0.647 | 0.210 (popularity only) | 1,682 teams |
| Win model: pick the winner of a real match | 58.0% | 57.6% (ratings only) | 3,877 matches |
| Teams alone (no ratings): pick the winner | 52.6% | 50.0% (coin flip) | 3,877 matches |
| Bring model: predict the 4 a player brings | 72.0% | 70.7% (usual picks) | 19,876 team previews |

On the newest matches, the team's extra signal on top of the players' ratings is too small to tell apart from zero (log-loss gain -0.0000 to +0.0061 over ratings alone, 95% paired bootstrap). Treat team-vs-team win chances as a rough guide.
<!-- /generated:summary -->

The honest headline: **the player decides most games.** Team composition adds only a few points of edge, so
the app shows win chances as a guide rather than a verdict. The full write-up, including the ideas that were
tested and rejected, is in [docs/experiments.md](docs/experiments.md).

## How it works

- **Data** refreshes itself: Showdown's legal pool, Smogon usage stats, Limitless tournament team lists, and
  about 1,300 ladder replays a day, pulled by GitHub Actions ([docs/data.md](docs/data.md)).
- **Models**: a team-aware recommender with tuned weights, a learned teammate model, a logistic-regression win
  model with leak-free Elo ratings, and a learned bring/lead model, each retrained on schedule.
- **Guard rails**: a weekly health check re-reads every held-out evaluation and opens an issue when a shipped
  model stops beating its baseline; result tables in this README are regenerated from those evaluations.
- **Errors**: a tab that breaks shows the visitor a short message instead of a traceback; with a
  `github_token` in the app's secrets it also opens an `app-error` issue (src/error_report.py).

## Run it

```bash
git clone https://github.com/mam084/pokemon-team-builder.git
cd pokemon-team-builder
pip install -r requirements.txt
streamlit run app.py          # data for every supported format is included
```

Click **Example team** in the sidebar to load a Garganacl team for Reg M-C.
The app has light and dark themes. It follows your device setting by default,
and you can switch in the top-right menu under Settings. Charts change colors
to match.

To rebuild the data yourself:

```bash
# legal dex (needs Node 22 and a built Showdown checkout)
git clone --depth 1 https://github.com/smogon/pokemon-showdown.git ../pokemon-showdown
(cd ../pokemon-showdown && npm ci && node build)
node scripts/export_dex.js --ps ../pokemon-showdown --out data/dex

# usage stats (newest published month, or pass --month YYYY-MM)
python scripts/fetch_usage.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests check:
- the hand-written type chart against Showdown's exported chart, matchup by matchup
- the Champions stat formula, including nature rounding, and the Stat Point limits
- paste import and export round-trips, including Megas named directly in a paste
- every legality rule
- the damage calculator, roll-for-roll against Showdown's engine, and the weight- and
  Speed-based power rules against Showdown's own code
- chaos-file parsing (using a fixture in Smogon's real layout)
- the analysis views, matchups, threats, recommender and evaluation harness
- the app itself, driven headlessly through adding, removing, presets and format
  changes

## Project structure

```
├── app.py                    page layout only
├── ui/                       one module per tab, plus shared state and helpers
├── src/
│   ├── formats.py            supported formats (regulation, singles/doubles, pick count)
│   ├── dex.py                legal-data loader: species, Mega forms, items, learnsets
│   ├── stats.py              Champions stat formula and Stat Point rules
│   ├── team.py               PokemonSet / team model
│   ├── paste.py              Showdown paste import and export
│   ├── share.py              team <-> compressed URL token for links
│   ├── legality.py           regulation checks
│   ├── type_chart.py         type effectiveness plus abilities that change matchups
│   ├── usage.py              Smogon chaos parsing, popular sets, team-sheet merging of Megas
│   ├── replay_usage.py       usage built from replays, for a new regulation before Smogon's stats
│   ├── analysis.py           type matchups, coverage, role checklist, speed tiers
│   ├── damage.py             damage calculator (Showdown-exact)
│   ├── presets.py            common sets assembled from usage stats
│   ├── roles.py              role tags for meta Pokémon and for your sets
│   ├── matchup.py            meta teams, damage-based pair scores, bring-N, counters, threats
│   ├── recommend.py          explainable multi-signal recommender with popularity modes
│   ├── plan.py               weather / Trick Room / Tailwind / terrain synergy
│   ├── builder.py            build three full teams around one Pokémon
│   ├── core_report.py        what players do with one Pokémon: replays, tournaments, calcs, team styles
│   ├── sheet_sets.py         whole sets from real team sheets (Bo3 open sheets, tournaments)
│   ├── setup.py              what one setup move buys: calcs and Speed after Dragon Dance etc.
│   ├── playbook.py           how to play against Trick Room, Tailwind, weather...: replays and your tools
│   ├── swaps.py              swap suggestions (best upgrade / most similar per member)
│   ├── gameplan.py           per-matchup game plan: bring, leads, threats, Speed order
│   ├── cooccurrence.py       tournament team pairings as a second synergy source
│   ├── evaluate.py           hide-one-member evaluation on real tournament teams
│   ├── validate.py           does the matchup score predict real match winners?
│   ├── match_model.py        learned win-chance model from real matches, with trust bounds
│   ├── evidence.py           what the held-out numbers support, worded the same in the app, README and health check
│   ├── team_rating.py        team rating vs real tournament teams; builds the trust bounds
│   ├── team_check.py         held-out team ranking and swap-search check (trust bounds)
│   ├── ratings.py            leak-free Elo ratings for tournament players
│   ├── replay_parse.py       Showdown battle log -> compact record
│   ├── replays.py            replay stats; does the game plan match real choices?
│   └── bring_model.py        learned bring-4 / lead model from replays
├── scripts/                  what the app and the scheduled workflows run
│   ├── export_dex.js         Showdown → data/dex
│   ├── fetch_usage.py        Smogon → data/usage
│   ├── fetch_tournaments.py  Limitless → data/tournaments
│   ├── fetch_replays.py      Showdown replays → data/replays (twice a day)
│   ├── evaluate.py           runs the evaluation → data/evaluation
│   ├── update_readme.py      rewrites the result tables in README.md and docs/experiments.md
│   ├── health_check.py       weekly: shipped models still beat their baselines; data is fresh
│   ├── new_regulation.py     notice a new regulation on Showdown; switch src/formats.py to it
│   ├── load_test.py          several visitors at once against a running app
│   ├── keep_awake.py         visits the live app every 6 hours so Community Cloud doesn't put it to sleep
│   └── ...
├── labs/                     one-off experiments behind each design decision (see docs/experiments.md)
├── docs/                     features, experiments and the data pipeline in full
├── data/                     generated data (committed so the app runs without setup)
├── tests/                    unittest suite and fixtures
└── .github/workflows/        tests and the monthly data refresh
```

## Roadmap

- [x] Stage 1: dashboard with type coverage and stat comparison (original PokéAPI version)
- [x] Stage 2: Smogon usage data and teammate co-occurrence
- [x] Stage 3: team-aware recommender
- [x] **Stage 4: Champions rebuild**: regulation-accurate legality, Stat Points,
  Megas, an automated data pipeline, threat analysis, and a multi-signal
  explainable recommender
- [x] Presets, role tags, and team-vs-meta matchups with bring-N and counter picks
- [x] Damage calculator verified against Showdown; damage-based matchups and threats
- [x] Evaluation on real tournament teams, with tuned weights and baselines
- [x] Matchup score validated on real match results, shown as a calibrated win chance
- [x] Game plans per matchup; tournament pairings in the synergy signal
- [x] Learned win-chance model (support tools, Pokémon effects) from 12,000 real matches
- [x] Learned teammate model (whole-team synergy from tournament and ladder teams), measured with the same evaluation
- [x] Deploy to Streamlit Community Cloud
- [x] Trust bounds: the swap search can't rate a team past the best real tournament team
- [x] Swaps judged by team score (fit + win chance), plus a plain-word team grade