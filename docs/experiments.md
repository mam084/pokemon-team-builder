# Experiments and evaluation

Every model the app ships was fitted on older data and tested once on newer data it never saw. This is the full write-up, including what was tried and rejected. The lab scripts are in [`labs/`](../labs/). Tables between `generated` markers are rewritten from `data/evaluation/` by `scripts/update_readme.py`.

## How accurate are the recommendations?

The recommender is tested on teams real players brought to
[Limitless](https://play.limitlesstcg.com) tournaments. Those teams are never
used to build it. The test (`src/evaluate.py`): take a real six, **hide one
member, give the other five to the recommender, and see where the hidden
Pokémon ranks** among about 68 candidates. This is repeated
for every member of every team.

<!-- generated:recommender -->
Tournaments are split by date. The teammate model learned from the 2,155 oldest teams (plus replays from before the next tournaments) and the weights were tuned by grid search on the next 1,626. Every number below comes from
1,737 teams in the 36 newest tournaments (2026-11-15 to
2026-11-21), which neither ever saw.

| model | top 1 | top 5 | top 10 | MRR |
|---|---|---|---|---|
| tuned weights | 57.6% | 80.5% | 87.3% | 0.678 |
| hand-set weights | 18.0% | 47.2% | 62.8% | 0.327 |
| synergy only | 56.4% | 80.3% | 87.2% | 0.672 |
| popularity only | 6.2% | 37.6% | 51.7% | 0.214 |
| before: lift synergy | 46.2% | 71.2% | 79.7% | 0.578 |
| random | 1.5% | 7.3% | 14.7% | 0.071 |

- The tuned weights find the missing Pokémon **first try 58% of the
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

`labs/synergy_lab.py` compares it with lift on the same held-out tournaments
(model fitted only on older tournaments and replays):

| synergy measure (alone) | top 1 | top 10 | MRR |
|---|---|---|---|
| lift (ladder + tournament pairings) | 35.1% | 71.3% | 0.479 |
| learned, tournaments only | 53.4% | 81.7% | 0.629 |
| learned, ladder replays only | 54.3% | 83.3% | 0.643 |
| learned, both (shipped) | 55.2% | 84.7% | 0.655 |

**Can replays say which pairs *win* more together?** Not yet:
`labs/win_synergy_lab.py` predicts the winners of 14,000 newer ladder games
from player ratings, plus the Pokémon on each team, plus every pair. Pairs moved
accuracy from 54.4% to 54.7% (log loss 0.6873 to 0.6870), which is noise at this
size, so recommendations use who players pair, not pair win rates.

## Does the matchup score predict wins?

The Matchups tab scores your team against others with damage calcs and Speed.
<!-- generated:validation -->
`src/validate.py` checks that score against **12,383 real Limitless
matches** where both players' team lists are known: each pair of teams is
scored against each other, a win-chance curve is fitted on the older
8,371 matches, and it's judged on the newest 4,012
(2026-11-15 to 2026-11-21).

| model | picks the winner | log loss |
|---|---|---|
| team vs team (bring 4) | 51.7% | 0.6934 |
| team vs team (all 6) | 51.7% | 0.6932 |
| score vs the meta | 51.2% | 0.6924 |
| popularity | 51.8% | 0.6924 |
| coin flip | 50.0% | 0.6931 |

Split into fifths by score, the side the model favors most strongly won
**53%** and the side it disfavors most strongly
**50%**, close to the fitted curve
(55% / 45%).
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
chosen by forward-chaining cross-validation inside the older 8,371
matches, and it's tested once on the newest 4,012
(2026-11-15 to 2026-11-21):

| model | picks the winner | log loss | AUC |
|---|---|---|---|
| learned model (skill + team) | 58.6% | 0.6724 | 0.615 |
| player skill only | 57.4% | 0.6729 | 0.613 |
| team only | 52.7% | 0.6918 | 0.533 |
| damage-calc matchup score | 51.6% | 0.6932 | 0.516 |
| popularity only | 51.7% | 0.6923 | 0.524 |
| coin flip | 50.0% | 0.6931 | 0.500 |

- **Who's playing matters most.** On the newest matches, the team's extra signal on top of the players' ratings is too small to tell apart from zero (log-loss gain -0.0025 to +0.0035 over ratings alone, 95% paired bootstrap). Treat team-vs-team win chances as a rough guide.
<!-- /generated:learned -->

**Upgrades tried and rejected (Nov 2026, `labs/match_lab.py`, `labs/match_lab2.py`).** None beat
the model above on the held-out tournaments, so none shipped: one-on-one "answers" counts, walls,
cubed matchup scores, Choice Scarf speed in the matchup scores (changed 40% of matches' speed
feature, held-out log loss 0.0002 worse), gradient-boosted trees (worse), and training on ~100,000 rated ladder and Bo3
replays as well (no gain on tournaments). Bo3 games alone, with their open team sheets
(`labs/bo3_match_lab.py`, Nov 2026; 50,073 rated non-forfeit games, settings picked on the training
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

**Bo3 replays** (`labs/tool_count_lab.py`; 75,599 rated games with open team sheets, never used to fit the
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
Fitted on data before 2026-11-15; bounds from 1,200 real teams from before then
(the best scores 59.4% vs the meta). **Ranking the 1,737 held-out teams**
by win chance vs the meta, then checking how they actually did:

| teams, by win chance | without bounds: said | won | with bounds: said | won |
|---|---|---|---|---|
| lowest quarter | 44.7% | 46.6% | 44.7% | 46.6% |
| 2nd quarter | 49.0% | 48.7% | 49.0% | 48.7% |
| 3rd quarter | 51.0% | 51.0% | 51.0% | 51.0% |
| highest quarter | 53.2% | 51.2% | 53.2% | 51.2% |

Rank correlation with real records: 0.076 without bounds, 0.076 with. The
bounds moved 0.1% of real teams by more than 0.1 points.

**Keep applying the best swap** (Neutral, any role) from the most popular meta teams:

| start | ends at, without bounds | with bounds |
|---|---|---|
| Goodstuffs (Sneasler + Kingambit) | 63.6% | 59.4% |
| Sun (Charizard-Mega-Y + Garchomp) | 63.2% | 59.4% |
| Rain + Tailwind (Archaludon + Pelipper) | 64.1% | 59.4% |

Without bounds the search walks to 63%-64%, past every real team; with them it stops at the best
real team's score.

**What swaps are judged by.** Ranking the same 1,737 held-out teams by **team score** (teammate fit
plus win chance, `src/team_rating.py`) vs **win chance alone**, with the teammate model also fitted before
2026-11-15:

| teams, by | win chance alone: won | team score: won |
|---|---|---|
| lowest quarter | 46.6% | 43.3% |
| 2nd quarter | 48.7% | 50.6% |
| 3rd quarter | 51.0% | 52.2% |
| highest quarter | 51.2% | 50.9% |

Rank correlation with real records: 0.076 by win chance, 0.113
by team score (paired 95% interval for the gain: +0.006 to +0.067). So swaps are judged by
team score. Keep applying the best swap that way (any role, bounds on):

| start | team score | win chance at the end | real teams sharing 5+ of its six |
|---|---|---|---|
| Goodstuffs (Sneasler + Kingambit) | 47 → 79 | 53.5% | 79 |
| Sun (Charizard-Mega-Y + Garchomp) | 40 → 97 | 56.2% | 100 |
| Rain + Tailwind (Archaludon + Pelipper) | 66 → 66 | 49.2% | 223 |
<!-- /generated:teamcheck -->

**Support tools: count each copy, or just "has it"? Tested, not shipped** (`labs/win_model_lab.py`, Nov 21).
The match model counts how many of your Pokémon carry each tool, so every extra Wide Guard earns the same
points as the first (the trust bounds below cap how far that goes), and rare tools can take huge weights
(Paralysis, different in ~1% of matches: -16 points per Pokémon) because features are standardized before
the penalty. Variants fitted and judged like the shipped model (C by forward CV on the oldest 70% of
tournaments, judged on the newest 30%, 4,087 matches):

| variant | test log loss vs shipped (95%) | swap test: win chance corr (vs shipped) | Paralysis pts |
|---|---|---|---|
| shipped: count per Pokémon | — | +0.059 | -13.6 |
| has it (0/1) | +0.0004 better (-0.0005 to +0.0013) | +0.045 (-0.021) | -13.4 |
| sqrt(count) | +0.0003 (-0.0001 to +0.0008) | | -13.6 |
| has it, rare tools shrunk like common ones | +0.0003 (-0.0007 to +0.0012) | +0.044 (-0.022) | -3.5 |
| count, rare tools shrunk | +0.0001 (-0.0005 to +0.0006) | +0.057 (-0.004) | -7.4 |

(Coefficients here are from the training-period fit; the swap test refits each on all tournaments, trust
bounds off, and scores the same-five / different-sixth replay pairs from `labs/swap_quality_lab.py`.)
None predicts match results better, and counting "has it" picked slightly *worse* swaps, so the shipped
model stays: a second copy of a tool seems to carry real signal, and the trust bounds already stop stacking
past what real teams reach. Weakness to keep in mind: on the newest tournaments the team features add
little beyond player skill (log loss gain 95% -0.002 to +0.004), and win chance alone barely predicts which
swap wins (+0.06), which is why swaps lean on teammate fit and say when they don't.

## How good are the swaps? (Nov 21, `labs/swap_quality_lab.py`, `labs/swap_choice_lab.py`)

Two questions, both answered on rated ladder and Bo3 replays (186,000 games) that neither the teammate model
nor the match model learned outcomes from.

**Does the swap the app prefers win more?** Wherever teams share the same five Pokémon and differ in the sixth
(1,334 pairs of sixths in 516 cores, each sixth 20+ games), compare their wins above what the players' ratings
predicted (Elo expected), with 95% intervals from resampling cores:

| scorer | correlation with real results | the sixth it prefers did |
|---|---|---|
| team score (what swaps are ranked by) | +0.18 (+0.09 to +0.25) | +1.4 pts (+0.3 to +2.5) |
| teammate fit alone | +0.15 (+0.06 to +0.25) | +1.4 pts |
| win chance vs the meta alone | +0.06 (-0.03 to +0.13) | +0.4 pts |
| popularity | -0.02 | -0.3 pts |

When fit and win chance agree (671 pairs) the preferred sixth did **+1.8 pts** (+0.3 to +3.2); where they
disagree and the team score follows win chance (307 pairs) it did **+0.05**, a coin flip. A joint fit puts win
chance at ~0.6 of fit's weight (95% -0.1 to 1.3) and a time split pointed both ways, so the weights stay equal;
instead each upgrade says which signals back it ("Backed by both" / "Win model only"). An evidence term ("teams
with your five plus Y won N points above expected") leaned positive on the newest games but its interval
spanned zero (292 test pairs), so it isn't used. Players' own one-Pokémon changes (312 swaps with 5+ games on
each side) were too few to tell scorers apart.

**Would the app suggest what players actually switch to?** 1,312 real one-Pokémon swaps made after the newest
30% of games began, with the teammate model fitted only before that. Where the real replacement lands among
the app's candidates for that slot:

| ranking | top 1 | top 3 | top 10 | MRR |
|---|---|---|---|---|
| shared roles and types (the old "Most similar") | 5.6% | 8.9% | 16.5% | 0.099 |
| **teammate fit (now "Players' pick")** | **21.2%** | **41.5%** | **61.4%** | **0.345** |
| popularity | 7.3% | 17.8% | 39.2% | 0.179 |
| shared roles + fit | 12.4% | 25.5% | 48.6% | 0.236 |
| fit + what players who dropped it switched to | 23.7% | 42.9% | 62.6% | 0.367 |

The real replacement had a different job (Support / Attacker / Hybrid) **54%** of the time, and when players
replaced a team's only weather / terrain / Trick Room setter they kept that plan just **16%** of the time, so
*Same role only* hid what most players do: it's now off by default (still available). The past-swaps signal
adds little over fit, so it isn't used. Each Pokémon is a Players' pick for one member at most.

## Two lenses: proven, and on paper

Tournament data can only vouch for combinations people play, so one grade built from it marks every
off-meta team down, good or bad. The Matchups tab's **Team check** shows two lenses instead:

- **Proven** (Strong / Solid / Shaky / Weak): how often strong players bring these Pokémon together,
  ranked among real tournament teams. When half the team or more is on few ladder teams it says
  **Untested**: the data can't judge it, which isn't a mark against it.
- **On paper**: the learned win chance against the meta teams (damage calcs, Speed, bulk, support
  moves), ranked the same way. Popularity plays no part.

Both tracked real results on the held-out week. Swaps use the team score, which combines them.

**Are Hidden gems picks any good?** (`labs/hidden_gems_lab.py`) Tournaments can't say, but ladder and
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

**Builder fixes** (`labs/builder_lab.py`, held-out week): no credit for starting Tailwind on a team that
already runs Trick Room, or the reverse (Staraptor's Tailwind "helping" the Trick Room setter). Neutral
builds with both fell from 33% to 21% and leaned toward the week's winning teams a little more (+0.084 to
+0.101). Counting the core's pairings twice made 93-96% of picks pair with the core (from 86-91%), but its
gain toward winners (+0.047, 95% -0.003 to +0.102) didn't clear zero. It is on anyway
(`ANCHOR_WEIGHT = 2`), by choice: no measured loss, and teams built around a core should pair with it.

**Sets from real team sheets** (`src/sheet_sets.py`, `labs/sheet_set_lab.py`, Nov 2026). Smogon's ladder stats
count each move on its own; Bo3 open team sheets and tournament lists are whole sets. The builder now gives each
Pokémon (its core included) the most common complete moveset on the last 30 days of sheets, each player counted
once, and the most common tournament nature, when there are 10+ sheets (else the ladder set; the item still
follows Item Clause). On 11,083 held-out tournament sets that matched +0.075 more moves per set (95% +0.063 to
+0.088) and the nature 67.7% vs 62.7% of the time. Re-run on 12,027 held-out sets (Nov 19): the whole set now
adds only +0.025 (95% +0.014 to +0.036), because with 10-30 sheets the most common whole set can be just two
players' (Espeon's Helping Hand set, while Expanding Force is on 55% of its sheets). Taking the whole set only
when 40%+ of sheets share it, else the four moves most often on sheets, matches +0.063 (95% +0.054 to +0.072);
that rule ships (`MODE_SHARE = 0.4`), and every set in the app now uses it, not just the builder's. Mega Feraligatr becomes Adamant, as tournament players run
it. Built teams lean toward the week's winners the same as before (+0.001) and score higher (Popular 53.0 → 55.7,
Neutral 21.9 → 22.8; `labs/threat_builder_lab.py`).

**Little data on a core** (`labs/thin_core_lab.py`, held-out week, Nov 19). Hide each member of 1,701 held-out
tournament teams and rank it from the other five; grouped by how many weighted teams the teammate model has on the
least-seen of the five, the real teammate is in the builder's top 10:

| least-seen Pokémon, weighted teams | under 100 | 100-200 | 200-400 | 400-800 | 800-1600 | 1600+ |
|---|---|---|---|---|---|---|
| top 10 | 55% | 59% | 70% | 79% | 91% | 94% |

So under 400 (`THIN_EVIDENCE`; 145 of the 228 Pokémon in the builder list, all from its less-used end) the builder and
the Pokémon tab say so in one line: *Little data on Feraligatr-Mega (7 tournament teams from 4 players, 103 rated games
in 30 days). With this little data, the builder's top 10 holds the real teammate about 59% of the time (87% overall)...*
A Pokémon with little data isn't a weak one: Mega Feraligatr's rated games are within the noise of what its players'
ratings predicted, and put in the Mega slot of 250 real one-Mega tournament teams it rates 46.9% vs the meta, 23rd of
57 Megas (Metagross 50.6%, Blastoise 47.3%).

**Counting a player's repeat tournament entries once: tested, not shipped** (`labs/repeat_entries_lab.py`). 29% of
tournament sheets repeat a six the same player already entered (one six 18 times), so one player can make a pull on
their own (Feraligatr + Empoleon 3.4x was one team entered twice). On the held-out week (10,206 queries), counting each
player's six once lowered MRR by 0.0026 (95% -0.0045 to -0.0008); keeping the first entry at 3x and repeats at 1x moved
it +0.0014 (-0.0000 to +0.0029), and -0.0012 (-0.0041 to +0.0015) around rarely seen Pokémon, the case it was for. So
every sheet still counts; the thin-data line covers the rest.

**Borrowing partners from similar Pokémon: tested, not shipped** (`labs/rare_prior_lab.py`, Nov 21). Instead of
shrinking an unseen pair's pull toward 0, shrink it toward a guess from what the two are: types, Speed band,
physical / special, Mega, the support tools of its usual set (Trick Room, Tailwind, weather, Fake Out, redirection,
Intimidate...) and weather abusers, 49 features, with the guess learned from the well-backed pairs. Strength chosen
on the tuning tournaments; on the held-out week (10,602 queries) MRR moved +0.0000 (95% -0.0006 to +0.0006), and
around rarely seen Pokémon -0.005 to +0.002, all within noise (under 100 weighted teams: top 10 60.0% either way).
What a Pokémon is says little about who players pair it with beyond what the data already shows.

**Answering the core's threats: tested, not shipped** (`labs/threat_builder_lab.py`). A bonus for picks that
beat the meta Pokémon the core loses to: the builder's teams already answer 93-95% of them, 99% with the bonus,
but the lean toward winners moved +0.066 (95% -0.003 to +0.136) in Popular and +0.003 in Neutral, with slightly
lower team scores. Not clear of zero, so `THREAT_WEIGHT = 0`; each built team still says which threats it answers.

**After setup** (`src/setup.py`): for a core with Dragon Dance, Swords Dance, Quiver Dance, Calm Mind, Nasty Plot,
Shell Smash and the like, the core report shows what one use buys against the top 30 (one-hit KOs, newly won
one-on-ones, Speed), and the Damage calc tab has a one-tap *Apply one Dragon Dance*. A display only: it assumes
the setup turn is free, which a damage calc can't judge; the learned win model already credits setup moves
from real results.

**Builder reasons only claim what the set carries** (`labs/set_fit_lab.py`, Nov 2026). A pick earns
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

### Does following the bring / lead model win? (`labs/bring_value_lab.py`, Nov 2026)

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

## Off-meta cores: does the builder steer toward what wins? (`labs/offmeta_lab.py`)

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
games the Neutral slope stayed at -0.45 either way (`labs/offmeta_lab.py --gems`): no harm, no measurable gain
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
188,948 replays; tested on 19,660 team previews.

| | bring-4 | lead pair |
|---|---|---|
| learned bring / lead model | 72.1% | 43.1% |
| players' usual picks (bring / lead rates) | 70.9% | 42.7% |
| damage-calc game plan | 68.3% | 34.2% |
| random | 66.8% | 33.5% |
<!-- /generated:bring -->

The damage-calc plan barely beats random: real choices depend on more than
damage. The learned bring model (`src/bring_model.py`) does best for the
bring-4, so the game plan's **Bring** comes from it (whenever its latest test beats
both baselines), with players' usual leads among those four; each Pokémon's Meta
page shows its bring / lead / win rates and usual turn-1 moves. The monthly
refresh retrains the model as replays pile up.

## Holding up under load (`scripts/load_test.py`, Nov 20)

Streamlit Community Cloud gives an app up to 2 cores and throttles it past ~690 MB (2.7 GB max). Streamlit
runs every visitor's page in one Python process, so their work shares roughly one core. Load test: the app
pinned to 2 cores, simulated visitors each with a different real tournament team, through Analysis,
Matchups, Battle plan, Recommendations and Pokémon.

| | before | after |
|---|---|---|
| server CPU per visitor | ~8 s | ~2 s |
| Matchups, 10 visitors at once (median) | 45 s | 1 s |
| memory over 60 new teams with swaps | 410 → 598 MB, still climbing | 519 → 550 MB, levelling off |

- **Suggested swaps run on request.** The swap search was ~9 of the ~11 s of server work in opening
  Matchups, paid by every new team even if nobody scrolled to it. It's now behind *Find swaps*; once a
  visitor uses it, it runs automatically for the rest of their visit.
- **Shared caches are bounded.** The damage-calc cache (~1.4 KB an entry) used to clear at 200k entries,
  reaching ~270 MB first; it now drops least-recently-used entries past 60k (~85 MB). The swap engine's
  per-set cache had no limit; it now keeps 3,000 sets (~40 MB). Swap results are unchanged and no slower.
- **Faster swap search (Nov 21).** *Find swaps* scores ~450 candidate teams against every meta team. It
  used to do that one meta team at a time (~30,000 small numpy calls per team); it now scores all meta
  teams at once, with the same operations in the same order, so results are identical to the last bit
  (checked on 10 real teams in every mode and view, and by a test). The team rating's fit check also
  stopped doing work it threw away. Same machine, cold caches, median of 3 runs:

  | *Find swaps* | before | after |
  |---|---|---|
  | 10 teams one after another | 35.1 s | 13.8 s (2.5x faster) |
  | 10 visitors pressing it at the same moment (median / worst wait) | 50 s / 52 s | 20 s / 21 s |
  | server CPU per visitor, full browser load test | ~8 s | ~5.5 s |

  What's left is mostly the damage calcs for newcomers no visitor has tried yet (cached after that).
