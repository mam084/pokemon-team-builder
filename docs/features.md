# Features

Everything the app does, tab by tab. Back to the [README](../README.md).

**Build a legal team**
- Every Pokémon, Mega Stone, item, ability and move list comes from the
  regulation's legal pool. Pokémon, items and moves are sorted by real usage,
  with each one's usage % shown.
- The editor uses Champions rules: level 50, **66 Stat Points with at most 32
  per stat**, and real level-50 stats for each nature. Mega Pokémon show their Mega
  stats, types and ability.
- When you pick a Pokémon, the app can fill in its most-used set (item, ability,
  spread and moves). It skips items your team already holds, so Item Clause
  is never broken. The same set is used everywhere (autofill, builder, Matchups,
  Battle plan): ladder stats, with moves and nature from real team sheets when
  there are enough, and an item that fits the moves (no Choice item with Protect;
  status moves go on Choice items only where real sheets do, like Trick or Soak).
- Cosmetic forms (Maushold-Four, Sinistcha-Masterpiece, Vivillon patterns) count
  as their base Pokémon everywhere, replays included. Rare forms with a different
  ability but the same types and stats (Squawkabilly-Yellow, Toxtricity-Low-Key)
  borrow their sibling's set, with their own ability.
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
  app never loads replays. When there's little data on it, one line says how far the builder's picks around
  it can be trusted (*Little data on a core*, below).
- **Battle plan tab: against a team you're facing** (first option; the common meta teams are below it): enter
  the six you see at team preview (and which one Mega Evolves, if they bring two Mega Stones), and each gets its
  most common set; or paste their team sheet (an open team sheet from Bo3 and tournaments, or a Showdown
  export) to plan against their real items, abilities and moves. Open team sheets don't show nature or Stat
  Points, so those come from the most common set and the plan says which; Trick Room and weather are read
  from their sets (`src/opponent.py`). The matchup gets a plan: win chance, what to bring and lead, what they usually lead,
  the Speed order and who answers what. The bring and lead come from the replay-learned model, which leans on
  your own team more than theirs, so the damage calcs' lead against this team is shown too when it differs.
  **Turn 1** lists what players clicked with each of your leads against their likely lead (Incineroar: Fake
  Out 54% overall, but Parting Shot first against Indeedee-F's Psychic Terrain); what players do, not a tested
  best move (`data/replays/summary/<format>_turn1.json`, last 30 days). Every matchup (meta teams too) also lists the Playbook's plays
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
- **Compare versions** (Matchups tab): save a version, then change the team or apply a swap (which saves
  the version before it when nothing is saved yet). It shows the win chance and favorable / unfavorable
  counts against the saved version, the meta teams it got better and worse against, which top threats are
  now answered or no longer answered, and every meta team for both versions. Go back, keep the new one, or
  clear (`ui/compare.py`). The saved version rides along in the page address (`v`, `vl`), so a refresh,
  a bookmark or a shared link keeps the comparison.
- **Start here** (top of the page while the team is empty): one line on what the app does that others
  don't, three steps (make a team → Matchups → Battle plan / Playbook), *Load the example team* and *Hide
  this*; hiding is remembered in the visitor's browser (`ui/start_here.py`). After the example loads, the
  notice points to Matchups.
- **Feedback**: a *Send feedback* link at the bottom of every page and in the sidebar opens a short Google
  Form (kind, tab, what happened, optional team link, device), so players can answer without any account.
  The same questions exist as a GitHub issue form (`.github/ISSUE_TEMPLATE/feedback.yml`, labelled
  `feedback`) for people who'd rather file an issue; `feedback_url` in the app's secrets overrides the link.
- **My teams** (Team tab): name and save teams, then load or delete them later. They're kept in the
  visitor's own browser (localStorage), so there's no sign-up and nothing is stored on a server; the list is
  per browser and device, and the share link moves a team between devices. Storage sits behind one small
  interface (`ui/team_store.py`: `TeamStore`), so accounts can come later as a second backend without
  changing the Team tab. A built-in Streamlit component (no extra package) reads the browser's copy once per
  page load and writes the list back after each change; entries hold the share-link token, so loading one
  goes through the same checks as a pasted team.
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
