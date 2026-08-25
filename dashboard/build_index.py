"""The compact aggregate index the monthly job carries between runs.

    python dashboard/build_index.py --bootstrap   # once, from the full local store
    python dashboard/build_index.py --stats

WHY AN INDEX RATHER THAN THE FULL STORE
The complete extract is ~15 GB, impractical to shuttle through a CI runner every
month. Almost none of it is needed: the dashboard reports aggregates. The one
thing that cannot be aggregated away is template membership, because a text only
becomes a template once it has been used often enough, and it can cross that
line years after it first appeared. Recomputing the trend correctly therefore
needs per-text, per-month counts -- but with narrative bodies dropped and only an
8-byte hash kept, that is ~64 MB (26 MB gzipped) rather than 15 GB.

EVERY TABLE IS KEYED BY MONTH
CFPB back-fills complaints into dates already past, so each run must re-read a
trailing window and replace what it previously recorded for those months. That
is only cheap if every table can be purged a month at a time -- a year-keyed
table would force re-fetching a whole year to correct one week of backfill.
Yearly figures are aggregated up at emit time instead.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cfpb_inspect import config  # noqa: E402
from cfpb_inspect.analysis.dedupe import normalize  # noqa: E402
from cfpb_inspect.companies import company_group  # noqa: E402
from cfpb_inspect.store import Store  # noqa: E402

INDEX_PATH = config.DATA_DIR / "dashboard_index.sqlite"

MIN_TOKENS = 25
# Per-state and relief detail is kept only for texts seen at least this often;
# a rarer text cannot cross the template threshold without being seen again,
# at which point its row is recreated.
DETAIL_MIN = 5
RELIEF_FROM = "2022-01"
# Sentinel key for "every scored narrative", used as a denominator row.
ALL_HASH = b"ALLNARRS"   # 8 printable bytes; collision with a real sha1 prefix is negligible
RELIEF_SET = ("Closed with monetary relief", "Closed with non-monetary relief")

# Per-company text detail is kept only for the busiest firms. The panel that
# uses it shows twelve; keeping forty leaves room for the ranking to move
# without carrying a row for every one of the thousands of named companies,
# which is what would make this table dominate the index.
COMPANY_DETAIL_TOP = 40

TABLES = ("text_month", "text_state_month", "text_company_month", "monthly",
          "company_month", "state_month", "relief_month")

SCHEMA = """
CREATE TABLE IF NOT EXISTS text_month (
    hash BLOB NOT NULL, month TEXT NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (hash, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS text_state_month (
    hash BLOB NOT NULL, state TEXT NOT NULL, month TEXT NOT NULL,
    n INTEGER NOT NULL, PRIMARY KEY (hash, state, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS text_company_month (
    hash BLOB NOT NULL, company TEXT NOT NULL, month TEXT NOT NULL,
    n INTEGER NOT NULL, PRIMARY KEY (hash, company, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS monthly (
    segment TEXT NOT NULL, month TEXT NOT NULL,
    complaints INTEGER NOT NULL, narratives INTEGER NOT NULL,
    PRIMARY KEY (segment, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS company_month (
    company TEXT NOT NULL, segment TEXT NOT NULL, month TEXT NOT NULL,
    complaints INTEGER NOT NULL, narratives INTEGER NOT NULL,
    PRIMARY KEY (company, segment, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS state_month (
    state TEXT NOT NULL, month TEXT NOT NULL,
    complaints INTEGER NOT NULL, narratives INTEGER NOT NULL,
    PRIMARY KEY (state, month)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS relief_month (
    segment TEXT NOT NULL, month TEXT NOT NULL, hash BLOB NOT NULL,
    relieved INTEGER NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (segment, month, hash, relieved)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def open_index(path: Path = INDEX_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    return conn


def text_hash(narrative: str | None) -> bytes | None:
    norm, _ = normalize(narrative or "")
    if len(norm.split()) < MIN_TOKENS:
        return None
    return hashlib.sha1(norm.encode()).digest()[:8]


def purge_months(conn: sqlite3.Connection, months: list[str]) -> None:
    """Remove everything previously recorded for these months.

    Called before re-ingesting a refreshed window so backfilled complaints
    replace earlier figures instead of being added to them.
    """
    if not months:
        return
    qs = ",".join("?" * len(months))
    for t in TABLES:
        conn.execute(f"DELETE FROM {t} WHERE month IN ({qs})", months)
    conn.commit()


def ingest(conn: sqlite3.Connection, rows) -> int:
    """Fold complaint rows into the aggregate tables.

    rows: (segment, month, state, company, company_response, has_narrative,
           narrative)
    """
    tm, tsm, tcm, rel = Counter(), Counter(), Counter(), Counter()
    mon, comp, sm = Counter(), Counter(), Counter()
    mon_n, comp_n, sm_n = Counter(), Counter(), Counter()
    n = 0
    for seg, month, state, company, resp, has_narr, narr in rows:
        n += 1
        st = (state or "").strip()
        grp = company_group(company)
        mon[(seg, month)] += 1
        comp[(grp, seg, month)] += 1
        sm[(st, month)] += 1

        h = text_hash(narr) if has_narr else None
        if has_narr:
            mon_n[(seg, month)] += 1
            comp_n[(grp, seg, month)] += 1
            sm_n[(st, month)] += 1
        if h is not None:
            tm[(h, month)] += 1
            if st:
                tsm[(h, st, month)] += 1
                # ALL_HASH is the denominator row: every scored narrative for
                # this state and month. It is keyed off a sentinel that never
                # appears in text_month, so prune_detail() leaves it alone --
                # without it the only surviving rows are repeated texts and the
                # templated share computes against itself.
                tsm[(ALL_HASH, st, month)] += 1
            if grp:
                # Same shape for companies, and for the same reason: whether a
                # text counts as a template depends on its running total across
                # the whole corpus, which can cross the threshold years after
                # the fact. Only per-hash, per-month counts can be re-totalled
                # correctly at emit time; a precomputed "templated" flag would
                # silently freeze the answer as of ingest.
                tcm[(h, grp, month)] += 1
                tcm[(ALL_HASH, grp, month)] += 1
            # Relief is recorded only for complaints that HAVE a scored
            # narrative. Including narrative-less complaints in the "organic"
            # bucket compares templated filings against a different population
            # and collapses the difference.
            if resp and resp not in ("", "In progress") and month >= RELIEF_FROM:
                rel[(seg, month, h, resp in RELIEF_SET)] += 1

    def bump(table, cols, counter):
        ph = ",".join("?" * (len(cols) + 1))
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}, n) VALUES ({ph}) "
            f"ON CONFLICT({','.join(cols)}) DO UPDATE SET n = n + excluded.n",
            [(*k, v) for k, v in counter.items()])

    def bump2(table, cols, c_all, c_narr):
        keys = set(c_all) | set(c_narr)
        ph = ",".join("?" * (len(cols) + 2))
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}, complaints, narratives) "
            f"VALUES ({ph}) ON CONFLICT({','.join(cols)}) DO UPDATE SET "
            "complaints = complaints + excluded.complaints, "
            "narratives = narratives + excluded.narratives",
            [(*k, c_all.get(k, 0), c_narr.get(k, 0)) for k in keys])

    bump("text_month", ["hash", "month"], tm)
    bump("text_state_month", ["hash", "state", "month"], tsm)
    bump("text_company_month", ["hash", "company", "month"], tcm)
    bump2("monthly", ["segment", "month"], mon, mon_n)
    bump2("company_month", ["company", "segment", "month"], comp, comp_n)
    bump2("state_month", ["state", "month"], sm, sm_n)
    conn.executemany(
        "INSERT INTO relief_month (segment, month, hash, relieved, n) "
        "VALUES (?,?,?,?,?) ON CONFLICT(segment, month, hash, relieved) "
        "DO UPDATE SET n = n + excluded.n",
        [(s, m, h, int(r), v) for (s, m, h, r), v in rel.items()])
    return n


def prune_detail(conn: sqlite3.Connection) -> None:
    """Collapse per-state and relief detail for texts too rare to matter."""
    conn.execute("DROP TABLE IF EXISTS temp.rare")
    conn.execute("CREATE TEMP TABLE rare AS SELECT hash FROM text_month "
                 "GROUP BY hash HAVING SUM(n) < ?", (DETAIL_MIN,))
    conn.execute("CREATE INDEX temp.ix_rare ON rare(hash)")

    before = conn.execute("SELECT COUNT(*) FROM text_state_month").fetchone()[0]
    conn.execute("DELETE FROM text_state_month WHERE hash <> ? "
             "AND hash IN (SELECT hash FROM rare)", (ALL_HASH,))
    after = conn.execute("SELECT COUNT(*) FROM text_state_month").fetchone()[0]

    cb = conn.execute("SELECT COUNT(*) FROM text_company_month").fetchone()[0]
    conn.execute("DELETE FROM text_company_month WHERE hash <> ? "
                 "AND hash IN (SELECT hash FROM rare)", (ALL_HASH,))
    # Then drop every company outside the top of the ranking. Unlike states,
    # which are a closed set of 51, companies run to thousands, and a per-hash
    # row for each would cost more than the whole rest of the index.
    conn.execute("DROP TABLE IF EXISTS temp.keep_co")
    conn.execute(
        "CREATE TEMP TABLE keep_co AS SELECT company FROM company_month "
        "GROUP BY company ORDER BY SUM(complaints) DESC LIMIT ?",
        (COMPANY_DETAIL_TOP,))
    conn.execute("CREATE INDEX temp.ix_keep_co ON keep_co(company)")
    conn.execute("DELETE FROM text_company_month "
                 "WHERE company NOT IN (SELECT company FROM keep_co)")
    conn.execute("DROP TABLE temp.keep_co")
    ca = conn.execute("SELECT COUNT(*) FROM text_company_month").fetchone()[0]

    rb = conn.execute("SELECT COUNT(*) FROM relief_month").fetchone()[0]
    # Rare texts fold into the anonymous bucket rather than being deleted:
    # they are organic by definition and still needed as the denominator.
    conn.execute("""INSERT INTO relief_month (segment, month, hash, relieved, n)
        SELECT segment, month, X'', relieved, SUM(n) FROM relief_month
        WHERE hash <> X'' AND hash IN (SELECT hash FROM rare)
        GROUP BY segment, month, relieved
        ON CONFLICT(segment, month, hash, relieved)
        DO UPDATE SET n = n + excluded.n""")
    conn.execute("DELETE FROM relief_month WHERE hash <> X'' "
                 "AND hash IN (SELECT hash FROM rare)")
    ra = conn.execute("SELECT COUNT(*) FROM relief_month").fetchone()[0]
    conn.execute("DROP TABLE temp.rare")
    conn.commit()
    print(f"  text_state_month   {before:,} -> {after:,} rows")
    print(f"  text_company_month {cb:,} -> {ca:,} rows")
    print(f"  relief_month       {rb:,} -> {ra:,} rows")


def bootstrap() -> None:
    store = Store()
    conn = open_index()
    for t in TABLES:
        conn.execute(f"DELETE FROM {t}")
    cur = store.conn.execute(
        "SELECT segment, month, state, company, company_response, "
        "has_narrative, narrative FROM complaints")
    total = 0
    while True:
        batch = cur.fetchmany(50_000)
        if not batch:
            break
        total += ingest(conn, batch)
        conn.commit()
        if total % 4_000_000 < 50_000:
            print(f"  {total:,} complaints folded in")
    last = store.query("SELECT MAX(date_received) d FROM complaints")[0]["d"][:10]
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('last_date', ?)", (last,))
    conn.commit()
    print(f"  {total:,} complaints indexed; watermark {last}")
    prune_detail(conn)
    conn.execute("VACUUM")
    conn.close()


def stats() -> None:
    conn = open_index()
    print(f"index: {INDEX_PATH}")
    print(f"  file size: {INDEX_PATH.stat().st_size/1e6:.1f} MB")
    for t in TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<18} {n:>10,} rows")
    for k, v in conn.execute("SELECT key, value FROM meta"):
        print(f"  meta.{k} = {v}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.bootstrap:
        bootstrap()
    stats()
