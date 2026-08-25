"""Windowed bulk extraction driver.

Three things here are not obvious and matter a lot in practice.

NARRATIVE STREAM SPLITTING
Only ~22% of complaints carry a publishable narrative, but a narrative row is
roughly 8x the size of one without. Fetching a mixed stream forces the window
sizer to assume worst-case row width everywhere. Splitting the pull into a
``has_narrative=true`` pass and a ``has_narrative=false`` pass lets each use a
row target matched to its actual row width, which cut the projected download
for full history from roughly 26 GB to roughly 10 GB.

THE CSV ROW CAP IS RECOVERABLE, NOT FATAL
A CSV export above ``config.MAX_CSV_ROWS`` (100,000) returns HTTP 400. Windows
are sized below that by count probes, but the probe and the export are separate
queries, so complaints arriving between them can push a window that measured
safe over the cap. ``_fetch_window`` therefore subdivides and retries: by date
first, then by individual product if a single day is still too large. A pull
measured in hours must not die on its third window because of a race.

BACKFILL REQUIRES RE-FETCHING RECENT WINDOWS
CFPB keeps adding complaints to dates already in the past -- a complaint
received on the 1st may not appear in the public API for weeks. A resumable
pull that trusts its own fetch log will therefore permanently under-count the
most recent weeks, and since those weeks are the post-LLM end of the series,
the undercount would bias exactly the coefficient we care about. Windows
touching the last ``refetch_recent_days`` days are always re-fetched.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from . import config
from .api import CFPBClient, CsvRowLimitExceeded
from .store import Store
from .taxonomy import raw_products_for

log = logging.getLogger(__name__)

# Row-count targets per request. Both must stay below config.MAX_CSV_ROWS, with
# headroom for complaints arriving between the count probe and the export.
TARGET_ROWS_WITH_NARRATIVE = 25_000
TARGET_ROWS_NO_NARRATIVE = 75_000

DEFAULT_REFETCH_DAYS = 60


def filter_key(products: Sequence[str], has_narrative: str | None) -> str:
    """Stable identifier for a filter set, used to scope the fetch log."""
    blob = "|".join(sorted(products)) + f"#narrative={has_narrative}"
    digest = hashlib.sha1(blob.encode()).hexdigest()[:12]
    return f"n{has_narrative or 'any'}-{digest}"


def _fetch_window(
    client: CFPBClient,
    store: Store,
    key: str,
    win_start: str,
    win_end: str,
    filters: dict[str, Any],
    expected: int,
    depth: int = 0,
) -> tuple[int, int, int]:
    """Fetch one window, subdividing if it exceeds the CSV row cap.

    Returns (received, inserted, failed_windows).
    """
    indent = "  " * depth
    try:
        rows = client.fetch_csv_rows(win_start, win_end, **filters)
    except CsvRowLimitExceeded as exc:
        days = (date.fromisoformat(win_end) - date.fromisoformat(win_start)).days + 1
        log.warning("%s%s -- subdividing", indent, exc)

        if days > 1:
            mid = date.fromisoformat(win_start) + timedelta(days=days // 2 - 1)
            left = _fetch_window(
                client, store, key, win_start, mid.isoformat(),
                filters, 0, depth + 1,
            )
            right = _fetch_window(
                client, store, key, (mid + timedelta(days=1)).isoformat(),
                win_end, filters, 0, depth + 1,
            )
            totals = tuple(a + b for a, b in zip(left, right))
            # Log the parent span too, so resume recognises it as complete.
            store.log_window(key, win_start, win_end, expected, totals[0], totals[1])
            return totals  # type: ignore[return-value]

        # A single day over the cap: split by individual product.
        products = filters.get("product") or []
        if isinstance(products, str) or len(products) <= 1:
            log.error(
                "%sUNRECOVERABLE: %s matches more than %s rows for a single "
                "product on a single day. This slice cannot be extracted via "
                "CSV and is MISSING from the store.",
                indent, win_start, f"{config.MAX_CSV_ROWS:,}",
            )
            store.log_window(key, win_start, win_end, expected, -1, 0)
            return 0, 0, 1

        received = inserted = failed = 0
        for product in products:
            sub = {**filters, "product": [product]}
            r, i, f = _fetch_window(
                client, store, f"{key}#p", win_start, win_end, sub, 0, depth + 1
            )
            received += r
            inserted += i
            failed += f
        store.log_window(key, win_start, win_end, expected, received, inserted)
        return received, inserted, failed

    inserted = store.upsert_rows(rows)
    store.log_window(key, win_start, win_end, expected, len(rows), inserted)
    return len(rows), inserted, 0


def fetch_segments(
    segments: Iterable[str],
    start: str = config.DB_START,
    end: str | None = None,
    narrative_mode: str = "split",
    store: Store | None = None,
    client: CFPBClient | None = None,
    refetch_recent_days: int = DEFAULT_REFETCH_DAYS,
    resume: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """Pull complaints for the given canonical segments into the local store.

    narrative_mode:
      ``split``   two passes, one per narrative flag (recommended, fastest)
      ``with``    only complaints that have a narrative (for text analysis)
      ``without`` only complaints that do not
      ``any``     single mixed pass
    """
    store = store or Store()
    client = client or CFPBClient()
    end = end or date.today().isoformat()
    segments = list(segments)
    products = raw_products_for(segments)

    if narrative_mode == "split":
        passes = [("true", TARGET_ROWS_WITH_NARRATIVE),
                  ("false", TARGET_ROWS_NO_NARRATIVE)]
    elif narrative_mode == "with":
        passes = [("true", TARGET_ROWS_WITH_NARRATIVE)]
    elif narrative_mode == "without":
        passes = [("false", TARGET_ROWS_NO_NARRATIVE)]
    elif narrative_mode == "any":
        passes = [(None, TARGET_ROWS_WITH_NARRATIVE)]
    else:
        raise ValueError(f"unknown narrative_mode {narrative_mode!r}")

    stale_after = (
        date.fromisoformat(end) - timedelta(days=refetch_recent_days)
    ).isoformat()

    totals = {"expected": 0, "received": 0, "inserted": 0, "windows": 0,
              "skipped_windows": 0, "failed_windows": 0}

    for has_narrative, target in passes:
        target = min(target, config.MAX_CSV_ROWS)
        key = filter_key(products, has_narrative)
        done = store.completed_windows(key) if resume else set()
        expected_total = client.count(
            product=products,
            has_narrative=has_narrative,
            date_received_min=start,
            date_received_max=end,
        )
        log.info(
            "pass has_narrative=%s: %s complaints expected in %s..%s "
            "(%s already-complete windows)",
            has_narrative, f"{expected_total:,}", start, end, len(done),
        )

        filters = {"product": products, "has_narrative": has_narrative}

        for win_start, win_end, expected in client.iter_windows(
            start, end, target_rows=target, **filters
        ):
            totals["expected"] += expected
            is_recent = win_end >= stale_after
            if (win_start, win_end) in done and not is_recent:
                totals["skipped_windows"] += 1
                continue

            if dry_run:
                log.info(
                    "[dry-run] %s..%s narrative=%s ~%s rows",
                    win_start, win_end, has_narrative, f"{expected:,}",
                )
                totals["windows"] += 1
                continue

            received, inserted, failed = _fetch_window(
                client, store, key, win_start, win_end, filters, expected
            )
            totals["received"] += received
            totals["inserted"] += inserted
            totals["failed_windows"] += failed
            totals["windows"] += 1

            if received and received != expected:
                # Not necessarily an error: the count probe and the CSV export
                # are separate queries and new complaints can land between them.
                # A large gap, though, means data is missing.
                log.warning(
                    "%s..%s expected %s rows, got %s",
                    win_start, win_end, f"{expected:,}", f"{received:,}",
                )
            log.info(
                "%s..%s narrative=%s  rows=%s  store=%s",
                win_start, win_end, has_narrative,
                f"{received:,}", f"{store.total():,}",
            )

    if not dry_run:
        store.set_meta("last_fetch_end", end)
        store.set_meta("fetch_segments", sorted(segments))
        store.set_meta("api_requests", client.request_count)

    if totals["failed_windows"]:
        log.error(
            "%d window(s) could not be extracted and are MISSING from the "
            "store; see the UNRECOVERABLE lines above",
            totals["failed_windows"],
        )
    log.info(
        "done: %s windows, %s rows received, %s in store (%s requests, %.1f GB)",
        totals["windows"], f"{totals['received']:,}", f"{store.total():,}",
        client.request_count, client.bytes_downloaded / 1e9,
    )
    return totals
