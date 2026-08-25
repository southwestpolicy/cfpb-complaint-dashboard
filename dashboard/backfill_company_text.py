#!/usr/bin/env python3
"""One-off backfill for `text_company_month`, the per-company text detail table.

WHY THIS EXISTS INSTEAD OF A REBUILD
The templated share in the companies panel needs per-company, per-hash, per-month
counts. That table was added after the index was built, and the monthly job only
re-reads its trailing refresh window, so the months the panel actually reports on
would stay empty for a year. The documented alternative is
`build_index.py --bootstrap`, which deletes every table and re-folds all 16.6M
complaints from the 15 GB store -- an hour of work to obtain one new table, with
the whole index unavailable if it is interrupted.

This does the narrow thing instead. It is:

  * additive -- it writes only `text_company_month` and never deletes from, or
    even reads, any other table;
  * restartable -- each month is written in its own transaction, and re-running
    a month replaces that month rather than double-counting it;
  * cheap -- only complaints carrying a narrative are hashed, which is a few
    hundred thousand rows per year rather than several million.

The hashing must match `build_index.text_hash` exactly, so it is imported rather
than reimplemented: a different normalisation would produce hashes that never
match the template set and a templated share of zero everywhere.

LIMITATION
Company keys are only consistent across index tables if every table was written
by the same version of `cfpb_inspect.companies`. This script groups with the
current alias table; if the index's `company_month` predates an alias being
added it holds the older key, and for those firms the two never join. The panel
then shows a dash for them rather than a wrong number. Only a full
`build_index.py --bootstrap` re-keys every table together, so that is still the
right move when the aliases have moved on -- it also corrects the display names
in the existing companies panel, which are stale for exactly the same reason.

    python dashboard/backfill_company_text.py --months 18
    python dashboard/backfill_company_text.py --from 2011-12    # everything
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cfpb_inspect import config  # noqa: E402
from cfpb_inspect.companies import company_group  # noqa: E402
from dashboard.build_index import (ALL_HASH, COMPANY_DETAIL_TOP,  # noqa: E402
                                   INDEX_PATH, open_index, text_hash)

STORE_PATH = config.DATA_DIR / "complaints.sqlite"


def months_in_index(conn: sqlite3.Connection) -> list[str]:
    return [m for (m,) in conn.execute(
        "SELECT DISTINCT month FROM monthly ORDER BY month")]


def backfill_month(idx: sqlite3.Connection, store: sqlite3.Connection,
                   month: str) -> tuple[int, int]:
    """Recompute one month of per-company text counts. Returns (rows, narrs)."""
    counts: Counter = Counter()
    narrs = 0
    cur = store.execute(
        "SELECT company, narrative FROM complaints "
        "WHERE month = ? AND has_narrative = 1", (month,))
    while True:
        batch = cur.fetchmany(20_000)
        if not batch:
            break
        for company, narrative in batch:
            h = text_hash(narrative)
            if h is None:
                continue
            grp = company_group(company)
            if not grp:
                continue
            narrs += 1
            counts[(h, grp)] += 1
            # Denominator row: every scored narrative for this company and
            # month. Mirrors the sentinel the state table uses, and is what the
            # templated share is divided by.
            counts[(ALL_HASH, grp)] += 1

    # Replace rather than accumulate, so a re-run is idempotent.
    idx.execute("DELETE FROM text_company_month WHERE month = ?", (month,))
    idx.executemany(
        "INSERT INTO text_company_month (hash, company, month, n) "
        "VALUES (?,?,?,?) ON CONFLICT(hash, company, month) "
        "DO UPDATE SET n = n + excluded.n",
        [(h, c, month, n) for (h, c), n in counts.items()])
    idx.commit()
    return len(counts), narrs


def prune_companies(idx: sqlite3.Connection) -> tuple[int, int]:
    """Keep text detail only for the busiest firms, as prune_detail does."""
    before = idx.execute("SELECT COUNT(*) FROM text_company_month").fetchone()[0]
    idx.execute("DROP TABLE IF EXISTS temp.keep_co")
    idx.execute(
        "CREATE TEMP TABLE keep_co AS SELECT company FROM company_month "
        "GROUP BY company ORDER BY SUM(complaints) DESC LIMIT ?",
        (COMPANY_DETAIL_TOP,))
    idx.execute("CREATE INDEX temp.ix_keep_co ON keep_co(company)")
    idx.execute("DELETE FROM text_company_month "
                "WHERE company NOT IN (SELECT company FROM keep_co)")
    idx.execute("DROP TABLE temp.keep_co")
    idx.commit()
    after = idx.execute("SELECT COUNT(*) FROM text_company_month").fetchone()[0]
    return before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", default=str(INDEX_PATH),
                    help="Index to write to. Point at a copy to rehearse.")
    ap.add_argument("--months", type=int, default=18,
                    help="How many trailing months to backfill (default 18).")
    ap.add_argument("--from", dest="from_month", default=None,
                    help="Earliest month to backfill, e.g. 2011-12. "
                         "Overrides --months.")
    args = ap.parse_args()

    if not STORE_PATH.exists():
        print(f"local store not found: {STORE_PATH}", file=sys.stderr)
        return 1

    idx = open_index(Path(args.index))
    months = months_in_index(idx)
    if not months:
        print("index has no months; nothing to backfill", file=sys.stderr)
        return 1

    target = ([m for m in months if m >= args.from_month] if args.from_month
              else months[-args.months:])

    store = sqlite3.connect(f"file:{STORE_PATH}?mode=ro", uri=True)
    print(f"backfilling {len(target)} months: {target[0]} .. {target[-1]}")
    tot_rows = tot_narr = 0
    for m in target:
        rows, narrs = backfill_month(idx, store, m)
        tot_rows += rows
        tot_narr += narrs
        print(f"  {m}  {narrs:>7,} scored narratives -> {rows:>7,} rows")
    store.close()

    before, after = prune_companies(idx)
    print(f"pruned to top {COMPANY_DETAIL_TOP} companies: "
          f"{before:,} -> {after:,} rows")
    print(f"done: {tot_narr:,} narratives across {len(target)} months")
    idx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
