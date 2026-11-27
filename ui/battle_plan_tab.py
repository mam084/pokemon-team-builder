"""
battle_plan_tab.py - one opponent in detail: the six you see at team preview (tapped, typed or pasted from an
open team sheet), your win chance, what to bring and lead, turn 1, and who answers what.

Shares the meta teams, the learned win model and the pairing heatmap with the Matchups tab (ui/matchups_tab.py).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analysis import build_members, mega_variants
from src.bring_model import load_model as load_bring_model
from src.bring_model import pick as bring_pick
from src.gameplan import game_plan
from src.match_model import explain, predict_match, team_side
from src.matchup import best_attack, best_variant, opponent_members, team_score, verdict
from src.replays import load_summary, usual_picks
from src.roles import meta_roles, role_text
from ui.common import sprite, type_badges, no_usage
from ui.matchups_tab import (archetypes_for, chance_verdict, learned_meta_sides, match_check, pair_heatmap,
                             swap_engine_for, win_text)

@st.cache_data(show_spinner=False, ttl=3600)
def bring_model_for(regulation: str) -> dict | None:
    """The replay-learned bring model, only if it beat both baselines on held-out games."""
    model = load_bring_model(regulation)
    if not model:
        return None
    r = model["results"]["bring"]
    return model if r["learned"][0] > max(r["usual picks"][0], r["damage calcs"][0]) else None


@st.cache_data(show_spinner=False, ttl=3600)
def replay_summary(fmt_id: str) -> dict | None:
    return load_summary(fmt_id)



def battle_plan_tab(fmt_id, team, members, dex, usage, fmt) -> None:
    """One opponent, in detail: win chance, what to bring and lead, turn 1, who answers what."""
    if usage is None:
        no_usage(fmt, "The battle plan needs usage stats for this format.")
        return
    archetypes = archetypes_for(fmt_id)
    doubles = fmt.is_doubles
    if not members:
        st.info("Add Pokémon on the **Team** tab, then enter the six you see at team preview here.")
        return
    names = [a.name for a in archetypes]
    if not names:
        st.info("Not enough usage data to build meta teams.")
        return
    pick = st.selectbox("Who are you facing?", [FACING] + names, key="detail_pick",
                        format_func=lambda x: x if x == FACING else f"Common meta team: {x}",
                        help="Enter the six you see at team preview, or practice against a common meta team.")
    their_side = None
    if pick == FACING:
        facing = facing_archetype(dex, usage)
        if facing is None:
            return
        arch, their_sets, filled = facing
        theirs = build_members(their_sets, dex, evolve=0 if their_sets[0].is_mega(dex) else None)
        model_now = learned_meta_sides(fmt_id)[0]
        if model_now is not None:
            their_side = team_side(theirs, their_sets, dex, usage, swap_engine_for(fmt_id))
        pick = "their team"
        if filled:
            spread = [n for n, parts in filled.items() if parts == ["nature and stat points"]]
            other = {n: parts for n, parts in filled.items() if parts != ["nature and stat points"]}
            bits = ([f"nature and stat points for {', '.join(spread)}"] if spread else []) + \
                   [f"{', '.join(parts)} for {n}" for n, parts in other.items()]
            st.caption("Not on their sheet, so taken from the most common set: " + "; ".join(bits) + ".")
    else:
        arch = archetypes[names.index(pick)]
        theirs = opponent_members(arch.members, usage, dex)
    cards = "".join(
        f"<div class='opp-card'><img src='{sprite(opp.form, dex)}' alt=''>"
        f"<div class='opp-name'>{opp.label}</div><div>{type_badges(opp.form.types)}</div>"
        f"<div class='opp-item'>{opp.pset.item or 'No item'}</div>"
        f"<div class='opp-meta'>{role_text(meta_roles(arch.members[i], usage, dex, doubles), 2)}</div></div>"
        for i, opp in enumerate(theirs))
    st.markdown(f"<div class='opp-grid'>{cards}</div>", unsafe_allow_html=True)
    notes = []
    if arch.trick_room:
        notes.append("This team sets Trick Room, so slower Pokémon get the Speed bonus.")
    if arch.weather:
        notes.append(f"Calcs are done in {arch.weather}, which this team sets.")
    if notes:
        st.caption(" ".join(notes))

    if members:
        variants = mega_variants(team, dex)
        # The bring-4 comes from the replay-learned model when it predicts real choices better
        # than both the calcs and players' usual picks (data/evaluation/<reg>_bring_model.json);
        # the Mega choice follows the bring, so the Pokémon told to Mega Evolve is always brought.
        bring_model = bring_model_for(fmt.regulation)
        use_model = bool(bring_model) and fmt.pick == 4 and len(members) > 4
        def mega_of(ms):
            return next((m.label for m in ms if m.form.is_mega), None)

        # the Mega always comes (who Mega Evolves is chosen by calcs); the model picks the rest
        picker = (lambda ms, mx: bring_pick(bring_model, ms, theirs, mx, dex, keep=mega_of(ms))[0]) \
            if use_model else None
        who, matrix, picks, picked = best_variant(variants, theirs, arch.trick_room, doubles, arch.weather,
                                                  fmt.pick, picker)
        members_now = next(ms for _, ms in variants if [m.label for m in ms] == list(matrix.index))
        score = team_score(matrix)
        model, sides = learned_meta_sides(fmt_id)
        pros = cons = []
        if model is not None and (their_side is not None or pick in names):
            mine = team_side(members_now, team, dex, usage, swap_engine_for(fmt_id))
            theirs_side = their_side if their_side is not None else sides[names.index(pick)]
            p_win = predict_match(model, mine, theirs_side)
            pros, cons = explain(model, mine, theirs_side)
            st.markdown(f"**Your team vs {pick}: about {p_win:.0%} to win ({chance_verdict(p_win).lower()})**")
        else:
            chance = win_text(score, match_check(fmt.regulation), "team vs team (all 6)")
            st.markdown(f"**Your team vs {pick}: {verdict(score).lower()}**" + (f" ({chance})" if chance else ""))

        plan_picks, bring_source = picks, ("replays" if use_model else "calcs")
        plan = game_plan(members_now, theirs, matrix, plan_picks, dex, doubles, arch.trick_room, arch.weather)
        plan.bring_source = bring_source
        plan.calc_lead = list(plan.lead)  # the calcs' lead against this team, before replays override it
        summary = replay_summary(fmt_id)
        if summary:
            label = {p.species: m.label for p, m in zip(team, members_now)}
            # their likely leads: what ladder players lead with (beats the calc guess on replays)
            their_sets = [o.pset for o in theirs if o.pset is not None]
            their_label = {p.species: o.label for p, o in zip(their_sets, [o for o in theirs if o.pset])}
            _, their_lead = usual_picks(summary, [p.species for p in their_sets])
            plan.their_leads = [their_label.get(s, s) for s in their_lead]
            plan.their_leads_source = "replays"
            if bring_source == "replays":
                r = bring_model["results"]["lead"]
                if r["learned"][0] > r["usual picks"][0]:  # the model's own leads test best
                    plan.lead = bring_pick(bring_model, members_now, theirs, matrix, dex,
                                           keep=mega_of(members_now))[1]
                    if not set(plan.lead) <= set(plan_picks):
                        plan.lead = [x for x in plan.lead if x in plan_picks][:2]
                else:  # players' usual leads among the four
                    _, lead_species = usual_picks(summary, [p.species for p, m in zip(team, members_now)
                                                            if m.label in plan_picks])
                    plan.lead = [label.get(s, s) for s in lead_species]
                plan.back = [b for b in plan.bring if b not in plan.lead]
        mega_name = None
        if len(variants) > 1 and who:
            form = dex.get_species(who)
            mega_name = form.base_species if form is not None else who
        game_plan_box(plan, mega_name)
        turn1_box(plan, members_now, theirs, fmt_id)
        playbook_box(theirs, members_now, dex, usage, fmt)

        answers = []
        for opp in theirs:
            col = matrix[opp.label]
            best = col.idxmax()
            mine_m = next(m for m in members_now if m.label == best)
            pct, move = best_attack(mine_m, opp, doubles, arch.weather)
            good = col.max() >= 0.5
            answers.append({"their Pokémon": opp.label, "your best answer": best if good else "none",
                            "key hit": f"{move} {pct:.0f}%" if good and move else "—"})
        st.markdown("**Who answers what**")
        st.dataframe(pd.DataFrame(answers), hide_index=True, width="stretch")
        with st.expander("Every pairing, and what moves the win chance"):
            st.plotly_chart(pair_heatmap(matrix), width="stretch")
            st.caption("Damage calcs both ways for each pair: blue = your Pokémon (row) wins it, red = theirs "
                       "(column) does.")
            if pros or cons:
                pts = lambda items: ", ".join(f"{g} ({v:+.0f})" for g, v in items)  # noqa: E731
                st.markdown("  \n".join(x for x in [f"**Helping you:** {pts(pros)}" if pros else "",
                                                     f"**Against you:** {pts(cons)}" if cons else ""] if x))
                st.caption("Points of win chance, from the model learned on real tournament matches. **Damage "
                           "calcs**: how your Pokémon and theirs hit each other. **Speed**: who moves first, "
                           "including Trick Room and Tailwind fit. **Bulk**: average defenses. The rest are support tools (Encore, Fake Out...). "
                           "How popular your Pokémon are doesn't count: we tested it and it didn't help predict "
                           "real results.")


FACING = "A team you're facing (enter its six)…"


PICK, PASTE = "Pick their six", "Paste their team sheet"
QUICK_PICKS = 18


def _quick_to_team(common: list[str]) -> None:
    """Pills changed: keep the typed-in picks, swap the common ones for what's tapped now (six at most)."""
    tapped = st.session_state.get("opp_quick") or []
    kept = [n for n in st.session_state.get("opp_team", []) if n not in common or n in tapped]
    st.session_state["opp_team"] = (kept + [n for n in tapped if n not in kept])[:6]


def facing_archetype(dex, usage):
    """The team you're facing, as (Archetype, sets in Mega-first order, {species: parts filled in}).
    Picked by name, each gets its most common set; pasted (an open team sheet or a full Showdown paste),
    it keeps their real items, abilities and moves, and only what the sheet leaves out comes from the
    most common set. With two or more Mega Stones you say which one Mega Evolves. None until there are
    two Pokémon to plan against."""
    from src.matchup import Archetype, _label
    from src.opponent import mega_first, sets_from_sheet, style_of
    sheet = usage.team_sheet_usage(dex)
    how = st.segmented_control("Their team", [PICK, PASTE], default=PICK, key="opp_input",
                               help="Bo3 and tournament games show open team sheets: paste theirs to plan "
                                    "against their real items, abilities and moves.") or PICK
    filled: dict[str, list[str]] = {}
    if how == PASTE:
        text = st.text_area("Their team sheet", key="opp_paste", height=180,
                            placeholder="Paste their open team sheet or Showdown export…")
        sets, filled, warnings = sets_from_sheet(text, dex, usage) if text.strip() else ([], {}, [])
        for w in warnings:
            st.caption(f"⚠ {w}")
        if len(sets) < 2:
            st.caption("Paste at least two of their Pokémon to see the plan.")
            return None
    else:
        # Team preview is on a timer and typing six names on a phone is slow: the most-used Pokémon are one
        # tap each. The multiselect below stays the record (opp_team); the pills just add and remove.
        common = list(sheet)[:QUICK_PICKS]
        st.session_state["opp_quick"] = [n for n in st.session_state.get("opp_team", []) if n in common]
        st.pills("Quick add (most common first)", common, selection_mode="multi", key="opp_quick",
                 on_change=_quick_to_team, args=(common,), label_visibility="visible",
                 help="The most-used Pokémon on ladder teams. Anyone else: type below.")
        picked = st.multiselect("Their six (from team preview)", list(sheet), key="opp_team", max_selections=6,
                                placeholder="Type to search…",
                                help="Each gets its most common set. Sorted by how often it's on ladder teams.")
        if len(picked) < 2:
            st.caption("Pick at least two of their Pokémon to see the plan.")
            return None
        sets = [p for p in (usage.popular_set(n, dex) for n in picked) if p is not None]
        if len(sets) < 2:
            return None
    stones = [p.species for p in sets if p.is_mega(dex)]
    mega = None
    if len(stones) > 1:
        mega = st.selectbox("Which one Mega Evolves?", stones, key="opp_mega",
                            help="Only one Mega per battle; the others play in their base forme.")
    sets = mega_first(sets, dex, mega)
    if len(sets) >= 4 and not st.session_state.get("_counted_bp"):
        from src.usage_counts import count
        count("battle plan vs a team")   # once a visit, when there's a real team to plan against
        st.session_state["_counted_bp"] = True
    # usage-entry names (a Mega by its Mega name) for roles and popularity
    names = [(p.battle_form(dex).name if i == 0 and p.is_mega(dex) else p.species) for i, p in enumerate(sets)]
    if how == PASTE:
        trick_room, weather, tags = style_of(sets, dex)
        name = f"{' + '.join(dict.fromkeys(tags[:2])) or 'Goodstuffs'} ({names[0]} + {names[1]})"
    else:
        name, trick_room, weather = _label(names, usage, dex)
    pop = sum(sheet.get(n, 0) for n in names) / len(names)
    return Archetype("Their team: " + name.split(" (")[0], names, round(pop, 1), trick_room, weather), sets, filled


def playbook_box(theirs, my_members, dex, usage, fmt) -> None:
    """The Playbook's findings for the styles this opponent sets up: plays that worked, and who on your
    team can make them (ui/playbook_tab.py has the full evidence). Setters are matched on the forme each
    opponent battles as (a Mega Charizard Y sets Sun; Mega X's Dragon Dance sets don't count for it)."""
    from src.playbook import STYLES, team_tools
    from ui.playbook_tab import _book, _name, _setters, _verdict, _who
    book = _book(fmt.id)
    if not book:
        return
    setters = _setters(fmt.id)

    def form_name(n: str) -> str:
        f = dex.get_species(n)
        return f.name if f is not None else n
    battling = {o.form.name: o.label for o in theirs}
    tools = team_tools(my_members)
    blocks, styles = [], []
    for style in STYLES:
        forms = {form_name(n) for n in setters.get(style, set())}
        who_sets = sorted({battling[f] for f in battling if f in forms})
        data = book["styles"].get(style)
        if not who_sets or not data:
            continue
        styles.append(style)
        good = [c for c in data["choices"] if _verdict(c) == "worked"]
        bad = [c for c in data["choices"] if _verdict(c) == "backfired"]
        rows = []
        for c in good[:3]:
            w = _who(c["choice"], tools)
            who = "" if w is None else (f" · yours: {', '.join(w)}" if w else " · your team can't")
            rows.append(f"- ✓ {_name(c['choice'])}: **{c['edge']:+.0f}** points{who}")
        if not good:
            rows.append("- No play clearly won more")
        if bad:
            rows.append(f"- ✗ Avoid {_name(bad[-1]['choice']).lower()}: **{bad[-1]['edge']:+.0f}** points")
        blocks.append(f"**Against their {style}** ({', '.join(who_sets)})\n\n" + "\n".join(rows))
    if blocks:
        with st.expander(f"From the Playbook: plays that won more against their {', '.join(styles)}"):
            st.markdown("\n\n".join(blocks))
            st.caption("Points of win chance above what the players' ratings predicted, against players who could "
                       "have made the same play and didn't. Associations, not proof: the Playbook tab has the details.")


def game_plan_box(plan, mega: str | None) -> None:
    """The plan for this matchup in a few short lines; how each part was chosen sits in one caption."""
    with st.container(border=True):
        st.markdown("**Game plan**")
        usual = plan.bring_source == "replays"
        lines = [f"**{'Players usually bring' if usual else 'Bring'}:** {', '.join(plan.bring)}"
                 + (f" · Mega Evolve {mega}" if mega else ""),
                 f"**{'Usual lead' if usual else 'Lead'}:** {' + '.join(plan.lead)}"
                 + (f" · **Back:** {', '.join(plan.back)}" if plan.back else ""),
                 (f"**On damage calcs against this team:** {' + '.join(plan.calc_lead)}"
                  if getattr(plan, "calc_lead", None) and plan.bring_source == "replays"
                  and set(plan.calc_lead) != set(plan.lead) else ""),
                 f"**They usually lead:** {' + '.join(plan.their_leads)}" if plan.their_leads else "",
                 f"**Your strongest piece:** {plan.strongest} ({plan.strongest_why})" if plan.strongest else ""]
        if plan.watch_out:
            lines.append("**Watch out for:** " + "; ".join(
                f"{w['pokemon']} ({w['hit']}; {w['your best']})" for w in plan.watch_out))
        st.markdown("  \n".join(line for line in lines if line))
        order, prev = [], None
        for r in plan.speed:
            name = f"**{r['pokemon']}**" if r["side"] == "yours" else r["pokemon"]
            sep = "" if prev is None else (" = " if r["speed"] == prev else " › ")
            order.append(f"{sep}{name} {r['speed']}")
            prev = r["speed"]
        st.caption("Speed (yours in bold, with each set's Stat Points and nature): " + "".join(order)
                   + (f". {plan.speed_note}" if plan.speed_note else ""))
        st.caption(("Bring and lead: what real players with your Pokémon choose against a team like this, "
                    "learned from ladder replays; it leans on your own team more than on theirs, so similar "
                    "opponents often get the same lead. It's a starting point, not a proven edge: players whose "
                    "choices matched it won no more than their ratings predicted (labs/bring_value_lab.py). "
                    "The calcs' lead is shown when it differs. "
                    if plan.bring_source == "replays" else "Bring and lead: from damage calcs against this team. ")
                   + "Their leads: what players with their six usually lead.")


@st.cache_data(show_spinner=False)
def turn1_data(fmt_id: str) -> dict:
    from src.replays import load_turn1
    data = load_turn1(fmt_id)
    return data["pokemon"] if data else {}


def turn1_box(plan, members_now, theirs, fmt_id: str) -> None:
    """Turn 1 for each of your leads: what players clicked against their likely leads (or overall)."""
    table = turn1_data(fmt_id)
    if not table or not plan.lead:
        return
    species_of = {m.label: m.pset.species for m in members_now if m.pset is not None}
    their_species = {o.label: o.pset.species for o in theirs if o.pset is not None}
    their_leads = [their_species.get(x, x) for x in (plan.their_leads or [])]
    lines = []
    for lead in plan.lead:
        row = table.get(species_of.get(lead, lead))
        if not row:
            continue
        vs = [(t, row["vs"][t]) for t in their_leads if t in row.get("vs", {})]
        if vs:
            t, cell = max(vs, key=lambda x: x[1]["n"])
            moves, against = cell["moves"], f"against {t} ({cell['n']:,} games)"
        else:
            moves, against = row["all"], f"in all its leads ({row['n']:,} games)"
        lines.append(f"**{lead}:** " + ", ".join(f"{m} {s:.0%}" for m, s in moves) + f" <span class='rec-sub'>{against}</span>")
    if lines:
        with st.container(border=True):
            st.markdown("**Turn 1: what players click**  \n" + "  \n".join(lines), unsafe_allow_html=True)
            st.caption("From the last 30 days of ladder and Bo3 replays: the first move each lead used, against "
                       "their likely lead when there are enough games. It's what players do, not a tested "
                       "best move; the Playbook below says which plays won more against each style.")
