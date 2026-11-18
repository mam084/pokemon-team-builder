"""Build learned-match-model rows from rated ladder / Bo3 replays (cached to .cache)."""
import sys, time, math, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from src import match_model as M
from src.analysis import build_members
from src.formats import CURRENT
from src.dex import load_dex
from src.usage import load_usage
from src.replays import load_records, _sets_for

OUT = M.CACHE_DIR / f"{CURRENT.regulation}_replay_match_rows.pkl"
_dex = _usage = None
_cache = {}


def _init():
    global _dex, _usage
    _dex, _usage = load_dex(CURRENT.regulation), load_usage(CURRENT.id, recent=False)


def _side(rec, p):
    sets = _sets_for(rec, p, _dex, _usage)
    mega_name = (rec.get("mega") or {}).get(p)
    key = (tuple((s.species, s.item, s.ability, tuple(s.moves)) for s in sets), mega_name)
    if key not in _cache:
        megas = [i for i, s in enumerate(sets) if s.is_mega(_dex)]
        pick = None
        if mega_name:
            pick = next((i for i in megas if mega_name.startswith(sets[i].species.split("-")[0])), None)
        if pick is None and megas:
            pick = megas[0]
        mem = build_members(sets, _dex, evolve=pick)
        _cache[key] = (mem, M.side_profile(mem),
                       sorted({_dex.sheet_id(s) for x in sets if (s := _dex.get_species(x.species))}))
    return _cache[key]


def _row(rec):
    try:
        (ma, pa, sa), (mb, pb, sb) = _side(rec, "p1"), _side(rec, "p2")
        if len(ma) < 4 or len(mb) < 4:
            return None
        r1, r2 = rec["players"]["p1"]["rating"], rec["players"]["p2"]["rating"]
        row = {"tournament": rec["format"], "date": dt.datetime.utcfromtimestamp(rec["uploadtime"]).date().isoformat(),
               "won": int(rec["winner"] == "p1"), "species_a": sa, "species_b": sb,
               "rating diff": (r1 - r2) / 400 * math.log(10), "bo3": int(bool(rec.get("sheets"))),
               "rating min": min(r1, r2)}
        row.update(M.matchup_features(M.pair_parts(ma, mb), ma, mb))
        for k in pa:
            row[k] = pa[k] - pb[k]
        return row
    except Exception as e:  # noqa
        return None


def main(shard=0, shards=1):
    keep = ("format", "uploadtime", "players", "winner", "preview", "sheets", "mega")
    recs = []
    for f in CURRENT.replays:
        recs += [{k: r.get(k) for k in keep} for r in load_records(f)
                 if all(r["players"][p]["rating"] for p in ("p1", "p2"))
                 and r["winner"] in ("p1", "p2") and not r.get("forfeit")]
    recs = recs[shard::shards]
    print(len(recs), "replays", flush=True)
    _init()
    t0, rows = time.time(), []
    for n, r in enumerate(recs):
        if len(_cache) > 4000:
            _cache.clear()
        row = _row(r)
        if row:
            rows.append(row)
        if n % 5000 == 0:
            print(n, f"{time.time()-t0:.0f}s", flush=True)
    out = OUT.with_suffix(f".{shard}.pkl") if shards > 1 else OUT
    pd.DataFrame(rows).to_pickle(out)
    print(len(rows), "rows", f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(*map(int, sys.argv[1:3])) if len(sys.argv) > 2 else main()
