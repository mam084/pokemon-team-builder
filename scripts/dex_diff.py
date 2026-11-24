#!/usr/bin/env python3
"""
dex_diff.py - what changed between two exported dex files, in plain lines.

Two uses, both run by the daily "Watch for a new regulation" workflow:

    python scripts/dex_diff.py drift --committed data/dex --fresh /tmp/dex [--github-output FILE]
        Exports Showdown's current data to --fresh and compares it with the committed dex, file by
        file (the export date ignored). Showdown edits a regulation in place when the game changes it
        (the Dec 2, 2026 balance patch: accuracy, learnsets, abilities), and the full data refresh
        only runs monthly, so a difference here starts it early. Writes changed=true/false.

    python scripts/dex_diff.py new --old data/dex/regmc.json --new data/dex/regmd.json
        What a new regulation adds to the last one: Pokémon, Megas, items, moves, abilities,
        and moves whose numbers changed. For the new-regulation pull request's description.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

IGNORED = {"generatedAt"}
# The move fields that change what the app computes (damage, Speed order, spread, priority).
MOVE_FIELDS = ("type", "category", "basePower", "accuracy", "priority", "target", "flags", "multihit",
               "hasSecondary", "recoil", "desc")


def _names(entries: dict, keys) -> list[str]:
    return sorted(entries[k].get("name", k) for k in keys)


def _short(names: list[str], limit: int = 25) -> str:
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def changes(old: dict, new: dict) -> list[str]:
    """Plain-language lines for what `new` changes relative to `old` (two dex files)."""
    out = []
    for section, label in (("species", "Pokémon"), ("items", "items"), ("moves", "moves"),
                           ("abilities", "abilities")):
        a, b = old.get(section, {}), new.get(section, {})
        added, removed = b.keys() - a.keys(), a.keys() - b.keys()
        if section == "species":
            megas = [k for k in added if b[k].get("isMega")]
            if megas:
                out.append(f"New Megas ({len(megas)}): {_short(_names(b, megas))}")
            added = [k for k in added if not b[k].get("isMega")]
        if added:
            out.append(f"New {label} ({len(added)}): {_short(_names(b, added))}")
        if removed:
            out.append(f"No longer legal, {label} ({len(removed)}): {_short(_names(a, removed))}")

    a, b = old.get("moves", {}), new.get("moves", {})
    for k in sorted(a.keys() & b.keys()):
        diffs = [f"{f} {a[k].get(f)!r} -> {b[k].get(f)!r}" for f in MOVE_FIELDS if a[k].get(f) != b[k].get(f)]
        if diffs:
            out.append(f"Move changed: {b[k]['name']}: " + "; ".join(diffs))
    a, b = old.get("abilities", {}), new.get("abilities", {})
    for k in sorted(a.keys() & b.keys()):
        if a[k].get("desc") != b[k].get("desc"):
            out.append(f"Ability changed: {b[k]['name']}: {b[k].get('desc')}")

    a, b = old.get("species", {}), new.get("species", {})
    learned = []
    for k in sorted(a.keys() & b.keys()):
        gained = set(b[k].get("learnset", [])) - set(a[k].get("learnset", []))
        lost = set(a[k].get("learnset", [])) - set(b[k].get("learnset", []))
        if gained or lost:
            moves = new.get("moves", {})
            words = [f"+{moves.get(m, {}).get('name', m)}" for m in sorted(gained)]
            words += [f"-{moves.get(m, {}).get('name', m)}" for m in sorted(lost)]
            learned.append(f"{b[k]['name']} ({', '.join(words)})")
        for f in ("baseStats", "types", "abilities"):
            if a[k].get(f) != b[k].get(f):
                out.append(f"Pokémon changed: {b[k]['name']}: {f} {a[k].get(f)} -> {b[k].get(f)}")
    if learned:
        out.append(f"Learnsets changed ({len(learned)} Pokémon): {_short(learned, 15)}")
    if old.get("rules") != new.get("rules"):
        out.append(f"Rules changed: {old.get('rules')} -> {new.get('rules')}")
    return out


def calc_unknown(old: dict, new: dict) -> list[str]:
    """New or changed abilities the damage calc and type chart never name: each is either harmless to the
    numbers (most aren't about damage) or a gap to fill in src/damage.py before trusting its calcs."""
    root = Path(__file__).resolve().parent.parent / "src"
    code = (root / "damage.py").read_text() + (root / "type_chart.py").read_text() + (root / "analysis.py").read_text()
    a, b = old.get("abilities", {}), new.get("abilities", {})
    touched = [k for k in b if k not in a or a[k].get("desc") != b[k].get("desc")]
    return sorted(b[k]["name"] for k in touched if f'"{k}"' not in code)


def _load(path: Path) -> dict:
    return {k: v for k, v in json.loads(path.read_text()).items() if k not in IGNORED}


def drift(committed: Path, fresh: Path) -> list[str]:
    """Lines describing every regulation whose fresh export differs from the committed one."""
    out = []
    for f in sorted(fresh.glob("*.json")):
        if f.name.endswith("_sprites.json"):
            continue
        old_path = committed / f.name
        if not old_path.exists():   # a new regulation: its switch adds the file (scripts/new_regulation.py)
            continue
        old, new = _load(old_path), _load(f)
        if old != new:
            out.append(f"## {f.stem}")
            out += [f"- {line}" for line in changes(old, new)] or ["- (fields the summary doesn't list)"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drift")
    d.add_argument("--committed", type=Path, required=True)
    d.add_argument("--fresh", type=Path, required=True)
    d.add_argument("--github-output", type=Path)
    n = sub.add_parser("new")
    n.add_argument("--old", type=Path, required=True)
    n.add_argument("--new", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "drift":
        lines = drift(args.committed, args.fresh)
        print("\n".join(lines) if lines else "The committed dex matches Showdown.")
        if args.github_output:
            with args.github_output.open("a") as f:
                f.write(f"changed={'true' if lines else 'false'}\n")
        return 0
    old, new = _load(args.old), _load(args.new)
    lines = changes(old, new)
    print("\n".join(f"- {line}" for line in lines) if lines else "- Nothing differs from the last regulation's dex.")
    unknown = calc_unknown(old, new)
    if unknown:
        print(f"- Not in the damage calc, check whether they change damage or Speed: {_short(unknown)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
