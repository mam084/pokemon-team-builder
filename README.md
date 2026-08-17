# Pokemon Team Builder

An interactive dashboard for building a Pokemon team and analyzing it: type coverage, shared weaknesses, and stat comparisons across your chosen team.

Built as a portfolio project, developed in stages — this repo is meant to show iterative growth from a basic dashboard toward a deployed ML-based recommender.

![Dashboard screenshot](docs/screenshot.png)

## Features (Stage 1)

- Pulls live Pokemon data (types, base stats, abilities) from [PokeAPI](https://pokeapi.co/)
- Build a team of up to 6 Pokemon via a simple picker
- **Type coverage heatmap** — see at a glance which attacking types your team is weak or resistant to, plus a callout for any shared weaknesses (types that hit 2+ team members hard)
- **Stat comparison** — radar chart and base-stat-total bar chart across your selected team

## Tech Stack

- **Data:** [PokeAPI](https://pokeapi.co/) (REST), fetched concurrently with `concurrent.futures`
- **Processing:** pandas
- **Dashboard:** Streamlit
- **Charts:** Plotly

## Setup

```bash
# clone and enter the repo
git clone https://github.com/<your-username>/pokemon-team-builder.git
cd pokemon-team-builder

# install dependencies
pip install -r requirements.txt

# fetch and clean the data (Gen 1 by default; see --help for full dex)
python src/fetch_data.py
python src/clean_data.py

# launch the dashboard
streamlit run app.py
```

## Project Structure

```
pokemon-team-builder/
├── data/
│   ├── pokemon_raw.json       # cached API pulls
│   └── pokemon_clean.csv      # tidy dataset used by the app
├── docs/
│   └── screenshot.png         # dashboard screenshot for this README
├── src/
│   ├── fetch_data.py          # pulls from PokeAPI (concurrent, resumable)
│   ├── clean_data.py          # raw JSON -> tidy DataFrame
│   └── type_chart.py          # type effectiveness lookup logic
├── app.py                     # Streamlit dashboard
├── requirements.txt
├── .gitignore
└── README.md
```

## Roadmap

This project is being built in stages, each a working milestone:

- [x] **Stage 1 — Basic dashboard:** PokeAPI data, type coverage, stat comparison *(this release)*
- [ ] **Stage 2 — Real usage data:** incorporate [Smogon usage stats](https://www.smogon.com/stats/) to see what's actually played in the competitive meta, and calculate teammate co-occurrence rates
- [ ] **Stage 3 — Basic recommender:** given a Pokemon, suggest common teammates based on co-occurrence
- [ ] **Stage 4 — Upgraded model:** move from co-occurrence counting to learned embeddings (e.g. word2vec-style training on team compositions) for synergy-aware recommendations
- [ ] **Stage 5 — Deploy:** ship as a public web app (Streamlit Community Cloud) so the recommender is live and clickable, not just a notebook

## Data Source

Pokemon data via [PokeAPI](https://pokeapi.co/), a free and open Pokemon API. Type effectiveness values follow current (Gen 6+) game rules.