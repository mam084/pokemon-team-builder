# Data pipeline

## Sources

| What | Source | How it gets here |
|---|---|---|
| Legal Pokémon, Megas, movepools, items, abilities, type chart | [Pokémon Showdown](https://github.com/smogon/pokemon-showdown)'s `champions` mod, the same code that validates teams on the ladder | `scripts/export_dex.js` → `data/dex/<regulation>.json` |
| Usage, sets, teammates, checks & counters | [Smogon monthly usage stats](https://www.smogon.com/stats/) (`chaos` JSON, 1630+ rating) | `scripts/fetch_usage.py` → `data/usage/<format>.json` |
| Real tournament teams (for evaluation) | [Limitless](https://play.limitlesstcg.com) public API, Reg M-C tournaments with 16+ players | `scripts/fetch_tournaments.py` → `data/tournaments/<regulation>.json` |

The **Refresh data** GitHub Action rebuilds all of these on the 3rd of every month,
after Smogon publishes the previous month's stats. It also runs whenever the
data scripts change, and you can start it by hand from the Actions tab. If
anything changed, it commits the new data. When a new regulation launches, see
*When a new regulation starts* below.

A few things to know about the data:
- Smogon lists each Mega under its own name ("Charizard-Mega-Y"), because that's
  the form that battles. Team sheets list the base Pokémon plus its stone, so the
  app merges the two views (`UsageData.variants`).
- Teammate % is P(B on team | A on team), so it isn't symmetric. The recommender
  uses *lift* so that Pokémon that are just popular everywhere don't dominate the
  results.
- The defensive heatmap is type-based (with the abilities that change type
  matchups). Damage-based views are the Matchups tab and the Damage calc tab.
- Tournament team lists from [Limitless](https://play.limitlesstcg.com) both feed
  the recommender (pairings, the teammate model) and test it. The evaluation keeps
  them apart by date: the model only sees tournaments (and replays) older than the
  ones it's tested on.

## When a new regulation starts

Reg M-C ends Dec 2, 2026. Most of the switch-over is automatic:

1. **Noticing it.** The *Watch for a new regulation* workflow reads Showdown's format list daily
   (`scripts/new_regulation.py check`; Showdown adds a regulation shortly before it starts) and opens
   an issue labelled `new-regulation` with the command to run.
2. **Switching** (one command on the start day, then push):
   `python scripts/new_regulation.py add --vgc gen9championsvgc2026regmd --bss gen9championsbssregmd --limitless M-D --start 2026-12-03`.
   It adds the new formats to `src/formats.py`, marks the old ones past and makes the new one the default.
   Everything else reads `src/formats.py`: the push starts *Refresh data*, whose dex export picks up any
   Champions regulation Showdown has, and the next replay fetch starts on the new ladder and Bo3 formats.
3. **The first weeks.** Smogon publishes a month's stats after it ends, so the new regulation has none
   until early the next month. Until then the app's usage comes from the regulation's own replays
   (`src/replay_usage.py`, rebuilt twice a day): who's on teams, teammates, Mega rates, and sets from open
   team sheets, with the last regulation's sets for Pokémon that carry over and too few sheets. The
   teammate model retrains on the replays from the first fetch, with a head start from the last regulation (below). Tournament-based parts (the win model,
   team rating, real tournament teams) fill in as Limitless events happen; until they do, the app shows
   what it has, and the health check reports them as waiting, not failing, for 35 days.

**Is a few days of replays enough?** (`labs/new_regulation_lab.py`) Simulated on Reg M-C: each
setup sees only data from before the held-out week, and hides one Pokémon from 500 held-out tournament
teams (3,000 queries):

| what the app has | finds the hidden Pokémon first | MRR | in the candidate pool |
|---|---|---|---|
| everything it has today (Smogon + replays + tournaments) | 57.6% | 0.681 | 94.7% |
| replays only, last 1 day | 51.7% | 0.624 | 93.3% |
| replays only, last 7 days (what ships) | 53.4% | 0.636 | 93.3% |
| last regulation's Smogon stats, rescaled to 7 days of replays | 49.8% | 0.584 | 83.1% |
| last regulation's Smogon stats alone | 16.7% | 0.263 | 80.1% |

Replay-built usage beats the last regulation's stats rescaled to the same replays by +0.052 MRR
(95% +0.040 to +0.063), mostly because new Pokémon are in its pool, and the last regulation's stats
alone by +0.37. It stays below the full setup (−0.045, 95% −0.054 to −0.037), so it is only a stand-in:
once Smogon has stats for the format, they're used as before. More days barely help (1 day 0.624,
14 days 0.633). Caveat: this is late Reg M-C, when teams had settled; a regulation's real first days
will be noisier.

**A head start for the teammate model** (`labs/regulation_start_lab.py`, Nov 21). On a regulation's first days
the teammate model has a few days of replays, and every pair's pull starts at 0. Most Pokémon carry over, so for
the first 15 days (`HEAD_START_DAYS`) `scripts/train_teammates.py` shrinks pulls toward the previous regulation's
Smogon teammate lifts at half strength instead (`HEAD_START_STRENGTH`, chosen on the week after each window).
Simulated on Reg M-C's first days with Reg M-B's stats, judged on M-C's 1,500 tournament teams from Oct 30 on
(9,000 queries):

| days of replays | replays | top 10: no head start → head start | MRR gain (95%) |
|---|---|---|---|
| 1 | 1,870 | 74.3% → 75.3% | +0.011 (+0.007 to +0.014) |
| 3 | 4,587 | 75.9% → 76.4% | +0.006 (+0.003 to +0.008) |
| 7 | 9,344 | 77.4% → 78.2% | +0.005 (+0.003 to +0.008) |
| 14 | 22,273 | 79.3% → 79.7% | +0.004 (+0.003 to +0.006) |

The gain fades as replays pile up, so after 15 days the model is fitted as before.
