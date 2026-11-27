"""
build.py

Build teams around one Pokemon from the command line, the same way the app's
"Build a whole team around one Pokémon" does, and print them as Showdown pastes
with the reasons and ratings. Also prints how the Pokemon is played (the
Pokémon tab's summary), unless --no-summary.

    python scripts/build.py Baxcalibur
    python scripts/build.py Baxcalibur --mode hidden --teams 3
    python scripts/build.py Garganacl --format gen9championsbssregmc
    python scripts/build.py Baxcalibur --paste-only > teams.txt
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.formats import CURRENT, FORMATS  # noqa: E402
from src.recommend import MODES  # noqa: E402


def plain(text: str) -> str:
    """Drop the app's markdown bold."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def summary(core, name: str, dex, usage, fmt) -> list[str]:
    """How the core is played: rated record, partners, team styles, matchups, and a thin-data note."""
    from src.core_report import core_matchups, load_index, thin_data, thin_note, tournament_core
    from src.evaluate import load_tournament_teams
    species = dex.get_species(name)
    root = dex.sheet_id(species)
    form = core.battle_form(dex)
    out = [f"{form.name if form else name} ({fmt.label})",
           f"  Set: {core.item or 'no item'} · {core.ability} · {core.nature} · " + " / ".join(core.moves)]
    row = ((load_index(fmt.id) or {}).get("pokemon") or {}).get(root) or {}
    if row.get("rated"):
        won, exp = row["rated_won"] / row["rated"], row["rated_expected"] / row["rated"]
        out.append(f"  Last 30 days: brought in {row['rated']:,} rated games, won {won:.0%} "
                   f"(its players' ratings predicted {exp:.0%})")
    if row.get("partners"):
        out.append("  Usual partners: " + ", ".join(
            f"{(dex.get_species(p).name if dex.get_species(p) else p)} {v:.0%}" for p, v in row["partners"].items()))
    if row.get("styles"):
        out.append("  Its teams carry: " + ", ".join(f"{k} {v:.0%}" for k, v in row["styles"].items()))
    calcs = core_matchups(core, usage, dex, doubles=fmt.is_doubles)
    if calcs["beats"]:
        out.append("  Beats one-on-one: " + ", ".join(n for n, _ in calcs["beats"][:8]))
    if calcs["threats"]:
        out.append("  Beaten by: " + ", ".join(n for n, _ in calcs["threats"][:8]))
    thin = thin_data(root, usage.teammates)
    if thin:
        teams = load_tournament_teams(fmt.regulation, dex)
        mega = form is not None and form.is_mega
        tour = tournament_core(root, teams, dex, form.required_item if mega else None) if teams else None
        out.append("  " + plain(thin_note(form.name if mega else name, thin, tour["teams"] if tour else None,
                                          tour["players"] if tour else None, row.get("rated"),
                                          point_to_tab=False)))
    return out


def team_block(n: int, t, core_name: str, threats: list[str], dex, usage, fmt) -> list[str]:
    from src.core_report import answered
    from src.paste import export_paste
    from src.team_rating import WEAK_NOTE, details_line, is_weak, lenses, load_reference, score_line
    head = f"Team {n}" + (f" · {t.theme} team" if t.theme else "")
    seen = lenses(t.sets, dex, usage, t.chance, load_reference(fmt.regulation)) if t.chance is not None else None
    if t.percentile is not None:
        head += f" · {score_line(t.percentile)}"
    elif t.meta_score is not None:
        head += f" · vs meta {t.meta_score:+.2f}"
    out = [head, "=" * len(head)]
    details = details_line(seen, t.chance)
    if details and t.percentile is not None:
        out.append(f"Behind the score: {details}")
    from src.team_plan import plan_line
    plan = plan_line(t.sets, dex, fmt.is_doubles)
    if plan:
        out.append(f"Game plan: {plan}")
    if is_weak(seen):
        out.append(f"Warning: {WEAK_NOTE}")
    if threats:
        yes, no = answered(t.sets, threats, usage, dex, fmt.is_doubles)
        if yes or no:
            out.append(f"Answers {len(yes)} of the {len(yes) + len(no)} Pokémon that beat {core_name}"
                       + (f" (not {', '.join(no)})" if no else ""))
    out += [f"- {r}" for r in t.reasons]
    out += ["", export_paste(t.sets).strip(), ""]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("core", help="the Pokémon to build around, e.g. Baxcalibur")
    parser.add_argument("--format", default=CURRENT.id, choices=sorted(FORMATS))
    parser.add_argument("--mode", default="popular", choices=sorted(MODES),
                        help="recommendation style (default popular)")
    parser.add_argument("--teams", type=int, default=3, help="how many teams (default 3)")
    parser.add_argument("--with", dest="lock", action="append", default=[], metavar="POKEMON",
                        help="a Pokémon every team must include (repeat for more)")
    parser.add_argument("--without", dest="ban", action="append", default=[], metavar="POKEMON",
                        help="a Pokémon no team may use (repeat for more)")
    parser.add_argument("--no-summary", action="store_true", help="skip how the Pokémon is played")
    parser.add_argument("--paste-only", action="store_true", help="print only the Showdown pastes")
    args = parser.parse_args(argv)

    from src.builder import build_teams, core_set
    from src.core_report import core_matchups
    from src.dex import load_dex
    from src.matchup import build_archetypes
    from src.usage import load_usage

    fmt = FORMATS[args.format]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt.id)
    if usage is None:
        print(f"No usage data for {fmt.id}.", file=sys.stderr)
        return 1
    species = dex.get_species(args.core)
    if species is None:
        print(f"{args.core!r} isn't in {fmt.label}'s Pokédex.", file=sys.stderr)
        return 1
    core = core_set(species.name, dex, usage)
    if core is None:
        print(f"No set data for {species.name} in {fmt.label}.", file=sys.stderr)
        return 1
    teams = build_teams(core, dex, usage, doubles=fmt.is_doubles, mode=args.mode, alternatives=args.teams,
                        archetypes=build_archetypes(usage, dex, team_size=6), regulation=fmt.regulation,
                        lock=args.lock, ban=args.ban)
    if not teams:
        print(f"Couldn't build a full team around {species.name}.", file=sys.stderr)
        return 1
    if args.paste_only:
        from src.paste import export_paste
        # Showdown's teambuilder backup format: paste the whole thing into "Import from text"
        print("\n\n".join(f"=== [{fmt.id}] {species.name} {n} ===\n\n" + export_paste(t.sets).strip()
                           for n, t in enumerate(teams, 1)))
        return 0
    lines = [] if args.no_summary else summary(core, species.name, dex, usage, fmt) + [""]
    from src.core_report import core_advice, load_index, thin_data
    row = ((load_index(fmt.id) or {}).get("pokemon") or {}).get(dex.sheet_id(species)) or {}
    advice = core_advice(species.name, row, thin_data(dex.sheet_id(species), usage.teammates), args.mode)
    if advice:
        lines += [f"Tip: {advice}", ""]
    form = core.battle_form(dex)
    core_name = form.name if form else species.name
    threats = [n for n, _ in core_matchups(core, usage, dex, doubles=fmt.is_doubles)["threats"][:5]]
    lines.append(f"Teams around {core_name} ({MODES[args.mode]} style), ranked by team score")
    lines.append("")
    for n, t in enumerate(teams, 1):
        lines += team_block(n, t, core_name, threats, dex, usage, fmt)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
