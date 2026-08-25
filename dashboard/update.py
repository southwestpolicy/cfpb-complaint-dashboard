"""Monthly refresh: pull recent complaints, update the index, emit the payload.

    python dashboard/update.py                 # normal monthly run
    python dashboard/update.py --months 6      # wider catch-up window
    python dashboard/update.py --dry-run

Designed to run unattended in CI. It never touches the 15 GB local store; it
carries only dashboard_index.sqlite between runs.

THE REFRESH WINDOW IS NOT JUST "SINCE LAST TIME"
CFPB publishes complaints weeks after the date they were received, so the
tail of any extract is incomplete. Each run therefore re-reads whole months
back to `--months` ago, purges what it previously recorded for them, and
re-ingests. Simply appending everything since the last watermark would bake the
undercount in permanently, and the undercount lands on the most recent months --
exactly the ones a dashboard puts at the right-hand edge of every chart.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cfpb_inspect.api import CFPBClient  # noqa: E402
from cfpb_inspect.taxonomy import SELECTED_SEGMENTS, canonical_segment, raw_products_for  # noqa: E402
from dashboard.build_index import (INDEX_PATH, ingest, open_index,  # noqa: E402
                                   prune_detail, purge_months)

log = logging.getLogger("update")

TARGET_ROWS_NARR = 25_000
TARGET_ROWS_PLAIN = 75_000


def months_between(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def to_rows(csv_rows):
    """Map API rows to the tuple shape ingest() expects."""
    for r in csv_rows:
        received = (r.get("date_received") or "")[:10]
        if len(received) != 10:
            continue
        narrative = (r.get("narrative") or "").strip()
        yield (
            canonical_segment(r.get("product") or ""),
            received[:7],
            r.get("state") or "",
            r.get("company") or "",
            r.get("company_response") or "",
            1 if narrative else 0,
            narrative,
        )


def run(months_back: int = 3, dry_run: bool = False) -> dict:
    conn = open_index()
    row = conn.execute("SELECT value FROM meta WHERE key='last_date'").fetchone()
    watermark = date.fromisoformat(row[0]) if row else date(2011, 12, 1)

    today = date.today()
    start_month = (watermark.replace(day=1)
                   - timedelta(days=1))          # into the previous month
    for _ in range(months_back - 1):
        start_month = (start_month.replace(day=1) - timedelta(days=1))
    start = start_month.replace(day=1)
    affected = months_between(start, today)

    log.info("watermark %s; refreshing months %s..%s (%d months)",
             watermark, affected[0], affected[-1], len(affected))
    if dry_run:
        client = CFPBClient()
        n = client.count(product=raw_products_for(SELECTED_SEGMENTS),
                         date_received_min=start.isoformat(),
                         date_received_max=today.isoformat())
        log.info("[dry-run] %s complaints in the refresh window", f"{n:,}")
        return {"dry_run": True, "window_complaints": n, "months": affected}

    client = CFPBClient()
    products = raw_products_for(SELECTED_SEGMENTS)
    purge_months(conn, affected)

    total = 0
    for has_narrative, target in (("true", TARGET_ROWS_NARR),
                                  ("false", TARGET_ROWS_PLAIN)):
        filters = {"product": products, "has_narrative": has_narrative}
        for w_start, w_end, expected in client.iter_windows(
                start.isoformat(), today.isoformat(),
                target_rows=target, **filters):
            rows = client.fetch_csv_rows(w_start, w_end, **filters)
            total += ingest(conn, list(to_rows(rows)))
            conn.commit()
            log.info("  %s..%s narrative=%s rows=%s", w_start, w_end,
                     has_narrative, f"{len(rows):,}")

    prune_detail(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_date', ?)",
                 (today.isoformat(),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)",
                 (today.isoformat(),))
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    log.info("refreshed %s complaints across %d months (%d requests, %.2f GB)",
             f"{total:,}", len(affected), client.request_count,
             client.bytes_downloaded / 1e9)
    return {"complaints": total, "months": affected,
            "requests": client.request_count,
            "index_mb": round(INDEX_PATH.stat().st_size / 1e6, 1)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3,
                    help="how many whole months to re-read (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    result = run(a.months, a.dry_run)
    print(result)
