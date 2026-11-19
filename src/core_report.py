"""
core_report.py

What real players do with one Pokemon, for the builder's "Build around" screen: the evidence you'd
otherwise look up on Pikalytics, Pokémon Zone or Limitless before building around a core.

- replay_index: from the last 30 days of ladder and Bo3 replays (scripts/summarize_replays.py writes
  it to data/replays/summary/<format>_cores.json, so the app never loads replays): for each Pokemon
  on a team sheet, games on team preview, games brought and won, the win rate the two players'
  ratings predicted for those games (Elo), the same for games where it Mega Evolved, its most common
  partners, the highest-rated winning teams, and the moves and items on Bo3 open team sheets.
- tournament_core: the tournament teams that ran it (best finishes first), their combined record,
  and the natures and moves on those sheets.
- core_matchups: damage calcs for the core alone against the most-used Pokemon: what it beats
  one-on-one and what beats it (src/matchup.threat_report), and which of those a built team answers.

Win rates here are descriptive, not a verdict: one Pokemon's games are a few hundred at most, and
the player matters more than the team (README, "A learned model of who wins"). So the replay line
shows actual vs rating-predicted wins with the sample size, never a bare win rate.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.dex import Dex, to_id

SUMMARY_DIR = Path(__file__).resolve().parent.parent / "data" / "replays" / "summary"
DAYS = 30            # same window as the teammate model: older replays stopped helping as the meta moved
TOP_PARTNERS = 8
TOP_TEAMS = 3
MIN_TEAM_RATING = 1300   # "proven" ladder teams: won, by a player rated at least this


def _expected(own: float | None, opp: float | None) -> float | None:
    if not own or not opp:
        return None
    return 1.0 / (1.0 + 10 ** ((opp - own) / 400.0))


def replay_index(records: list[dict], dex: Dex, days: int = DAYS) -> dict:
    """{sheet id: stats} from replays (see the module docstring). Forfeits don't count toward wins."""
    from src.replay_parse import PLAYERS
    stamped = [r for r in records if r.get("uploadtime")]
    if not stamped:
        return {}
    end = max(r["uploadtime"] for r in stamped)
    start = end - days * 86400
    root_cache: dict[str, str | None] = {}

    def root(name: str) -> str | None:
        if name not in root_cache:
            s = dex.get_species(name)
            root_cache[name] = dex.sheet_id(s) if s is not None else None
        return root_cache[name]

    stats: dict[str, dict] = defaultdict(lambda: {
        "previews": 0, "brought": 0, "won": 0, "rated": 0, "rated_won": 0, "rated_expected": 0.0,
        "mega": 0, "mega_won": 0, "mega_rated": 0, "mega_rated_won": 0, "mega_expected": 0.0,
        "partners": Counter(), "seen": set(), "teams": [], "sheets": 0, "moves": Counter(), "items": Counter()})
    for r in stamped:
        if r["uploadtime"] < start:
            continue
        day = datetime.fromtimestamp(r["uploadtime"], timezone.utc).strftime("%Y-%m-%d")
        for p in PLAYERS:
            q = "p2" if p == "p1" else "p1"
            roots = [x for x in (root(sp) for sp in r["preview"][p]) if x]
            brought = {x for x in (root(sp) for sp in r["brought"].get(p) or []) if x}
            mega = r.get("mega", {}).get(p)
            mega_root = root(mega) if mega else None
            won = r["winner"] == p
            counted = not r.get("forfeit")
            own, opp = r["players"][p].get("rating"), r["players"][q].get("rating")
            exp = _expected(own, opp)
            sheet = {root(s["species"]): s for s in (r.get("sheets") or {}).get(p) or [] if root(s["species"])}
            team_key = ((r["players"][p].get("name") or "").lower(), frozenset(roots))
            for x in set(roots):
                s = stats[x]
                s["previews"] += 1
                if team_key not in s["seen"]:   # partners: each player's team once, not every game
                    s["seen"].add(team_key)
                    s["partners"].update(y for y in set(roots) if y != x)
                if x in sheet:
                    s["sheets"] += 1
                    s["moves"].update(to_id(m) for m in sheet[x].get("moves") or [])
                    if sheet[x].get("item"):
                        s["items"][to_id(sheet[x]["item"])] += 1
                if x not in brought or not counted:
                    continue
                s["brought"] += 1
                s["won"] += won
                if exp is not None:
                    s["rated"] += 1
                    s["rated_won"] += won
                    s["rated_expected"] += exp
                if mega_root == x:
                    s["mega"] += 1
                    s["mega_won"] += won
                    if exp is not None:
                        s["mega_rated"] += 1
                        s["mega_rated_won"] += won
                        s["mega_expected"] += exp
                if won and (own or 0) >= MIN_TEAM_RATING:
                    s["teams"].append((own, day, r["format"].endswith("bo3"), mega, r["preview"][p]))
    out = {}
    for x, s in stats.items():
        if s["previews"] < 5:
            continue
        seen, teams = set(), []
        for own, day, bo3, mega, preview in sorted(s["teams"], key=lambda t: -t[0]):
            key = frozenset(root(sp) for sp in preview)
            if key in seen:
                continue
            seen.add(key)
            teams.append({"rating": own, "date": day, "bo3": bo3, "mega": mega, "team": preview})
            if len(teams) >= TOP_TEAMS:
                break
        row = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()
               if k not in ("partners", "seen", "teams", "moves", "items")}
        row["players"] = len(s["seen"])
        row["partners"] = {k: round(v / len(s["seen"]), 3) for k, v in s["partners"].most_common(TOP_PARTNERS)}
        row["teams"] = teams
        if s["sheets"]:
            row["moves"] = {k: round(v / s["sheets"], 3) for k, v in s["moves"].most_common(8)}
            row["items"] = {k: round(v / s["sheets"], 3) for k, v in s["items"].most_common(3)}
        out[x] = row
    first = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d")
    last = datetime.fromtimestamp(end, timezone.utc).strftime("%Y-%m-%d")
    return {"from": first, "to": last, "days": days, "pokemon": out}


def load_index(format_id: str) -> dict | None:
    path = SUMMARY_DIR / f"{format_id}_cores.json"
    return json.loads(path.read_text()) if path.exists() else None


def tournament_core(root: str, teams: list[dict], dex: Dex, mega_item: str | None = None) -> dict:
    """Tournament teams running this Pokemon (holding mega_item, when given), best finishes first."""
    from src.similar_teams import roots_of
    hits = []
    natures, moves = Counter(), Counter()
    for t in teams:
        mon = next((p for p in t["sets"] if dex.get_species(p.species) is not None
                    and dex.sheet_id(dex.get_species(p.species)) == root), None)
        if mon is None or (mega_item and to_id(mon.item or "") != to_id(mega_item)):
            continue
        hits.append(t)
        natures[mon.nature] += 1
        moves.update(mon.moves)
    hits.sort(key=lambda t: (t["placing"] / max(t["players"] or 1, 1)) if t.get("placing") else 1.0)
    w = sum(int(t.get("wins") or 0) for t in hits)
    l = sum(int(t.get("losses") or 0) for t in hits)
    all_w = sum(int(t.get("wins") or 0) for t in teams)
    all_l = sum(int(t.get("losses") or 0) for t in teams)
    n = len(hits)
    return {
        "teams": n, "wins": w, "losses": l, "base": all_w / max(all_w + all_l, 1),
        "best": [{"placing": t.get("placing"), "players": t.get("players"), "wins": t.get("wins"),
                  "losses": t.get("losses"), "date": t["date"], "player": t.get("player", ""),
                  "team": [p.species for p in t["sets"]]} for t in hits[:TOP_TEAMS]],
        "natures": {k: v / n for k, v in natures.most_common(3)} if n else {},
        "moves": {k: v / n for k, v in moves.most_common(6)} if n else {},
        "roots": [sorted(roots_of(t["sets"], dex)) for t in hits],
    }


def core_matchups(core_set, usage, dex: Dex, doubles: bool = True, n: int = 30) -> dict:
    """The core alone against the n most-used Pokemon: who it beats one-on-one, and who 2HKOs it
    without being beaten back (its threats), most used first, each with the deciding calc."""
    from src.analysis import build_members
    from src.matchup import threat_report
    df = threat_report(build_members([core_set], dex), usage, dex, n=n, doubles=doubles)
    if df.empty:
        return {"beats": [], "threats": []}
    df = df.sort_values("usage %", ascending=False)
    beats = [(r["pokemon"], r["your best hits"].split("(", 1)[-1].rstrip(")")) for _, r in df.iterrows()
             if r["answers"] != "none"]
    threats = [(r["pokemon"], r["hardest hits"].split(" to ")[0]) for _, r in df.iterrows()
               if r["answers"] == "none" and r["2HKOs"] > 0]
    return {"beats": beats, "threats": threats}


def wins_against(m, t, doubles: bool = True) -> bool:
    """Does member m win the one-on-one against t (damage calcs both ways, then Speed)?"""
    from src.matchup import best_attack, wins_one_on_one
    from src.stats import effective_speed
    taken, _ = best_attack(m, t, doubles)
    dealt, _ = best_attack(t, m, doubles)
    return wins_one_on_one(taken, dealt, effective_speed(m.stats["spe"], m.pset.item if m.pset else None),
                           effective_speed(t.stats["spe"], t.pset.item if t.pset else None))


def answered(team_sets, threats: list[str], usage, dex: Dex, doubles: bool = True) -> tuple[list[str], list[str]]:
    """Which of the core's threats a built team has an answer to (a member that wins the 1-on-1)."""
    from src.analysis import build_members
    from src.matchup import opponent_members
    members = build_members(team_sets, dex)
    yes, no = [], []
    for name in threats:
        opp = opponent_members([name], usage, dex)
        if not opp:
            continue
        (yes if any(wins_against(m, opp[0], doubles) for m in members) else no).append(name)
    return yes, no


__all__ = ["replay_index", "load_index", "tournament_core", "core_matchups", "answered", "wins_against"]
