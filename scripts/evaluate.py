"""
evaluate.py

Scores the recommender against real tournament teams (see src/evaluate.py for
the method) and writes the results to data/evaluation/<regulation>.json, which
the README and the app's Recommendations tab report.

    python scripts/evaluate.py                 # Reg M-C VGC
    python scripts/evaluate.py --max-teams 300 # quicker run on the newest teams
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dex import load_dex  # noqa: E402
from src.evaluate import evaluate  # noqa: E402
from src.formats import FORMATS  # noqa: E402
from src.usage import load_usage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", default="gen9championsvgc2026regmc")
    parser.add_argument("--max-teams", type=int)
    args = parser.parse_args()

    fmt = FORMATS[args.format]
    dex, usage = load_dex(fmt.regulation), load_usage(fmt.id)
    if usage is None:
        print("No usage data for this format.")
        return 1
    start = time.time()
    report = evaluate(fmt.regulation, dex, usage, doubles=fmt.is_doubles, max_teams=args.max_teams)
    report["format"] = fmt.id
    report["seconds"] = round(time.time() - start, 1)
    out = ROOT / "data" / "evaluation" / f"{fmt.regulation}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))

    print(f"{report['teams']} teams ({report['train_teams']} train / {report['test_teams']} test), "
          f"{report['queries']} test queries, pool ~{report['candidate_pool']} Pokemon, {report['seconds']}s")
    print(f"tuned weights: {report['tuned_weights']}")
    print(f"{'model':<18}" + "".join(f"{k:>9}" for k in ["hit@1", "hit@5", "hit@10", "mrr", "in_pool"]))
    for name, m in report["results"].items():
        print(f"{name:<18}" + "".join(f"{m[k]:>9.3f}" for k in ["hit@1", "hit@5", "hit@10", "mrr", "in_pool"]))
    print(f"-> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
