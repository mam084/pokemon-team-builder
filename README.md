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
- **Your team lives in the page link.** The address bar updates as you build,
  so refreshing or bookmarking the page keeps your team, and the **Share**
  link in the sidebar sends it to anyone. The team is stored as a compressed
  Showdown paste in the URL (`src/share.py`), so nothing is saved on a server
  and there are no accounts.

**Presets and roles**
- **Presets**: up to six common sets for each Pokémon, built from ladder stats.
  Each popular item (and each Mega) starts its own preset. The item shapes the
  rest of the set: Choice items drop status moves and Protect, and Choice Scarf
  picks a max-Speed spread. Apply a preset from the editor, or add one to the
  team straight from the Pokémon tab. Champions has no IVs; a "spread" is the
  nature plus Stat Points.
- **Roles**: what a Pokémon usually does (Fake Out support, Trick Room or
  Tailwind setter, Rain/Sun/Sand setter, redirector, Intimidate, Choice Scarf
  attacker, priority or spread attacker, bulky...). For meta Pokémon a role
  counts when at least 30% of sets run it, and the share is shown. For your own
  sets, roles come from your moves, item and ability. Roles appear in the team
  strip, the editor, recommendations and the meta views.

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

**Matchups vs the meta**
- Smogon stats don't record whole teams, so the app **rebuilds about 10 common
  meta teams** from teammate data. It starts from a popular Pokémon and keeps
  adding whoever is most often paired with everyone already on the team,
  respecting Species Clause and one Mega per team. Each team is named for what
  it sets up, e.g. *Rain + Tailwind (Archaludon + Pelipper)*, and every
  opponent uses its most popular set.
- Every pairing is decided by **real damage calcs in both directions**, using
  both sides' actual sets: **pair score** = log2(hits they need to KO you ÷
  hits you need to KO them), ±0.5 for Speed (reversed under Trick Room).
  Weather teams are scored in their weather. Moves whose power depends on
  weight or Speed (Low Kick, Grass Knot, Heavy Slam, Heat Crash, Gyro Ball,
  Electro Ball) use each side's real weight and Speed; Reversal, Flail and
  Hard Press assume full HP. **Team score** = how well you
  answer their Pokémon minus how well they answer yours, so a mirror match
  scores exactly 0.
- For each meta team you get a verdict, the best **bring 4** (or bring 3 in
  Singles), a pairing heatmap, your best answer to each of their Pokémon with
  the key calc (e.g. *Draco Meteor 83%*), and **counter picks** (meta Pokémon
  that beat that team).
- **Biggest threats**: the 30 most-used Pokémon ranked by
  `usage × (your Pokémon it 2HKOs + 1) ÷ (answers + 1)`, where an *answer*
  2HKOs it back while taking under 50%. Each row shows its hardest hits and
  the meta's best counters to it.

**Damage calculator**
- Level-50 Champions damage with **Showdown's exact formula and rounding**.
  `tests/test_damage.py` checks 102 cases roll-for-roll against Showdown's own
  engine (spread moves, weather, terrain, crits, screens, Helping Hand, stat
  stages, Body Press, Foul Play, Psyshock, Weather Ball, -ate abilities, Mega
  Sol, resist berries, Life Orb...).
- Pick any of your Pokémon or a meta Pokémon's popular set on either side, and
  see each move's damage range, % of HP and KO chance.

**Build around a Pokémon, and fix what's weak**
- **Build a whole team around one Pokémon**, right on the empty Team screen (and on the
  Recommendations tab): pick a core (or use your own set for it) and get three different
  complete teams. Each is filled one Pokémon at
  a time with the top recommendation, using popular sets that keep Item Clause
  and one Mega, then rated against the meta teams.
- **Pokémon tab: how any one Pokémon is played** (`ui/pokemon_tab.py`, `src/core_report.py`): its
  last 30 days of ladder and Bo3 games (wins next to what the players' ratings predicted, so a
  small sample isn't read as a verdict) and tournament record; its top partners; the team styles
  its teams carry a setter for (Trick Room, Tailwind, Rain...); the set the builder gives it and the
  moves on real team sheets (each player counted once); what it beats one-on-one and what beats it
  (damage calcs) and what one setup move adds; real winning teams to load; and the Smogon ladder
  detail (moves, items, spreads, presets, checks & counters). *Build a team around it* opens the
  builder with it picked, and each built team says which of the Pokémon that beat the core it
  answers. Built twice a day with the replays (`data/replays/summary/<format>_cores.json`), so the
  app never loads replays.
- **Against a team you're facing** (Matchups tab, last option under *Matchup detail*): enter the six you see
  at team preview (and which one Mega Evolves, if they bring two Mega Stones). Each gets its most common set,
  and the matchup gets the same plan as a meta team: win chance, what to bring and lead, what they usually
  lead, the Speed order and who answers what. Every matchup (meta teams too) also lists the Playbook's plays
  for the styles that team sets up, matched on the forme each opponent battles as (a Mega Charizard Y sets
  Sun; a Charizard that doesn't Mega Evolve doesn't), and which of your Pokémon can make them.
- **Playbook tab: how to play against Trick Room, Tailwind, weather, Psychic Terrain and setup sweepers**
  (`src/playbook.py`, `ui/playbook_tab.py`). From the last 30 days of rated ladder and Bo3 games: in the
  games where the opponent *led* with a setter, how each turn-1 choice (Fake Out on the setter, Taunt it,
  attack it, your own speed control, double Protect...) did against what the players' ratings predicted,
  next to which of your Pokémon can make each play and your hardest hit on the common setters. A glance
  line per style says how many of the plays that worked your team can make. Associations, not proof; see
  *How to play against a style* below.
- **Suggested swaps** (Matchups tab): "Garchomp → Emboar: Close Combat 116% to
  Incineroar, takes 22%". Pick a threat to fix, or ask for the best overall
  improvement. Every member × candidate swap is scored by **team score** (0-100:
  how the team compares with real tournament teams, from teammate fit plus the
  learned win chance vs the meta), and a swap is only offered if it doesn't make
  the team noticeably worse. One tap applies it.
- **Team grade** (Matchups tab): Strong, Solid, Shaky or Weak, by where the team
  score falls among real tournament teams (quarters, the precision the held-out
  test supports).
- **Recommendation style**, shared by recommendations, the builder and swaps:
  - *Popular picks*: the data-tuned defaults, which lean on proven meta Pokémon.
  - *Neutral*: popularity counts for nothing and every Pokémon with ladder data
    is considered.
  - *Hidden gems*: like Neutral, but the most-used Pokémon are marked down.
- **Game-plan synergy** (`src/plan.py`): the recommender knows what weather,
  Trick Room, Tailwind and terrain do. A Mega Froslass (Snow Warning) team gets
  Beartic (Slush Rush), Glaceon and Rotom-Frost (Blizzard never misses in snow)
  instead of the meta's usual partners. A Swift Swim team with no rain setter
  gets rain setters. The plan signal has diminishing returns, and once a plan
  has its core (two or more members using it), recommendations switch to
  **covering the core's weak spots**. Each weakness is weighted by how often
  the meta attacks with that type, so an Ice core gets Water/Fighting types or
  a Flash Fire Ceruledge, not a fifth Ice type.
- **Two Megas**: teams may carry two Mega Stones. The builder and swaps use
  that, and every matchup tells you which one to Mega Evolve.

**Find what's missing**
- **Recommendations**: every candidate gets five scores from 0 to 1, and you can
  change how much each one counts:

  | signal | meaning |
  |---|---|
  | synergy ("Fits") | how strongly players pair it with your **whole team**, from a teammate model learned on real teams (below). 0.5 = no pull either way. Formats without the model fall back to Smogon teammate lift |
  | defense | how well it resists the types your team is weak to |
  | offense | how well it hits popular Pokémon your team can't hit super effectively (weighted by usage) |
  | roles | whether it brings a role your team is missing |
  | meta | its overall usage, as a prior |

  Each pick's card explains itself in short lines (*Fits: Rillaboom (7.4x),
  Sinistcha (5.9x)*; *Watch: rarely run next to Garchomp (0.5x)*; *Covers: Ice,
  Dark, Steel*), shows how often players with your team pick it next, and has an
  **Add to team** button that adds its most popular set.
- **Spread tuner** (Team tab): pick a Speed to beat and up to 3 popular attacks to survive
  (each threat's strongest move against your set, at the highest roll); it finds the fewest
  Stat Points that do it, keeps your nature, and puts the rest into attack or bulk.
- **Tournament teams like yours** (Analysis tab): Limitless team lists that share most of
  your Pokémon, their combined record against the average, and the best finishes with what
  they ran differently.
- **Fit check** (Analysis tab): for each member, how usual it is next to the rest
  and what players most often run in that spot instead. Swaps use the same model:
  each member's second suggestion is the *usual pick* for that spot.
- **The meta** (bottom of the Pokémon tab): the usage leaderboard (tap a row to open that Pokémon) and what the learned model says wins games.

## How accurate are the recommendations?

The recommender is tested on teams real players brought to
[Limitless](https://play.limitlesstcg.com) tournaments. Those teams are never
used to build it. The test (`src/evaluate.py`): take a real six, **hide one
member, give the other five to the recommender, and see where the hidden
Pokémon ranks** among about 68 candidates. This is repeated
for every member of every team.

<!-- generated:recommender -->
Tournaments are split by date. The teammate model learned from the 2,218 oldest teams (plus replays from before the next tournaments) and the weights were tuned by grid search on the next 1,450. Every number below comes from
1,765 teams in the 36 newest tournaments (2026-11-13 to
2026-11-19), which neither ever saw.

| model | top 1 | top 5 | top 10 | MRR |
|---|---|---|---|---|
| tuned weights | 57.0% | 80.8% | 87.4% | 0.677 |
| hand-set weights | 17.7% | 46.9% | 62.9% | 0.325 |
| synergy only | 57.0% | 80.8% | 87.4% | 0.677 |
| popularity only | 6.2% | 37.3% | 51.6% | 0.211 |
| before: lift synergy | 48.5% | 72.4% | 80.3% | 0.593 |
| random | 1.5% | 7.3% | 14.7% | 0.071 |

- The tuned weights find the missing Pokémon **first try 57% of the
  time** and in the top 10 87% of the time: 108% better MRR than the
  weights the recommender originally shipped with.
<!-- /generated:recommender -->
- **Two Mega Stones are normal**: 81% of these tournament teams carry two (you
  choose which Mega Evolves at team preview). Removing the old "second Mega"
  penalty raised test MRR from 0.475 to 0.507 on the same data. The matchup engine now scores a
  two-Mega team with whichever Mega Evolves best against each opponent, and says
  which one.
- The **game-plan signal** only helps a little: the tuning gives it a small
  weight (0.05), and more than that hurts (MRR falls to about 0.44 at 0.3).
  Tournament players mostly bring proven meta Pokémon rather than building
  around weather. So it does most of its work in the *Neutral* / *Hidden gems*
  modes, whose weights are a design choice rather than fitted. In Neutral mode on 400
  held-out teams the recommender still ranks the real missing Pokémon in its
  top 10 48% of the time among ~260 candidates (random: 4%).
- With the learned teammate model, tuning puts **all the weight on Fits**: for
  predicting real teams, popularity, type coverage, roles and game plan add nothing
  on top (the model already learned who players pick). Those signals still explain
  each pick in the app, drive the *Neutral* and *Hidden gems* styles, and can be
  raised under **Fine-tune the ranking**.
- *(Before the teammate model)* **Lift synergy also learned from tournament pairings** (`src/cooccurrence.py`):
  ladder teammate stats are weighted to high-rated players, so a Pokémon on
  0.05% of those teams is really one or two players. Thousands of tournament
  team sheets give those Pokémon real sample sizes. In a three-way date split
  (pairings from the oldest teams, weights tuned on the next, tested on the
  newest 30%), adding them raised synergy-only MRR from 0.393 to 0.463 and the
  full model from 0.539 to 0.556 (top 10: 74.2% to 76.9%).
- About 6% of hidden Pokémon are outside the candidate pool
  (the usage top 80), which caps every model's scores.
- `python scripts/evaluate.py` reproduces this. The monthly data refresh re-runs it on new tournaments.

### Learned synergy

Lift looks at one pair at a time, so it can't tell real partners apart from two
Pokémon that only show up together because both go with a third. The teammate
model (`src/synergy.py`) scores a candidate against the whole team at once, and is
fitted the way it's used: hide each member of a real team and predict it from the
rest.

    P(candidate c | team T)  ∝  exp( b_c + Σ_{m in T} W[m, c] )

`b_c` is how often c gets picked at all, and `W[m, c]` is the pull between two
Pokémon *after* accounting for the rest of the team. It's fitted on every tournament
team list (counted 3x) plus the last 30 days of ladder and Bo3 teams from replays
(each player's team once, higher ratings weighted more; older replays stopped
helping as the meta moved: 45+ days scored MRR 0.650 vs 0.656 for 30), with L2 regularisation so
rarely seen pairs stay near 0. `exp(W)` is the "7.4x" in the app's reasons.

`scripts/synergy_lab.py` compares it with lift on the same held-out tournaments
(model fitted only on older tournaments and replays):

| synergy measure (alone) | top 1 | top 10 | MRR |
|---|---|---|---|
| lift (ladder + tournament pairings) | 35.1% | 71.3% | 0.479 |
| learned, tournaments only | 53.4% | 81.7% | 0.629 |
| learned, ladder replays only | 54.3% | 83.3% | 0.643 |
| learned, both (shipped) | 55.2% | 84.7% | 0.655 |

**Can replays say which pairs *win* more together?** Not yet:
`scripts/win_synergy_lab.py` predicts the winners of 14,000 newer ladder games
from player ratings, plus the Pokémon on each team, plus every pair. Pairs moved
accuracy from 54.4% to 54.7% (log loss 0.6873 to 0.6870), which is noise at this
size, so recommendations use who players pair, not pair win rates.

## Does the matchup score predict wins?

The Matchups tab scores your team against others with damage calcs and Speed.
<!-- generated:validation -->
`src/validate.py` checks that score against **12,190 real Limitless
matches** where both players' team lists are known: each pair of teams is
scored against each other, a win-chance curve is fitted on the older
8,092 matches, and it's judged on the newest 4,098
(2026-11-13 to 2026-11-19).

| model | picks the winner | log loss |
|---|---|---|
| team vs team (bring 4) | 52.1% | 0.6925 |
| team vs team (all 6) | 51.9% | 0.6923 |
| score vs the meta | 51.6% | 0.6920 |
| popularity | 51.2% | 0.6923 |
| coin flip | 50.0% | 0.6931 |

Split into fifths by score, the side the model favors most strongly won
**54%** and the side it disfavors most strongly
**48%**, close to the fitted curve
(55% / 46%).
<!-- /generated:validation -->

- **The signal is real but small.** One game is mostly play and luck, so the
  app shows matchups as a calibrated win chance ("about 48% to win") rather
  than implying a favorable matchup is a sure thing.
- Player skill can't be read off the Swiss records: a player's record in their
  *other* matches predicts nothing here, because Swiss pairs players with equal
  records, so opponents start roughly even. That also makes these matches a
  fair test of team choice.
- The pair score's Speed bonus (0.5) was checked against 0 and 1.0 on the
  older matches; 0.5 fit best, so it stays.
- **Support** (screens, Intimidate, Tailwind, Trick Room) was tested as a
  team-wide effect on every pairing. No version improved predictions:
  Tailwind / Trick Room made them worse at every strength tried, so they don't
  change the score; screens and Intimidate count at 0.2 strength, which costs
  no measurable accuracy and lets a screens setter earn a bring slot in close
  calls. Capturing support properly would take a turn-by-turn battle simulator.
- Team lists don't publish stat points; each Pokémon gets its most common
  ladder spread (`usage.typical_spread`). Each side Mega Evolves its first stone.
- `python -m src.validate` reproduces this; the monthly data refresh re-runs it.

## A learned model of who wins

Hand-weighting support made match predictions worse, so `src/match_model.py`
learns what matters instead, from 12,168 real matches with both team lists.
Each match becomes a row of differences (player 1 minus player 2):

- **player skill**: each player's Elo *before* the match (`src/ratings.py`,
  updated match by match over all 13,000 Limitless results, K tuned on the older
  tournaments) and games played, so a team doesn't get credit for its pilot
- **matchup**: the damage-calc team score, bring-4 score, mean best damage each
  way, OHKO / 2HKO counts, share of pairings won on Speed
- **support tools**: how many Pokémon on each side carry Fake Out, Intimidate,
  Tailwind, Trick Room, screens, redirection, Wide Guard, sleep, Encore, setup,
  recovery, priority, weather, terrain and more
- **context**: bulk and base Speed, Trick Room on a slow team, Tailwind on a fast one (score vs the meta, popularity and having a Mega were tested and dropped: they didn't improve held-out predictions)

An L2-regularized logistic regression is fitted on both orientations of every
match (so swapping the players exactly flips the prediction). Its settings are
<!-- generated:learned -->
chosen by forward-chaining cross-validation inside the older 8,092
matches, and it's tested once on the newest 4,098
(2026-11-13 to 2026-11-19):

| model | picks the winner | log loss | AUC |
|---|---|---|---|
| learned model (skill + team) | 59.0% | 0.6686 | 0.622 |
| player skill only | 57.7% | 0.6714 | 0.615 |
| team only | 53.4% | 0.6894 | 0.546 |
| damage-calc matchup score | 51.9% | 0.6921 | 0.524 |
| popularity only | 51.1% | 0.6923 | 0.523 |
| coin flip | 50.0% | 0.6931 | 0.500 |

- **Who's playing matters most**, but the team adds real signal on top: log-loss
  gain +0.0002 to +0.0054 over ratings alone (95% paired bootstrap).
<!-- /generated:learned -->

**Upgrades tried and rejected (Nov 2026, `scripts/match_lab.py`, `scripts/match_lab2.py`).** None beat
the model above on the held-out tournaments, so none shipped: one-on-one "answers" counts, walls,
cubed matchup scores, Choice Scarf speed in the matchup scores (changed 40% of matches' speed
feature, held-out log loss 0.0002 worse), gradient-boosted trees (worse), and training on ~100,000 rated ladder and Bo3
replays as well (no gain on tournaments). Bo3 games alone, with their open team sheets
(`scripts/bo3_match_lab.py`, Nov 2026; 50,073 rated non-forfeit games, settings picked on the training
period): every window from the last 7 days to all 8 weeks scored worse on validation than tournaments
alone, and on the held-out week the best (21 days) was 0.0006 better in log loss with a 95% interval
spanning zero (-0.0001 to +0.0014), so they stay out. On replays the team features add nothing beyond the
players' ratings, even in Bo3 where the real sets are known. Teams in real play are close enough that
the player decides most games; a matchup as lopsided as all-Fire vs all-Grass is beyond every one of
~112,000 real matches, so how the model handles it can't be tested.
- **Per-Pokémon effects were mostly player skill.** Without ratings they helped
  (e.g. "Alakazam teams win 3 points more than their calcs say"); with ratings in
  the model they no longer improved cross-validated predictions, so they're out.
- Calibrated: where it gave a side its best odds (66%) that side won
  67%; its worst (35%), 38%. Boosted trees did no better.

**What it learned** (win-chance points per extra Pokémon with the tool, between
equally rated players, 90% tournament-bootstrap range):

- clearly positive: Wide Guard +1.9 (+0.4 to +3.3), Encore +1.6 (+0.2 to +3.1),
  setup moves +1.6 (+1.0 to +2.3), Trick Room +1.6 (+0.4 to +2.8) (but a slow
  team leaning on it: -4.9 (-8.7 to -1.8)); outspeeding, bulk and
  2HKOs count too
- no clear effect: Reflect +1.6 (-0.4 to +3.5), Light Screen -1.1 (-3.1 to +0.8),
  Intimidate +1.0 (-0.3 to +2.1), Tailwind -1.4 (-2.9 to +0.1)
- negative: Fake Out -1.1 (-1.8 to -0.4), recovery -1.9 (-3.3 to -0.2)

Accounting for skill barely moves these tool effects (at equal regularization,
e.g. Wide Guard +2.1 to +1.9, Encore +2.2 to +1.7), so they aren't just "strong
players use them". They're still associations, not proof of cause. The app
predicts with both players rated equal, so win chances compare *teams*.
`python -m src.ratings` and `python -m src.match_model` reproduce this; the
monthly refresh retrains it.

## Is the "best" team really that good? (trust bounds)

Keep tapping the top swap and the model used to walk any team to about **66% vs the meta**, always the
same way: Armarouge, Araquanid, Swampert and Bastiodon, **four Wide Guard users**. The model counts each
tool user (about +2 points each), so four of them were worth +8 points of the +16, while the damage calcs
added nothing. No tournament team has ever run more than two (0.1% of team sheets have two), nobody had
played even three of those six Pokémon together, and the best of 5,376 real teams scores 59%. The search
was finding where the model is most wrong, not a better team.

**Diminishing returns can't be learned from tournaments.** Counting tool users capped at 1 or 2, square-rooted
or logged all tie the linear count on the held-out week (log-loss differences within ±0.001), because there
are almost no teams that stack. Capping alone doesn't fix the search either: it then collects one of every
favored tool at once (Trick Room, Wide Guard, Yawn, a setup move, no Fake Out), each within what real teams do
but adding up to +16 points when the best real team gets +6.

**Bo3 replays** (`scripts/tool_count_lab.py`; 75,599 rated games with open team sheets, never used to fit the
model) do show diminishing returns: extra Intimidate (-1.8 points each), redirection (-1.4), Helping Hand (-5.2)
and terrain (-3.3) users hurt, and only Tailwind gains from a second setter (+2.4). They also show the
tournament-learned tool effects don't carry over: on those games they predict worse than player ratings alone,
counted linearly or capped.

So the fix is in the search, not the model: **trust bounds** (`src/match_model.trust_bounds`). Each feature's
push, the total, and the win chance vs the meta are capped at what real tournament teams reach (rebuilt with
the team rating reference, `python -m src.team_rating`). A team past them gets a one-line *Untested* note on
the Matchups tab, and swaps can't climb past the best real team. `python -m src.team_check` tests this on
the held-out week:

<!-- generated:teamcheck -->
Fitted on data before 2026-11-13; bounds from 1,200 real teams from before then
(the best scores 56.8% vs the meta). **Ranking the 1,765 held-out teams**
by win chance vs the meta, then checking how they actually did:

| teams, by win chance | without bounds: said | won | with bounds: said | won |
|---|---|---|---|---|
| lowest quarter | 45.3% | 44.7% | 45.3% | 44.6% |
| 2nd quarter | 49.0% | 48.7% | 49.0% | 48.9% |
| 3rd quarter | 50.7% | 51.4% | 50.7% | 51.3% |
| highest quarter | 52.4% | 52.1% | 52.4% | 52.1% |

Rank correlation with real records: 0.112 without bounds, 0.112 with. The
bounds moved 0.7% of real teams by more than 0.1 points.

**Keep applying the best swap** (Neutral, any role) from the most popular meta teams:

| start | ends at, without bounds | with bounds |
|---|---|---|
| Goodstuffs (Sneasler + Kingambit) | 61.4% | 56.8% |
| Sun (Charizard-Mega-Y + Garchomp) | 61.8% | 56.8% |
| Rain + Tailwind (Archaludon + Pelipper) | 61.8% | 56.8% |

Without bounds the search walks to 61%-62%, past every real team; with them it stops at the best
real team's score.

**What swaps are judged by.** Ranking the same 1,765 held-out teams by **team score** (teammate fit
plus win chance, `src/team_rating.py`) vs **win chance alone**, with the teammate model also fitted before
2026-11-13:

| teams, by | win chance alone: won | team score: won |
|---|---|---|
| lowest quarter | 44.6% | 41.9% |
| 2nd quarter | 48.9% | 50.0% |
| 3rd quarter | 51.3% | 50.6% |
| highest quarter | 52.1% | 53.8% |

Rank correlation with real records: 0.112 by win chance, 0.169
by team score (paired 95% interval for the gain: +0.025 to +0.088). So swaps are judged by
team score. Keep applying the best swap that way (any role, bounds on):

| start | team score | win chance at the end | real teams sharing 5+ of its six |
|---|---|---|---|
| Goodstuffs (Sneasler + Kingambit) | 53 → 70 | 52.4% | 78 |
| Sun (Charizard-Mega-Y + Garchomp) | 43 → 97 | 55.6% | 3 |
| Rain + Tailwind (Archaludon + Pelipper) | 68 → 68 | 49.1% | 228 |
<!-- /generated:teamcheck -->

## Two lenses: proven, and on paper

Tournament data can only vouch for combinations people play, so one grade built from it marks every
off-meta team down, good or bad. The Matchups tab's **Team check** shows two lenses instead:

- **Proven** (Strong / Solid / Shaky / Weak): how often strong players bring these Pokémon together,
  ranked among real tournament teams. When half the team or more is on few ladder teams it says
  **Untested**: the data can't judge it, which isn't a mark against it.
- **On paper**: the learned win chance against the meta teams (damage calcs, Speed, bulk, support
  moves), ranked the same way. Popularity plays no part.

Both tracked real results on the held-out week. Swaps use the team score, which combines them.

**Are Hidden gems picks any good?** (`scripts/hidden_gems_lab.py`) Tournaments can't say, but ladder and
Bo3 replays can: about 100,000 rated games with both teams' previews. Each Pokémon's win edge, adjusted for
both players' ratings, then the edge of each style's top 3 picks for 300 real teams missing one member,
against the rest of what that style could pick:

| style | its picks | its pool | difference (90% range) |
|---|---|---|---|
| Popular picks | +0.45 | +0.89 | -0.45 (-0.62 to -0.32) |
| Neutral | +0.53 | +0.27 | +0.26 (-0.02 to +0.47) |
| Hidden gems | +0.58 | +0.18 | **+0.40 (+0.07 to +0.98)** |

(points of win chance.) Hidden gems' picks win more than the uncommon Pokémon it passes over, and about as
much as the average common one (+0.64); Popular picks chases usage, not wins.

**Builder fixes** (`scripts/builder_lab.py`, held-out week): no credit for starting Tailwind on a team that
already runs Trick Room, or the reverse (Staraptor's Tailwind "helping" the Trick Room setter). Neutral
builds with both fell from 33% to 21% and leaned toward the week's winning teams a little more (+0.084 to
+0.101). Counting the core's pairings twice made 93-96% of picks pair with the core (from 86-91%), but its
gain toward winners (+0.047, 95% -0.003 to +0.102) didn't clear zero. It is on anyway
(`ANCHOR_WEIGHT = 2`), by choice: no measured loss, and teams built around a core should pair with it.

**Sets from real team sheets** (`src/sheet_sets.py`, `scripts/sheet_set_lab.py`, Nov 2026). Smogon's ladder stats
count each move on its own; Bo3 open team sheets and tournament lists are whole sets. The builder now gives each
Pokémon (its core included) the most common complete moveset on the last 30 days of sheets, each player counted
once, and the most common tournament nature, when there are 10+ sheets (else the ladder set; the item still
follows Item Clause). On 11,083 held-out tournament sets that matched +0.075 more moves per set (95% +0.063 to
+0.088) and the nature 67.7% vs 62.7% of the time. Mega Feraligatr becomes Adamant, as tournament players run
it. Built teams lean toward the week's winners the same as before (+0.001) and score higher (Popular 53.0 → 55.7,
Neutral 21.9 → 22.8; `scripts/threat_builder_lab.py`).

**Answering the core's threats: tested, not shipped** (`scripts/threat_builder_lab.py`). A bonus for picks that
beat the meta Pokémon the core loses to: the builder's teams already answer 93-95% of them, 99% with the bonus,
but the lean toward winners moved +0.066 (95% -0.003 to +0.136) in Popular and +0.003 in Neutral, with slightly
lower team scores. Not clear of zero, so `THREAT_WEIGHT = 0`; each built team still says which threats it answers.

**After setup** (`src/setup.py`): for a core with Dragon Dance, Swords Dance, Quiver Dance, Calm Mind, Nasty Plot,
Shell Smash and the like, the core report shows what one use buys against the top 30 (one-hit KOs, newly won
one-on-ones, Speed), and the Damage calc tab has a one-tap *Apply one Dragon Dance*. A display only: it assumes
the setup turn is free, which a damage calc can't judge; the learned win model already credits setup moves
from real results.

**Builder reasons only claim what the set carries** (`scripts/set_fit_lab.py`, Nov 2026). A pick earns
credit for Tailwind, Pivoting or Wide Guard from any move on 25%+ of its sets, but the set the builder adds
is its top four moves, so 19% of the claims in "Why each Pokémon" weren't on the added set (Corviknight
"for its Tailwind" with Brave Bird / Roost / Bulk Up / Power Trip). Swapping the credited move in was tested on
the held-out week's tournament sheets (hide a member, credit it from the other five, compare with the moves that
player ran): it made 1,592 sets *less* realistic, -0.37 matching moves each (95% -0.41 to -0.33); only 27% of
swapped-in moves were real, against 62% of the moves they replaced. So sets stay as players run them, and the
reason (and a team's *Tailwind* / *Rain* label) drops any claim the set doesn't carry: 0 of 1,743 claims now
go beyond their set, and the teams themselves are unchanged.

## How to play against a style (the Playbook)

`src/playbook.py` picks the games where the opponent **led** with a Pokémon that sets a style up (Trick Room,
Tailwind, Rain, Sun, Sand, Snow, Psychic Terrain, a setup sweeper), since that's what you see when you choose
turn 1. The replay log only shows moves that happened (a setter stopped by Fake Out never shows its Trick
Room), so games can't be picked by what the setter did. Each choice is scored by wins above the players'
ratings (Elo) against players facing the same lead who **could have made it and didn't**: for a move (Fake Out,
Taunt, Trick Room, Tailwind, speed drops, Haze), players who had it in play (open team sheet, used that game, or
on 40%+ of that Pokémon's sets); for your own weather setter, players with one in team preview. Choices any
team can make (attacking the setter, double Protect) are compared with everyone else. Having Fake Out isn't the
story, using it is: against everyone else, "your own Trick Room" looked like +4.2 points; against players who
had Trick Room and didn't use it, it's +2.7 and unclear. Some of what came out (Nov 2026, both players 1100+):

- vs **Sun**: Fake Out on the setter +8.4 (it can't stop Drought, but it stops the turn-1 Eruption or Heat Wave).
- vs **Rain**: leading your own weather setter +8.5.
- vs **Tailwind**: Trick Room or speed drops +5.2; attacking the setter +2.5; Fake Out on it +0.1.
- vs **Trick Room**: Taunt or Encore on the setter +10.9 (83 players); Fake Out on its partner -4.4.
- vs **setup sweepers**: Haze, Roar or Encore during the game +6.1; Fake Out on the sweeper +3.9.
- **Double Protect on turn 1** did worse against every style (-7 to -16).

A choice also says something about the team and the player, so these are associations, not causes. The clearest
example: the replay log shows a move even when it fails, and Fake Outs clicked into Psychic Terrain at a grounded
target (they do nothing) came out at +8 points: that's who clicks Fake Out, not what it did. So a Fake Out into
the terrain isn't scored as a choice (unless the target is Flying or Levitates, or the player led a terrain setter
of their own), and the tab states the rule instead.

### Weather wars: what's being collected (Nov 2026)

When two weather setters come in together, the slower one's weather stays; a Mega's ability (Mega Charizard Y's
Drought) goes off when it Mega Evolves, so two Megas on turn 1 leave the slower one's weather up. Whether to lead a
weather setter, keep it in the back, delay its Mega or leave it home can't be judged without knowing which turn it
Mega Evolved and which weather ended up on the field, so since Nov 19 each replay record also keeps `mega_turn`,
every `weather` change (turn, weather, who set it) and `field` events (Trick Room, terrains, Tailwind, screens).
Older records don't have them; the plan is to look again once about three weeks of games have them.

What the older records already say for Mega Froslass against a Charizard that Mega Evolved into Y (rated games,
both players 1100+, points of win chance above the ratings' prediction): leaving Froslass home +6.1 (488 games,
90% +2.4 to +9.8); leading it when Charizard also led -6.0 (295); leading it when Charizard didn't lead +10.0
(143); bringing it in the back -0.8 (218, unclear). Protecting turn 1 and Mega Evolving turn 2 vs Mega Evolving
turn 1 is the open question the new fields answer.

### Does following the bring / lead model win? (`scripts/bring_value_lab.py`, Nov 2026)

The bring model predicts what players choose (72% of brings, 44% of leads on held-out replays). Whether that's
worth following is a different question: on 10,178 held-out rated sides, players whose real bring overlapped
more with the model's picks won no more than their ratings predicted (-0.13 points per Pokémon, 90% -1.74 to
+1.33; leads -0.65, -2.01 to +0.70). Refitting on sides that beat their rating (winners only, or weighted by
how much they beat it) leaned better for leads (+0.66 / +0.68) but stayed inside the noise, so the shipped model
is unchanged: it's the best at predicting real choices, which is what the game plan shows.

### Model health check (`scripts/health_check.py`, weekly)

Every Monday and after each data refresh, a workflow reads the latest held-out evaluations and checks that the
recommender still beats popularity, the learned win model still beats the damage-calc score (95% interval above
0) and stays calibrated, the team check still ranks real teams in order, and the bring model still beats players'
usual picks; plus that replays, usage stats and tournaments are fresh. A failure opens (or comments on) a GitHub
issue labelled `health-check`.

## Off-meta cores: does the builder steer toward what wins? (`scripts/offmeta_lab.py`)

Tournaments have too few off-meta teams to judge, so this uses the held-out week of rated ladder and Bo3
games (18,414 team-games, both players 1100+; 134 cores with 30+ games, 68 of them under 1% usage). Every model
is fitted on data from before the week. For each game, how many Pokémon the player's team shares with the
builder's three teams for each of its members, and whether teams sharing more won more than their ratings
predicted:

| picks from | slope, points of win chance per shared Pokémon (90% interval) |
|---|---|
| the core's top-5 partners (a usage site's teammate list) | -0.18 (-0.55 to +0.27) |
| builder, Popular picks | -0.39 (-0.73 to -0.04) |
| builder, Neutral | -0.42 (-1.04 to +0.11) |
| builder, Hidden gems | **+1.65 (-0.02 to +3.18)**; cores at 3-10% usage: +2.69 (+0.68 to +4.74) |

Building like everyone else around a core doesn't win more than the players' ratings say (the player decides
most games); Hidden gems picks, the unusual ones, are the ones that over-perform, as in *Are Hidden gems picks
any good?* above.

**One of the three Neutral teams is a Hidden gems build** (`NEUTRAL_GEMS = 1`, unlabelled; the three are ranked
together), so a Neutral build also offers the unusual picks that beat their ratings above. On the same held-out
games the Neutral slope stayed at -0.45 either way (`scripts/offmeta_lab.py --gems`): no harm, no measurable gain
for the set of three; Hidden gems picks themselves +1.57.

**Tested, not shipped: a ladder-edge bonus.** Giving builder picks credit for how much more each Pokémon won than
its players' ratings predicted (30 days before the week, shrunk toward 0) moved those slopes to Popular -0.10 /
+0.19 (weights 2 / 5), Neutral -0.11 / +0.16, Hidden gems +2.19 / +1.65: all inside the noise, while pulling teams
away from what players pair with the core. `EDGE_WEIGHT = 0`.

## Battle replays

A daily GitHub Action (`scripts/fetch_replays.py`, **Fetch replays** workflow)
downloads public Showdown replays for Reg M-C (ladder and Bo3) and parses each
(`src/replay_parse.py`) into a compact record: team preview, the Pokémon
brought, leads, Mega, every move used, turn-1 choices, faints, the winner and
both ladder ratings; Bo3 games add open team sheets. Records live in
`data/replays/<format>/<day>.jsonl.gz` (about 0.5 MB a day); a `backfill` run
fetches older replays and resumes where it stopped. About 1,300 Reg M-C ladder
replays are saved publicly each day.

**Does the game plan predict what players do?** Overlap of predicted with real
choices on the newest replays (rates and model fitted on older ones):

<!-- generated:bring -->
181,385 replays; tested on 19,600 team previews.

| | bring-4 | lead pair |
|---|---|---|
| learned bring / lead model | 72.0% | 43.8% |
| players' usual picks (bring / lead rates) | 70.7% | 43.1% |
| damage-calc game plan | 68.1% | 34.1% |
| random | 66.8% | 33.0% |
<!-- /generated:bring -->

The damage-calc plan barely beats random: real choices depend on more than
damage. The learned bring model (`src/bring_model.py`) does best for the
bring-4, so the game plan's **Bring** comes from it (whenever its latest test beats
both baselines), with players' usual leads among those four; each Pokémon's Meta
page shows its bring / lead / win rates and usual turn-1 moves. The monthly
refresh retrains the model as replays pile up.

## Data

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
   teammate model retrains on the replays from the first fetch. Tournament-based parts (the win model,
   team rating, real tournament teams) fill in as Limitless events happen; until they do, the app shows
   what it has, and the health check reports them as waiting, not failing, for 35 days.

**Is a few days of replays enough?** (`scripts/new_regulation_lab.py`) Simulated on Reg M-C: each
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
│   ├── team_rating.py        team rating vs real tournament teams; builds the trust bounds
│   ├── team_check.py         held-out team ranking and swap-search check (trust bounds)
│   ├── ratings.py            leak-free Elo ratings for tournament players
│   ├── replay_parse.py       Showdown battle log -> compact record
│   ├── replays.py            replay stats; does the game plan match real choices?
│   └── bring_model.py        learned bring-4 / lead model from replays
├── scripts/
│   ├── export_dex.js         Showdown → data/dex
│   ├── fetch_usage.py        Smogon → data/usage
│   ├── fetch_tournaments.py  Limitless → data/tournaments
│   ├── evaluate.py           runs the evaluation → data/evaluation
│   ├── tool_count_lab.py     diminishing returns for support tools (tournaments and Bo3)
│   ├── set_fit_lab.py        should builder sets carry the moves they were credited for? (no)
│   ├── sheet_set_lab.py      real-sheet sets vs ladder sets on held-out tournament sheets
│   ├── threat_builder_lab.py builder: sheet sets and a threat-answer bonus, held-out week
│   ├── offmeta_lab.py        off-meta cores: do builder picks win more than ratings predict?
│   ├── bring_value_lab.py    does following the bring / lead model win? (imitation vs outcome-weighted)
│   ├── health_check.py       weekly: shipped models still beat their baselines; data is fresh
│   ├── new_regulation.py     notice a new regulation on Showdown; switch src/formats.py to it
│   ├── new_regulation_lab.py how good are recommendations from a few days of replays?
│   └── make_damage_vectors.js  Showdown → damage test vectors
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
