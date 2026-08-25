"""Refuse to publish an implausible dashboard payload.

    python dashboard/check_payload.py dashboard/public/data/dashboard.json

An unattended monthly job can fail in ways that still produce a well-formed
file: a partial fetch, an API change, a purge that ran without a matching
re-ingest. Any of those would quietly put wrong numbers on a public page, which
is worse than the page going stale. This exits non-zero instead.

Checks are deliberately loose bounds, not exact expectations -- the point is to
catch collapse and corruption, not to freeze the figures.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

# Plausible envelopes. Wide on purpose.
MIN_COMPLAINTS = 15_000_000
MIN_TEMPLATED_PCT, MAX_TEMPLATED_PCT = 5.0, 70.0
MIN_TREND_POINTS = 60
MIN_STATES = 40
MIN_COMPANIES = 8
MAX_STALE_DAYS = 75


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "dashboard/public/data/dashboard.json")
    if not path.exists():
        fail(f"{path} does not exist")

    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"payload is not valid JSON: {exc}")

    for key in ("meta", "headline", "trend", "volume", "states", "companies"):
        if key not in d:
            fail(f"missing top-level key {key!r}")

    h, m = d["headline"], d["meta"]

    if h.get("complaints", 0) < MIN_COMPLAINTS:
        fail(f"only {h.get('complaints'):,} complaints; expected at least "
             f"{MIN_COMPLAINTS:,}. A partial fetch would look like this.")

    pctv = h.get("templated_pct")
    if pctv is None or not (MIN_TEMPLATED_PCT <= pctv <= MAX_TEMPLATED_PCT):
        fail(f"templated share {pctv} outside the plausible range "
             f"{MIN_TEMPLATED_PCT}-{MAX_TEMPLATED_PCT}%")

    if len(d["trend"]) < MIN_TREND_POINTS:
        fail(f"trend has {len(d['trend'])} points; expected >= {MIN_TREND_POINTS}")

    if len(d["states"]) < MIN_STATES:
        fail(f"only {len(d['states'])} states present")

    if len(d["companies"]) < MIN_COMPANIES:
        fail(f"only {len(d['companies'])} companies present")

    through = m.get("data_through")
    try:
        age = (date.today() - date.fromisoformat(through)).days
    except Exception:
        fail(f"unreadable data_through: {through!r}")
    if age > MAX_STALE_DAYS:
        fail(f"data_through {through} is {age} days old; the fetch did not advance")

    # The trend must not be flat or empty at the end: a purge without a
    # matching re-ingest shows up as trailing zeros.
    tail = [p["pct"] for p in d["trend"][-3:]]
    if tail and all(v == 0 for v in tail):
        fail("the last three trend points are zero; months were purged but not refilled")

    monthly_total = sum(sum(s["counts"]) for s in d["volume"]["series"])
    if monthly_total < MIN_COMPLAINTS * 0.5:
        fail(f"volume series totals {monthly_total:,}, implausibly low against "
             f"{h['complaints']:,} complaints")

    print("payload OK")
    print(f"  complaints      {h['complaints']:,}")
    print(f"  templated       {h['templated_pct']}%  ({h['templated']:,})")
    print(f"  trend points    {len(d['trend'])}  ({d['trend'][0]['month']} to "
          f"{d['trend'][-1]['month']})")
    print(f"  states          {len(d['states'])}")
    print(f"  companies       {len(d['companies'])}")
    print(f"  data through    {through}  ({age} days old)")
    print(f"  size            {path.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
