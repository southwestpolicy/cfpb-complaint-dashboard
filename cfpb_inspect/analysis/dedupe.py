"""Near-duplicate narrative detection.

THE REDACTION CONFOUND
----------------------
CFPB scrubs PII from published narratives by replacing it with runs of X, so
real text looks like::

    ON XX/XX/XXXX I WENT TO XXXX XXXX XXXX XXXX XXXX WARNER LAW FIRM IN XXXX MI

Two unrelated complaints about the same kind of problem can therefore share a
large fraction of their tokens purely because both had names, dates and
addresses removed. Measuring similarity on the raw text would rank
heavily-redacted complaints as near-duplicates of each other and produce a pile
of false astroturfing hits.

Every redaction run is collapsed to a single sentinel token that is then dropped
from the shingle set, and ``redaction_ratio`` is reported per cluster so a
cluster that is only similar because it is mostly redacted can be recognised
and discarded.

WHAT A HIT MEANS
----------------
A cluster of near-identical narratives is not by itself proof of astroturfing.
Consumers copy template letters from credit-repair firms, consumer advocacy
sites and Reddit threads, and a credit-repair mill filing on behalf of many
real clients with real disputes produces the same signature as a fabricated
campaign. The metadata reported per cluster -- how many distinct companies,
states and days it spans -- is what distinguishes a coordinated filing operation
from a popular template, and neither is distinguishable from LLM-assisted
drafting on text alone.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Iterator

from ..store import Store

log = logging.getLogger(__name__)

# Runs of two or more X (the redaction marker), optionally slash/space joined.
REDACTION_RE = re.compile(r"\b[X]{2,}(?:[/\-\s][X]{2,})*\b", re.IGNORECASE)
NON_WORD_RE = re.compile(r"[^a-z0-9\s]+")
WS_RE = re.compile(r"\s+")

SENTINEL = "\x00redacted\x00"


@dataclass
class Cluster:
    """A group of narratives linked by shared MinHash bands.

    IMPORTANT -- ``size`` IS A CHAINED COMPONENT SIZE, NOT A COPY COUNT.
    Clusters are connected components under single linkage, so A joins C
    whenever some B is similar to both, even if A and C are not similar to each
    other. Measured on the full extract, the largest component showed pairwise
    Jaccard between members ranging from 0.36 to 1.00 against a 0.80 threshold:
    it is a chain of boilerplate variants sharing an opening paragraph, not one
    template repeated.

    Use ``cohesion_mean`` and ``cohesion_pct`` to judge a cluster. High cohesion
    means a genuine single template; low cohesion means a family of related
    texts, which is still interesting but must not be reported as N copies of
    one document. For an unimpeachable copy count, use
    ``exact_duplicate_groups`` instead -- byte-identical grouping cannot chain.
    """

    cluster_id: int
    size: int
    complaint_ids: list[int]
    companies: list[str]
    states: list[str]
    segments: list[str]
    first_date: str
    last_date: str
    day_span: int
    mean_redaction_ratio: float
    exemplar: str
    cohesion_mean: float | None = None
    cohesion_pct: float | None = None
    cohesion_sampled: int = 0

    def as_row(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "chained_size": self.size,
            "cohesion_mean": (
                round(self.cohesion_mean, 3) if self.cohesion_mean is not None else None
            ),
            "cohesion_pct_above_threshold": (
                round(self.cohesion_pct, 1) if self.cohesion_pct is not None else None
            ),
            "cohesion_sampled": self.cohesion_sampled,
            "distinct_companies": len(self.companies),
            "distinct_states": len(self.states),
            "first_date": self.first_date,
            "last_date": self.last_date,
            "day_span": self.day_span,
            "mean_redaction_ratio": round(self.mean_redaction_ratio, 3),
            "segments": ",".join(self.segments[:4]),
            "top_companies": " | ".join(self.companies[:3]),
            # Sample IDs make a cluster auditable: without them a reader cannot
            # pull the underlying complaints and check the finding.
            "sample_complaint_ids": " ".join(str(i) for i in self.complaint_ids[:20]),
            "exemplar": self.exemplar[:300],
        }


def normalize(text: str) -> tuple[str, float]:
    """Lowercase, strip punctuation, and neutralise redaction runs.

    Returns the normalised text plus the share of original tokens that were
    redaction markers.
    """
    if not text:
        return "", 0.0
    raw_tokens = text.split()
    subbed = REDACTION_RE.sub(f" {SENTINEL} ", text)
    lowered = subbed.lower()
    # Protect the sentinel from punctuation stripping.
    lowered = lowered.replace(SENTINEL, " \x01 ")
    cleaned = NON_WORD_RE.sub(" ", lowered).replace("\x01", SENTINEL)
    tokens = [t for t in WS_RE.split(cleaned) if t]
    redactions = sum(1 for t in tokens if t == SENTINEL)
    kept = [t for t in tokens if t != SENTINEL]
    ratio = redactions / max(len(raw_tokens), 1)
    return " ".join(kept), ratio


def shingles(text: str, k: int = 5) -> set[str]:
    """Word k-gram shingles, the unit of comparison for MinHash."""
    words = text.split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i: i + k]) for i in range(len(words) - k + 1)}


def exact_duplicate_groups(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    min_tokens: int = 25,
) -> list[dict[str, object]]:
    """Byte-identical (post-normalisation) narratives, grouped.

    Cheap, runs in one pass, and catches the least subtle form of templating.
    """
    groups: dict[str, list[tuple[int, str, str, str, str]]] = defaultdict(list)
    for row in _iter_narratives(store, segments, start, end):
        norm, _ratio = normalize(row["narrative"])
        if len(norm.split()) < min_tokens:
            continue
        digest = hashlib.sha1(norm.encode()).hexdigest()
        groups[digest].append(
            (
                row["complaint_id"], row["company"] or "", row["state"] or "",
                row["date_received"], row["segment"] or "",
            )
        )

    out = []
    for digest, members in groups.items():
        if len(members) < 2:
            continue
        dates = sorted(m[3] for m in members)
        out.append(
            {
                "hash": digest[:12],
                "size": len(members),
                "distinct_companies": len({m[1] for m in members}),
                "distinct_states": len({m[2] for m in members}),
                "first_date": dates[0],
                "last_date": dates[-1],
                "complaint_ids": [m[0] for m in members][:50],
            }
        )
    out.sort(key=lambda d: d["size"], reverse=True)
    return out


def _warn_on_thin_coverage(
    store: Store,
    segments: list[str] | None,
    start: str | None,
    end: str | None,
    floor_pct: float = 5.0,
) -> None:
    """Flag months where almost no narratives are published.

    Text-based astroturfing detection can only see complaints whose narrative
    was published. Where coverage is near zero, "no clusters found" means "no
    text to compare", not "no templating". Silence there would be the most
    misleading output this tool could produce, so it is announced loudly.
    """
    clauses = ["1=1"]
    params: list[object] = []
    if segments:
        clauses.append(f"segment IN ({','.join('?' * len(segments))})")
        params.extend(segments)
    if start:
        clauses.append("month >= ?")
        params.append(start[:7])
    if end:
        clauses.append("month <= ?")
        params.append(end[:7])

    rows = store.query(
        "SELECT month, COUNT(*) AS n, SUM(has_narrative) AS x FROM complaints "
        f"WHERE {' AND '.join(clauses)} GROUP BY month ORDER BY month",
        params,
    )
    thin = [
        (r["month"], r["n"], 100.0 * (r["x"] or 0) / r["n"])
        for r in rows
        if r["n"] and 100.0 * (r["x"] or 0) / r["n"] < floor_pct
    ]
    if not thin:
        return
    hidden = sum(n for _, n, _ in thin)
    log.warning(
        "NARRATIVE COVERAGE GAP: %d month(s) below %.0f%% narrative coverage, "
        "covering %s complaints that are effectively INVISIBLE to text "
        "analysis. Range %s..%s. A null result over this window means 'no text "
        "to compare', NOT 'no templating'.",
        len(thin), floor_pct, f"{hidden:,}", thin[0][0], thin[-1][0],
    )


def _optimal_bands(threshold: float, num_perm: int) -> tuple[int, int]:
    """Pick LSH band/row counts whose S-curve inflects near ``threshold``.

    The probability that two documents with Jaccard similarity s share at least
    one band is 1-(1-s^r)^b, which rises steeply around (1/b)^(1/r). Choosing
    (b, r) to put that point at the requested threshold is what makes the index
    both sensitive and cheap.
    """
    best, best_err = (16, 8), 1e9
    for r in range(1, num_perm + 1):
        b = num_perm // r
        if b < 1:
            continue
        err = abs((1.0 / b) ** (1.0 / r) - threshold)
        if err < best_err:
            best, best_err = (b, r), err
    return best


def near_duplicate_clusters(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    threshold: float = 0.8,
    num_perm: int = 64,
    shingle_k: int = 5,
    min_tokens: int = 25,
    max_redaction_ratio: float = 0.5,
    limit: int | None = None,
    max_group: int = 20_000,
    cohesion_min_size: int = 10,
    cohesion_sample: int = 40,
) -> list[Cluster]:
    """Cluster narratives by MinHash/LSH Jaccard similarity, backed by disk.

    ``max_redaction_ratio`` skips narratives that are mostly redaction markers,
    since their remaining text is too thin to compare meaningfully.

    WHY THE BAND INDEX LIVES ON DISK
    An in-memory LSH holds one entry per document per band, so the full
    credit_reporting narrative set (2.5M complaints) needs tens of gigabytes and
    simply will not run. Band signatures are therefore written to a temporary
    SQLite database and grouped with SQL, which keeps resident memory to the
    union-find structure alone and makes the pass scale to the whole database.
    Only documents that actually land in a cluster are ever re-read for their
    text and metadata.
    """
    import numpy as np
    from datasketch import MinHash

    from .. import config

    _warn_on_thin_coverage(store, segments, start, end)

    bands, rows_per_band = _optimal_bands(threshold, num_perm)
    achieved = (1.0 / bands) ** (1.0 / rows_per_band)
    log.info(
        "LSH: num_perm=%d -> %d bands x %d rows (S-curve inflects at %.2f, "
        "requested %.2f)", num_perm, bands, rows_per_band, achieved, threshold,
    )

    band_db_path = config.CACHE_DIR / "lsh_bands.sqlite"
    if band_db_path.exists():
        band_db_path.unlink()
    band_db = sqlite3.connect(band_db_path)
    band_db.execute("PRAGMA journal_mode=OFF")
    band_db.execute("PRAGMA synchronous=OFF")
    band_db.execute(
        "CREATE TABLE bands (band INTEGER, sig BLOB, complaint_id INTEGER)"
    )

    n_seen = n_kept = 0
    batch: list[tuple[int, bytes, int]] = []
    for row in _iter_narratives(store, segments, start, end, limit=limit):
        n_seen += 1
        norm, ratio = normalize(row["narrative"])
        if len(norm.split()) < min_tokens or ratio > max_redaction_ratio:
            continue
        sh = shingles(norm, shingle_k)
        if not sh:
            continue

        m = MinHash(num_perm=num_perm)
        # update_batch vectorises the permutation maths; per-shingle update()
        # is roughly an order of magnitude slower at this document count.
        m.update_batch([s.encode() for s in sh])

        cid = int(row["complaint_id"])
        sig = np.asarray(m.hashvalues, dtype=np.uint64)
        for b in range(bands):
            chunk = sig[b * rows_per_band: (b + 1) * rows_per_band]
            batch.append((b, chunk.tobytes(), cid))

        n_kept += 1
        if len(batch) >= 200_000:
            band_db.executemany("INSERT INTO bands VALUES (?,?,?)", batch)
            batch.clear()
        if n_kept % 100_000 == 0:
            log.info("signed %s narratives", f"{n_kept:,}")

    if batch:
        band_db.executemany("INSERT INTO bands VALUES (?,?,?)", batch)
    band_db.commit()
    log.info("signed %s of %s narratives; grouping bands",
             f"{n_kept:,}", f"{n_seen:,}")

    band_db.execute("CREATE INDEX ix_bands ON bands(band, sig)")
    band_db.commit()

    # Union-find over documents sharing any band signature.
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    cur = band_db.execute(
        "SELECT GROUP_CONCAT(complaint_id) FROM bands "
        "GROUP BY band, sig HAVING COUNT(*) > 1"
    )
    oversized = 0
    while True:
        chunk = cur.fetchmany(10_000)
        if not chunk:
            break
        for (ids,) in chunk:
            members = [int(x) for x in ids.split(",")]
            if len(members) > max_group:
                # A single band shared by this many documents means degenerate
                # text (e.g. near-empty after redaction stripping). Linking them
                # all would fuse unrelated clusters into one blob.
                oversized += 1
                continue
            first = members[0]
            for other in members[1:]:
                union(first, other)
    band_db.close()
    band_db_path.unlink(missing_ok=True)
    if oversized:
        log.warning(
            "skipped %d band group(s) larger than %s documents; raise "
            "min_tokens if this is high", oversized, f"{max_group:,}",
        )

    components: dict[int, list[int]] = {}
    for node in parent:
        components.setdefault(find(node), []).append(node)
    comps = [m for m in components.values() if len(m) >= 2]
    log.info("found %s clusters covering %s complaints",
             f"{len(comps):,}", f"{sum(len(c) for c in comps):,}")

    # Only clustered documents need their text and metadata read back.
    meta, texts = _load_members(store, comps)

    clusters = [
        _build_cluster(i + 1, members, meta, texts)
        for i, members in enumerate(comps)
    ]
    _measure_cohesion(
        store, clusters, threshold=threshold, shingle_k=shingle_k,
        min_size=cohesion_min_size, sample=cohesion_sample,
    )
    clusters.sort(key=lambda c: c.size, reverse=True)
    for i, c in enumerate(clusters, start=1):
        c.cluster_id = i
    return clusters


def _measure_cohesion(
    store: Store,
    clusters: list[Cluster],
    threshold: float,
    shingle_k: int,
    min_size: int,
    sample: int,
) -> None:
    """Attach a within-cluster similarity measure to each cluster, in place.

    Single-linkage components can chain dissimilar documents together, so the
    component size alone says nothing about whether one template is being
    reused. This samples members, compares each against the cluster exemplar,
    and records the mean Jaccard plus the share meeting the requested
    threshold. Without it, a chained family of variants is indistinguishable
    from a genuine mass-copied template.
    """
    targets = [c for c in clusters if c.size >= min_size]
    if not targets:
        return
    log.info("measuring cohesion for %s clusters (sample up to %d each)",
             f"{len(targets):,}", sample)

    for n_done, cluster in enumerate(targets, start=1):
        ids = cluster.complaint_ids[:sample]
        if len(ids) < 2:
            continue
        placeholders = ",".join("?" * len(ids))
        rows = store.query(
            f"SELECT complaint_id, narrative FROM complaints "
            f"WHERE complaint_id IN ({placeholders})",
            ids,
        )
        shingle_sets: dict[int, set[str]] = {}
        for r in rows:
            norm, _ = normalize(r["narrative"] or "")
            sh = shingles(norm, shingle_k)
            if sh:
                shingle_sets[int(r["complaint_id"])] = sh
        if len(shingle_sets) < 2:
            continue

        # Compare against the exemplar, which is the first member.
        anchor_id = cluster.complaint_ids[0]
        anchor = shingle_sets.get(anchor_id) or next(iter(shingle_sets.values()))
        sims = []
        for cid, sh in shingle_sets.items():
            if sh is anchor:
                continue
            union = anchor | sh
            sims.append(len(anchor & sh) / len(union) if union else 0.0)
        if not sims:
            continue
        cluster.cohesion_mean = sum(sims) / len(sims)
        cluster.cohesion_pct = 100.0 * sum(
            1 for s in sims if s >= threshold
        ) / len(sims)
        cluster.cohesion_sampled = len(sims)

        if n_done % 2_000 == 0:
            log.info("  cohesion measured for %s/%s clusters",
                     f"{n_done:,}", f"{len(targets):,}")


def _load_members(
    store: Store, comps: list[list[int]], exemplar_chars: int = 600
) -> tuple[dict[int, dict[str, object]], dict[int, str]]:
    """Fetch metadata for clustered complaints, and text for exemplars only."""
    meta: dict[int, dict[str, object]] = {}
    texts: dict[int, str] = {}
    exemplars = {members[0] for members in comps}

    all_ids = [cid for members in comps for cid in members]
    for i in range(0, len(all_ids), 5_000):
        chunk = all_ids[i: i + 5_000]
        placeholders = ",".join("?" * len(chunk))
        for row in store.query(
            "SELECT complaint_id, company, state, date_received, segment, "
            f"narrative FROM complaints WHERE complaint_id IN ({placeholders})",
            chunk,
        ):
            cid = int(row["complaint_id"])
            norm, ratio = normalize(row["narrative"] or "")
            meta[cid] = {
                "company": row["company"] or "",
                "state": row["state"] or "",
                "date": row["date_received"],
                "segment": row["segment"] or "",
                "ratio": ratio,
            }
            if cid in exemplars:
                texts[cid] = norm[:exemplar_chars]
    return meta, texts


def _build_cluster(
    cid: int,
    members: list[int],
    meta: dict[int, dict[str, object]],
    texts: dict[int, str],
) -> Cluster:
    import pandas as pd

    # Guard against a member whose metadata read back empty; better a slightly
    # smaller cluster than a crash three hours into a pass.
    members = [m for m in members if m in meta] or members[:1]
    dates = sorted(str(meta[m]["date"]) for m in members if m in meta)
    span = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    companies = sorted({str(meta[m]["company"]) for m in members if meta[m]["company"]})
    states = sorted({str(meta[m]["state"]) for m in members if meta[m]["state"]})
    segs = sorted({str(meta[m]["segment"]) for m in members})
    ratios = [float(meta[m]["ratio"]) for m in members if m in meta] or [0.0]
    exemplar = texts.get(members[0], "")
    return Cluster(
        cluster_id=cid,
        size=len(members),
        complaint_ids=sorted(members)[:100],
        companies=companies,
        states=states,
        segments=segs,
        first_date=dates[0],
        last_date=dates[-1],
        day_span=int(span),
        mean_redaction_ratio=sum(ratios) / len(ratios),
        exemplar=exemplar,
    )


def _iter_narratives(
    store: Store,
    segments: list[str] | None,
    start: str | None,
    end: str | None,
    limit: int | None = None,
    batch: int = 20_000,
) -> Iterator[dict[str, object]]:
    """Stream narrative rows without loading millions of them into memory."""
    clauses = ["has_narrative = 1", "narrative IS NOT NULL", "narrative <> ''"]
    params: list[object] = []
    if segments:
        clauses.append(f"segment IN ({','.join('?' * len(segments))})")
        params.extend(segments)
    if start:
        clauses.append("date_received >= ?")
        params.append(start)
    if end:
        clauses.append("date_received <= ?")
        params.append(end)

    sql = (
        "SELECT complaint_id, narrative, company, state, date_received, segment "
        f"FROM complaints WHERE {' AND '.join(clauses)} ORDER BY complaint_id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    cur = store.conn.execute(sql, params)
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            return
        for r in rows:
            yield dict(r)
