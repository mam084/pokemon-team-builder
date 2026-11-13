# Pokémon Champions Team Builder

[![Tests](https://github.com/mam084/pokemon-team-builder/actions/workflows/tests.yml/badge.svg)](https://github.com/mam084/pokemon-team-builder/actions/workflows/tests.yml)
[![Refresh data](https://github.com/mam084/pokemon-team-builder/actions/workflows/refresh-data.yml/badge.svg)](https://github.com/mam084/pokemon-team-builder/actions/workflows/refresh-data.yml)

A team builder and analyzer for **Pokémon Champions**, built for the current
regulation (VGC 2026 Reg M-C and Battle Stadium Singles M-C, with Reg M-B kept
for reference). You build full competitive sets, the app checks them against the
regulation's rules, and then it measures the team against what people actually
play on the ladder.

![Defensive matchup heatmap and role checklist](docs/screenshot.png)

## What it does

**Build a legal team**
- Every Pokémon, Mega Stone, item, ability and move list comes from the
  regulation's legal pool. Pokémon, items and moves are sorted by real usage,
  with each one's usage % shown.
- The editor uses Champions rules: level 50, **66 Stat Points with at most 32
  per stat**, and real level-50 stats for each nature. Mega Pokémon show their Mega
  stats, types and ability.
- When you pick a Pokémon, the app can fill in its most-used set (item, ability,
  spread and moves). It skips items your team already holds, so Item Clause
  is never broken.
- Legality checks cover Species Clause, Item Clause, illegal moves and abilities,
  and Stat Point limits. You also get a warning when more than one Pokémon holds
  a Mega Stone, since only one can Mega Evolve per battle.
- Import and export Showdown pastes.

**Analyze it**
- **Defensive heatmap** shows how much damage each type does to each member.
  It uses the Mega forms and accounts for abilities that change type matchups
  (Levitate, Purifying Salt, Thick Fat, Water Absorb…). Shared weaknesses are
  flagged.
- **Role checklist**: speed control, Fake Out, Protect, Intimidate, redirection,
  Wide Guard, pivoting, spread damage, weather/terrain, disruption and recovery.
  The doubles-only roles are hidden in Singles.
- **Speed tiers** compare your real Speed stats with the meta's most common
  spreads. There's also a Trick Room view.
- **Offensive coverage** shows what your moves hit super effectively, by type and
  against the 30 most-used Pokémon in their usual battle form.

**Find what's missing**
- **Recommendations**: every candidate gets five scores from 0 to 1, and you can
  change how much each one counts:

  | signal | meaning |
  |---|---|
  | synergy | how much more often it appears next to your members than chance predicts. This is the mean log-lift from teammate stats, P(B\|A) / P(B) |
  | defense | how well it resists the types your team is weak to |
  | offense | how well it hits popular Pokémon your team can't hit super effectively (weighted by usage) |
  | roles | whether it brings a role your team is missing |
  | meta | its overall usage, as a prior |

  Each pick also gets a written reason, e.g. *"5.0x more common than usual next to
  Garganacl; resists Water, Grass, Ground"*.
- **Threats** ranks popular Pokémon by `usage × (members hit super effectively + 1) ÷ (answers + 1)`.
  An *answer* is a member that takes neutral or less from every type the threat
  usually attacks with, and that hits it super effectively back.
- **Meta explorer**: the usage leaderboard and each Pokémon's moves, items,
  abilities, spreads, teammates, and checks & counters.

## Data

| What | Source | How it gets here |
|---|---|---|
| Legal Pokémon, Megas, movepools, items, abilities, type chart | [Pokémon Showdown](https://github.com/smogon/pokemon-showdown)'s `champions` mod, the same code that validates teams on the ladder | `scripts/export_dex.js` → `data/dex/<regulation>.json` |
| Usage, sets, teammates, checks & counters | [Smogon monthly usage stats](https://www.smogon.com/stats/) (`chaos` JSON, 1630+ rating) | `scripts/fetch_usage.py` → `data/usage/<format>.json` |

The **Refresh data** GitHub Action rebuilds both on the 3rd of every month,
after Smogon publishes the previous month's stats. It also runs whenever the
data scripts change, and you can start it by hand from the Actions tab. If
anything changed, it commits the new data. So when a new regulation launches,
the only code change is adding it to `src/formats.py` and `scripts/export_dex.js`.

A few things to know about the data:
- Smogon lists each Mega under its own name ("Charizard-Mega-Y"), because that's
  the form that battles. Team sheets list the base Pokémon plus its stone, so the
  app merges the two views (`UsageData.variants`).
- Teammate % is P(B on team | A on team), so it isn't symmetric. The recommender
  uses *lift* so that Pokémon that are just popular everywhere don't dominate the
  results.
- The type analysis doesn't calculate damage. It models types and the abilities
  that change type matchups, but not items, stat boosts or field effects.

## Run it

```bash
git clone https://github.com/mam084/pokemon-team-builder.git
cd pokemon-team-builder
pip install -r requirements.txt
streamlit run app.py          # data for every supported format is included
```

Click **Example team** in the sidebar to load a Garganacl team for Reg M-C.

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
- chaos-file parsing (using a fixture in Smogon's real layout)
- the analysis views, threat logic and recommender

CI runs the tests and a check that the app starts.

## Project structure

```
├── app.py                    Streamlit UI
├── src/
│   ├── formats.py            supported formats (regulation, singles/doubles, pick count)
│   ├── dex.py                legal-data loader: species, Mega forms, items, learnsets
│   ├── stats.py              Champions stat formula and Stat Point rules
│   ├── team.py               PokemonSet / team model
│   ├── paste.py              Showdown paste import and export
│   ├── legality.py           regulation checks
│   ├── type_chart.py         type effectiveness plus abilities that change matchups
│   ├── usage.py              Smogon chaos parsing, popular sets, team-sheet merging of Megas
│   ├── analysis.py           matchups, coverage, roles, speed tiers, threats
│   └── recommend.py          explainable multi-signal recommender
├── scripts/
│   ├── export_dex.js         Showdown → data/dex
│   └── fetch_usage.py        Smogon → data/usage
├── data/dex, data/usage      generated data (committed so the app runs without setup)
├── tests/                    unittest suite and chaos fixture
└── .github/workflows/        tests and the monthly data refresh
```

## Roadmap

- [x] Stage 1: dashboard with type coverage and stat comparison (original PokéAPI version)
- [x] Stage 2: Smogon usage data and teammate co-occurrence
- [x] Stage 3: team-aware recommender
- [x] **Stage 4: Champions rebuild**: regulation-accurate legality, Stat Points,
  Megas, an automated data pipeline, threat analysis, and a multi-signal
  explainable recommender
- [ ] Stage 5: learned embeddings (e.g. word2vec on tournament team lists) as an extra synergy signal, evaluated against held-out teams
- [ ] Stage 6: a damage calculator for the matchups the threat view flags
- [ ] Deploy to Streamlit Community Cloud
