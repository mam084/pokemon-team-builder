"""
replay_parse.py

Turns a Pokemon Showdown battle log into a compact record. Pure Python, no
dependencies, so the fetch workflow can run it without the app's stack.

A record keeps what the analyses need and nothing else:

    id, format, uploadtime, rating          replay metadata
    players: {p1: {name, rating}, p2: ...}  ladder rating at the start, when shown
    winner: "p1" | "p2" | None, forfeit     result
    turns                                   number of turns
    preview: {p1: [species x6], p2: ...}    team preview
    brought: {p1: [species], p2: ...}       Pokemon that actually came out (<= 4)
    leads: {p1: [species x2], p2: ...}      the two on the field at the start
    mega: {p1: species | None, ...}         who Mega Evolved
    moves: {p1: {species: {move: uses}}}    every move used, by whom
    turn1: {p1: [[species, move, target]]}  first-turn choices
    faints: [[turn, side, species]]
    sheets: {p1: [{species, item, ability, moves}]}  open team sheets (Bo3), when present

Species names are taken from the details field (after nicknames), with the
Mega forme kept in mega and moves, and the base species used everywhere else
so a team's preview, bring and leads line up.
"""

from __future__ import annotations

from collections import defaultdict

PLAYERS = ("p1", "p2")


def _species(details: str) -> str:
    """'Kingambit, L50, M' -> 'Kingambit'."""
    return details.split(",")[0].strip()


def _base(species: str) -> str:
    """'Froslass-Mega' -> 'Froslass'; leaves other formes ('Arcanine-Hisui') alone."""
    for suffix in ("-Mega-X", "-Mega-Y", "-Mega-Z", "-Mega"):
        if species.endswith(suffix):
            return species[: -len(suffix)]
    return species


def _side(ident: str) -> str:
    """'p1a: Nick' -> 'p1'."""
    return ident.split(":")[0][:2]


def _slot(ident: str) -> str:
    """'p1a: Nick' -> 'p1a'."""
    return ident.split(":")[0].strip()


def parse_packed_team(packed: str) -> list[dict]:
    """Showdown's packed team format (used by |showteam|) -> [{species, item, ability, moves}]."""
    out = []
    for entry in packed.split("]"):
        fields = entry.split("|")
        if len(fields) < 5:
            continue
        nickname, species = fields[0], fields[1] or fields[0]
        out.append({"species": species, "item": fields[2], "ability": fields[3],
                    "moves": [m for m in fields[4].split(",") if m], "nickname": nickname})
    return out


def parse_log(log: str, meta: dict | None = None) -> dict:
    meta = meta or {}
    rec: dict = {
        "id": meta.get("id"), "format": meta.get("format") or meta.get("formatid"),
        "uploadtime": meta.get("uploadtime"), "rating": meta.get("rating"),
        "players": {p: {"name": None, "rating": None} for p in PLAYERS},
        "winner": None, "forfeit": False, "turns": 0,
        "preview": {p: [] for p in PLAYERS}, "brought": {p: [] for p in PLAYERS},
        "leads": {p: [] for p in PLAYERS}, "mega": {p: None for p in PLAYERS},
        "moves": {p: defaultdict(lambda: defaultdict(int)) for p in PLAYERS},
        "turn1": {p: [] for p in PLAYERS}, "faints": [], "sheets": {},
    }
    on_field: dict[str, str] = {}      # slot -> base species
    names: dict[str, str] = {}         # player name -> side
    turn = 0
    for line in log.splitlines():
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "player" and len(parts) >= 4 and parts[2] in PLAYERS and parts[3]:
            p = parts[2]
            rec["players"][p]["name"] = parts[3]
            names[parts[3]] = p
            if len(parts) >= 6 and parts[5].strip().isdigit():
                rec["players"][p]["rating"] = int(parts[5])
        elif kind == "poke" and len(parts) >= 4 and parts[2] in PLAYERS:
            rec["preview"][parts[2]].append(_base(_species(parts[3]).replace("-*", "")))
        elif kind == "showteam" and len(parts) >= 4 and parts[2] in PLAYERS:
            rec["sheets"][parts[2]] = parse_packed_team("|".join(parts[3:]))
        elif kind in ("switch", "drag", "replace") and len(parts) >= 4:
            p, slot = _side(parts[2]), _slot(parts[2])
            species = _base(_species(parts[3]))
            on_field[slot] = species
            if p in PLAYERS:
                if species not in rec["brought"][p]:
                    rec["brought"][p].append(species)
                if turn == 0 and species not in rec["leads"][p] and len(rec["leads"][p]) < 2:
                    rec["leads"][p].append(species)
        elif kind == "detailschange" and len(parts) >= 4:
            p, species = _side(parts[2]), _species(parts[3])
            if p in PLAYERS and "-Mega" in species:
                rec["mega"][p] = species
        elif kind == "-mega" and len(parts) >= 4:
            p = _side(parts[2])
            if p in PLAYERS and rec["mega"][p] is None:
                rec["mega"][p] = f"{on_field.get(_slot(parts[2]), parts[3])}-Mega"
        elif kind == "turn" and len(parts) >= 3:
            turn = int(parts[2]) if parts[2].isdigit() else turn + 1
            rec["turns"] = turn
        elif kind == "move" and len(parts) >= 4:
            p, slot = _side(parts[2]), _slot(parts[2])
            if p not in PLAYERS:
                continue
            species = on_field.get(slot, "?")
            move = parts[3]
            # moves called by another move ([from]) aren't choices
            if any(x.startswith("[from]") for x in parts[4:]):
                continue
            rec["moves"][p][species][move] += 1
            if turn == 1:
                target = on_field.get(_slot(parts[4]), "") if len(parts) > 4 and ":" in parts[4] else ""
                rec["turn1"][p].append([species, move, target])
        elif kind == "faint" and len(parts) >= 3:
            p, slot = _side(parts[2]), _slot(parts[2])
            if p in PLAYERS:
                rec["faints"].append([turn, p, on_field.get(slot, "?")])
        elif kind == "win" and len(parts) >= 3:
            rec["winner"] = names.get(parts[2])
        elif kind in ("-message", "message") and len(parts) >= 3 and "forfeited" in parts[2]:
            rec["forfeit"] = True
    rec["moves"] = {p: {s: dict(m) for s, m in rec["moves"][p].items()} for p in PLAYERS}
    return rec


def is_usable(rec: dict) -> bool:
    """A finished doubles game with both team previews."""
    return (rec["winner"] in PLAYERS and all(len(rec["preview"][p]) >= 4 for p in PLAYERS)
            and all(rec["leads"][p] for p in PLAYERS))
