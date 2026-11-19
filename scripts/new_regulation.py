#!/usr/bin/env python3
"""
new_regulation.py - notice a new Pokémon Champions regulation and switch the app to it.

    python scripts/new_regulation.py check --ps ../pokemon-showdown
        Lists Champions VGC / BSS regulations Showdown has that src/formats.py doesn't.
        Reads Showdown's config/formats.ts, so no build is needed. Run daily by the
        "Watch for a new regulation" workflow, which opens an issue when it finds one.

    python scripts/new_regulation.py add --vgc gen9championsvgc2026regmd --start 2026-12-03 \\
        [--bss gen9championsbssregmd] [--limitless M-D] [--active "Dec 3, 2026 – Mar 2027"]
        Adds the new formats to src/formats.py as current (VGC with its Bo3 ladder feeding the
        learned models, BSS too if given), marks the old ones past, points DEFAULT_FORMAT at the
        new VGC format and records the old one as `previous` (its sets fill in early on).

After `add`, push: the Refresh data workflow runs (src/formats.py changed) and exports the new
dex; replays start arriving with the next fetch; until Smogon publishes the regulation's first
monthly stats, usage comes from its replays (src/replay_usage.py). README: "When a new
regulation starts".
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FORMATS_PY = ROOT / "src" / "formats.py"
NAME = re.compile(r'name:\s*"\[Gen 9 Champions\] (VGC (\d{4}) Reg ([A-Z])-([A-Z]{1,3})|BSS Reg ([A-Z])-([A-Z]{1,3}))"')


def to_id(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def showdown_formats(formats_ts: str) -> list[dict]:
    """Champions VGC (not Bo3) and BSS regulation formats named in Showdown's config/formats.ts."""
    out = []
    for m in NAME.finditer(formats_ts):
        if m.group(2):
            year, a, b = m.group(2), m.group(3), m.group(4)
            out.append({"style": "vgc", "id": f"gen9championsvgc{year}reg{a}{b}".lower(),
                        "regulation": f"reg{a}{b}".lower(), "label": f"{a}-{b}"})
        else:
            a, b = m.group(5), m.group(6)
            out.append({"style": "bss", "id": f"gen9championsbssreg{a}{b}".lower(),
                        "regulation": f"reg{a}{b}".lower(), "label": f"{a}-{b}"})
    return out


def new_regulations(found: list[dict], known: set[str]) -> dict[str, list[dict]]:
    """{regulation: its Showdown formats} for regulations src/formats.py has no format for."""
    from src.formats import FORMATS
    have = {f.regulation for f in FORMATS.values()} | known
    out: dict[str, list[dict]] = {}
    for f in found:
        if f["regulation"] not in have:
            out.setdefault(f["regulation"], []).append(f)
    return out


def check(ps: Path) -> dict[str, list[dict]]:
    found = showdown_formats((ps / "config" / "formats.ts").read_text())
    new = new_regulations(found, set())
    for reg, fmts in new.items():
        vgc = next((f["id"] for f in fmts if f["style"] == "vgc"), None)
        bss = next((f["id"] for f in fmts if f["style"] == "bss"), None)
        label = fmts[0]["label"]
        cmd = "python scripts/new_regulation.py add" + (f" --vgc {vgc}" if vgc else "") + \
            (f" --bss {bss}" if bss else "") + f" --limitless {label} --start YYYY-MM-DD"
        print(f"New regulation on Showdown: Reg {label} ({', '.join(f['id'] for f in fmts)})")
        print(f"  switch the app on its start day: {cmd}")
    if not new:
        print("No new Champions regulation on Showdown.")
    return new


def _entry(fid: str, label: str, regulation: str, game_type: str, pick: int, active: str, start: str,
           replays: tuple[str, ...] = (), limitless: str = "", previous: str = "") -> str:
    lines = [f'            id="{fid}",', f'            label="{label}",', f'            regulation="{regulation}",',
             f'            game_type="{game_type}",', f"            pick={pick},", f'            active="{active}",',
             "            current=True,", f'            start="{start}",']
    if replays:
        lines.append(f"            replays=({', '.join(repr(r).replace(chr(39), chr(34)) for r in replays)}),")
    if limitless:
        lines.append(f'            limitless="{limitless}",')
    if previous:
        lines.append(f'            previous="{previous}",')
    return "        Format(\n" + "\n".join(lines) + "\n        ),\n"


def add_formats(text: str, vgc: str, start: str, bss: str = "", limitless: str = "", active: str = "") -> str:
    """src/formats.py's text with the new regulation added and made the default."""
    from src.formats import DEFAULT_FORMAT, FORMATS
    m = re.search(r"reg([a-z]{1,3})$", vgc)
    if not m:
        raise SystemExit(f"{vgc}: expected a format id ending in reg<letters>")
    regulation = f"reg{m.group(1)}"
    if any(f.regulation == regulation for f in FORMATS.values()):
        raise SystemExit(f"{regulation} is already in src/formats.py")
    letters = m.group(1).upper()
    code = limitless or (f"{letters[0]}-{letters[1:]}" if len(letters) > 1 else letters)
    year = re.search(r"vgc(\d{4})", vgc).group(1)
    day = date.fromisoformat(start)
    active = active or f"{day:%b} {day.day}, {day.year} –"

    # the old current formats become past
    for f in FORMATS.values():
        if not f.current:
            continue
        past = f.label[:-1] + ", past)" if f.label.endswith(")") else f.label + " (past)"
        block = re.search(rf'(Format\(\n\s*id="{re.escape(f.id)}",.*?\n\s*\),)', text, re.S)
        if block:
            new_block = block.group(1).replace(f'label="{f.label}"', f'label="{past}"')
            new_block = re.sub(r"\n\s*current=True,", "", new_block)
            text = text.replace(block.group(1), new_block)

    entries = _entry(vgc, f"VGC {year} Reg {code} (Doubles)", regulation, "doubles", 4, active, start,
                     replays=(vgc, vgc + "bo3"), limitless=code, previous=DEFAULT_FORMAT)
    if bss:
        old_bss = next((f.id for f in FORMATS.values() if f.current and not f.is_doubles), "")
        entries += _entry(bss, f"Battle Stadium Singles Reg {code}", regulation, "singles", 3, active, start,
                          previous=old_bss)
    text = text.replace("    for f in [\n", "    for f in [\n" + entries, 1)
    text = re.sub(r'DEFAULT_FORMAT = "[^"]+"', f'DEFAULT_FORMAT = "{vgc}"', text, count=1)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--ps", type=Path, default=ROOT.parent / "pokemon-showdown")
    c.add_argument("--github-output", type=Path, help="append new=<regulations> for a workflow step")
    a = sub.add_parser("add")
    a.add_argument("--vgc", required=True)
    a.add_argument("--bss", default="")
    a.add_argument("--start", required=True, help="first day, YYYY-MM-DD")
    a.add_argument("--limitless", default="")
    a.add_argument("--active", default="")
    args = ap.parse_args()
    if args.cmd == "check":
        new = check(args.ps)
        if args.github_output:
            with args.github_output.open("a") as f:
                f.write(f"new={' '.join(sorted(new))}\n")
        return 0
    FORMATS_PY.write_text(add_formats(FORMATS_PY.read_text(), args.vgc, args.start, args.bss, args.limitless,
                                      args.active))
    print(f"src/formats.py: {args.vgc} is now the default; push to refresh the dex and start fetching replays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
