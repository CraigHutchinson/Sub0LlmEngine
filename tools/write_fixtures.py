"""Writes the fixtures the C++ tests read from the Python reference (docs/SERVICE.md "Port order", step 2).

    python tools/write_fixtures.py          write tests/fixtures/
    python tools/write_fixtures.py --check  fail if the committed fixtures differ from what the reference produces

bench/summary.json describes the real bench history: the C++ contracts layer must parse the same file to the same numbers.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "bench", "ultra-9-275hx_rtx-5070-laptop-gpu-8g_63g.jsonl")
OUT = os.path.join(ROOT, "tests", "fixtures", "bench", "summary.json")


def benchSummary():
    rows = []
    with open(BENCH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    outcomes = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "source": "bench/" + os.path.basename(BENCH),
        "rows": len(rows),
        "outcomes": dict(sorted(outcomes.items())),
        "withExcluded": sum(1 for r in rows if r.get("excluded")),
        "withoutBackend": sum(1 for r in rows if "backend" not in r),
        "nullPeakVram": sum(1 for r in rows if r["peakVramMiB"] is None),
        "nullWallSec": sum(1 for r in rows if r["wallSec"] is None),
        "maxDepth": max(r["depth"] for r in rows),
        "maxConcurrency": max(r["B"] for r in rows),
        "sumTgTps": round(math.fsum(r["tgTps"] for r in rows if r.get("tgTps") is not None), 6),
        "sumPpTps": round(math.fsum(r["ppTps"] for r in rows if r.get("ppTps") is not None), 6),
        "distinctBuilds": len({r["build"] for r in rows}),
        "paramNames": sorted({k for r in rows for k in r["params"]}),
    }


def main():
    want = json.dumps(benchSummary(), indent=2) + "\n"
    if "--check" in sys.argv:
        have = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if have != want:
            print("tests/fixtures/bench/summary.json is stale: run python tools/write_fixtures.py", file=sys.stderr)
            return 1
        print("fixtures are fresh")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(want)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
