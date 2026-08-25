"""Local SQLite store for fetched complaints.

Design notes:

* ``complaint_id`` is the natural primary key, so re-fetching an overlapping
  window is idempotent -- important because CFPB back-fills complaints for
  weeks after the date they were received, so recent windows must be re-pulled.
* ``fetch_log`` records every completed window against the filter set that
  produced it, making a multi-hour pull resumable and auditable.
* ``segment`` is materialised at insert time from the taxonomy crosswalk, so
  analysis never has to touch the unstable raw ``product`` label. The raw label
  is retained alongside it for drill-down and rename diagnostics.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config
from .taxonomy import canonical_segment

SCHEMA = """
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id            INTEGER PRIMARY KEY,
    date_received           TEXT NOT NULL,
    month                   TEXT NOT NULL,
    product                 TEXT,
    segment                 TEXT,
    sub_product             TEXT,
    issue                   TEXT,
    sub_issue               TEXT,
    company                 TEXT,
    state                   TEXT,
    zip_code                TEXT,
    tags                    TEXT,
    submitted_via           TEXT,
    date_sent_to_company    TEXT,
    company_response        TEXT,
    company_public_response TEXT,
    timely                  TEXT,
    has_narrative           INTEGER NOT NULL DEFAULT 0,
    narrative               TEXT
);

CREATE INDEX IF NOT EXISTS ix_complaints_month     ON complaints(month);
CREATE INDEX IF NOT EXISTS ix_complaints_segment   ON complaints(segment, month);
CREATE INDEX IF NOT EXISTS ix_complaints_company   ON complaints(company, month);
CREATE INDEX IF NOT EXISTS ix_complaints_state     ON complaints(state, month);
CREATE INDEX IF NOT EXISTS ix_complaints_channel   ON complaints(submitted_via, month);
CREATE INDEX IF NOT EXISTS ix_complaints_narrative ON complaints(has_narrative, month);
CREATE INDEX IF NOT EXISTS ix_complaints_date      ON complaints(date_received);

CREATE TABLE IF NOT EXISTS fetch_log (
    filter_key   TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    expected     INTEGER,
    received     INTEGER,
    inserted     INTEGER,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (filter_key, window_start, window_end)
);

CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
"""

_INSERT = """
INSERT INTO complaints (
    complaint_id, date_received, month, product, segment, sub_product,
    issue, sub_issue, company, state, zip_code, tags, submitted_via,
    date_sent_to_company, company_response, company_public_response,
    timely, has_narrative, narrative
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(complaint_id) DO UPDATE SET
    date_received=excluded.date_received,
    month=excluded.month,
    product=excluded.product,
    segment=excluded.segment,
    sub_product=excluded.sub_product,
    issue=excluded.issue,
    sub_issue=excluded.sub_issue,
    company=excluded.company,
    state=excluded.state,
    zip_code=excluded.zip_code,
    tags=excluded.tags,
    submitted_via=excluded.submitted_via,
    date_sent_to_company=excluded.date_sent_to_company,
    company_response=excluded.company_response,
    company_public_response=excluded.company_public_response,
    timely=excluded.timely,
    has_narrative=excluded.has_narrative,
    -- never overwrite a stored narrative with a blank from a metadata-only pull
    narrative=COALESCE(NULLIF(excluded.narrative, ''), complaints.narrative)
"""


class Store:
    def __init__(self, path: Path | str = config.DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=60)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # WAL keeps long pulls from blocking concurrent reads/analysis.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.commit()

    # -- writing -----------------------------------------------------------

    def upsert_rows(self, rows: Iterable[dict[str, str]]) -> int:
        """Insert or update complaint rows. Returns the number processed."""
        payload = []
        for row in rows:
            cid = (row.get("complaint_id") or "").strip()
            if not cid.isdigit():
                continue
            received = (row.get("date_received") or "")[:10]
            if len(received) != 10:
                continue
            narrative = (row.get("narrative") or "").strip()
            product = row.get("product") or ""
            payload.append(
                (
                    int(cid),
                    received,
                    received[:7],
                    product,
                    canonical_segment(product),
                    row.get("sub_product") or "",
                    row.get("issue") or "",
                    row.get("sub_issue") or "",
                    row.get("company") or "",
                    row.get("state") or "",
                    row.get("zip_code") or "",
                    row.get("tags") or "",
                    row.get("submitted_via") or "",
                    (row.get("date_sent_to_company") or "")[:10],
                    row.get("company_response") or "",
                    row.get("company_public_response") or "",
                    row.get("timely") or "",
                    1 if narrative else 0,
                    narrative,
                )
            )
        if not payload:
            return 0
        with self.conn:
            self.conn.executemany(_INSERT, payload)
        return len(payload)

    def log_window(
        self,
        filter_key: str,
        window_start: str,
        window_end: str,
        expected: int,
        received: int,
        inserted: int,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO fetch_log "
                "(filter_key, window_start, window_end, expected, received, "
                " inserted, fetched_at) "
                "VALUES (?,?,?,?,?,?, datetime('now'))",
                (filter_key, window_start, window_end, expected, received, inserted),
            )

    def completed_windows(self, filter_key: str) -> set[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT window_start, window_end FROM fetch_log WHERE filter_key = ?",
            (filter_key,),
        ).fetchall()
        return {(r["window_start"], r["window_end"]) for r in rows}

    def set_meta(self, key: str, value: Any) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value, updated_at) "
                "VALUES (?, ?, datetime('now'))",
                (key, json.dumps(value) if not isinstance(value, str) else value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    # -- reading -----------------------------------------------------------

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def total(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0])

    def coverage(self) -> dict[str, Any]:
        """What is actually in the store, for reporting alongside results."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, MIN(date_received) AS first_date, "
            "MAX(date_received) AS last_date, "
            "SUM(has_narrative) AS narratives, "
            "COUNT(DISTINCT company) AS companies, "
            "COUNT(DISTINCT segment) AS segments FROM complaints"
        ).fetchone()
        return dict(row)

    def segment_counts(self) -> list[sqlite3.Row]:
        return self.query(
            "SELECT segment, COUNT(*) AS n, MIN(date_received) AS first_date, "
            "MAX(date_received) AS last_date FROM complaints "
            "GROUP BY segment ORDER BY n DESC"
        )

    def narrative_coverage(
        self, segments: list[str] | None = None, since: str = "2015-01"
    ) -> list[sqlite3.Row]:
        """Share of complaints per month that carry a published narrative.

        This is a prerequisite check for every text-based finding, not a
        curiosity. Narrative publication requires consumer consent AND CFPB PII
        scrubbing, so it lags the complaint date -- and the lag is not uniform
        across segments. On the full extract, credit_reporting narrative
        coverage falls to 0.1% from 2026-01 while mortgage in the same months
        still shows 28-46%. Any near-duplicate or template analysis over a
        window with near-zero coverage is describing almost nothing, and would
        silently report 'no astroturfing found'.
        """
        where = ["month >= ?"]
        params: list[Any] = [since]
        if segments:
            where.append(f"segment IN ({','.join('?' * len(segments))})")
            params.extend(segments)
        return self.query(
            "SELECT month, COUNT(*) AS complaints, "
            "SUM(has_narrative) AS narratives, "
            "ROUND(100.0 * SUM(has_narrative) / COUNT(*), 2) AS narrative_pct "
            f"FROM complaints WHERE {' AND '.join(where)} "
            "GROUP BY month ORDER BY month",
            params,
        )

    def raw_product_windows(self) -> list[sqlite3.Row]:
        """Observed active date range of each raw product label.

        This is the rename diagnostic: a label that stops appearing on the same
        date another starts is a rename, not a change in consumer behaviour.
        """
        return self.query(
            "SELECT product, segment, COUNT(*) AS n, "
            "MIN(date_received) AS first_seen, MAX(date_received) AS last_seen "
            "FROM complaints GROUP BY product, segment ORDER BY segment, first_seen"
        )

    def close(self) -> None:
        self.conn.close()
