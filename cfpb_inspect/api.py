"""CFPB Consumer Complaint Database API client.

Verified behaviour of the upstream API (probed 2026-08-20):

* The base path REQUIRES its trailing slash. Without it the request is served
  the HTML search page instead of JSON, and ``format=json`` 404s -- there is no
  such parameter, JSON is the default and ``format`` only accepts ``csv``.
* ``frm`` is hard-capped at 10000, so JSON paging cannot walk a result set
  larger than ~10k. Bulk extraction must use ``format=csv``.
* ``format=csv`` IGNORES ``size`` and streams the matching result set, up to a
  cap of 100,000 rows. Verified: a 3-day window reported 15,001 hits in JSON
  and returned exactly 15,001 CSV data rows; 97,904 rows exported fine while
  101,137 returned HTTP 400. Beyond the cap the window must be subdivided.
* Error bodies are NOT JSON. A 400 over the row cap returns the bare string
  ``size``; a rate-limited request returns ``detail``. Do not try to parse them.
* ``date_received_max`` is INCLUSIVE.
* The edge rejects spoofed-browser User-Agents; see config.USER_AGENT.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import date, timedelta
from typing import Any, Iterator

import requests

from . import config

log = logging.getLogger(__name__)

# This network terminates TLS at an inspecting proxy whose root CA lives in the
# Windows certificate store but not in certifi's bundle, so requests fails with
# CERTIFICATE_VERIFY_FAILED where urllib succeeds. truststore routes
# verification through the OS trust store, which fixes it without the obvious
# and unacceptable alternative of disabling verification.
try:  # pragma: no cover - environment dependent
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    log.warning(
        "truststore unavailable; TLS verification uses certifi and may fail "
        "behind an inspecting proxy. Install it with: pip install truststore"
    )

# CSV column header -> our internal field name
CSV_FIELDS: dict[str, str] = {
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Consumer complaint narrative": "narrative",
    "Company public response": "company_public_response",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Date sent to company": "date_sent_to_company",
    "Company response to consumer": "company_response",
    "Timely response?": "timely",
    "Complaint ID": "complaint_id",
}


class RateLimited(RuntimeError):
    pass


class CsvRowLimitExceeded(ValueError):
    """A CSV export matched more rows than config.MAX_CSV_ROWS.

    Raised as its own type so the fetch driver can subdivide the window and
    retry, rather than treating it as a fatal parameter error. This must stay
    recoverable: the count probe that sizes a window is a separate query from
    the export, so backfill arriving between the two can push a window that was
    measured as safe over the cap.
    """


class CFPBClient:
    """Throttled, retrying client for the complaint search API."""

    def __init__(
        self,
        throttle: float = config.THROTTLE_SECONDS,
        timeout: int = config.REQUEST_TIMEOUT,
        max_retries: int = config.MAX_RETRIES,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(config.DEFAULT_HEADERS)
        self.throttle = throttle
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request = 0.0
        self.request_count = 0
        self.bytes_downloaded = 0

    # -- plumbing ----------------------------------------------------------

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle:
            time.sleep(self.throttle - elapsed)

    def _request(self, params: dict[str, Any]) -> requests.Response:
        """GET with throttle plus exponential backoff.

        Retries 403 as well as 429/5xx: the edge WAF returns 403 for
        rate-tripped requests that succeed on a later attempt.
        """
        clean = {k: v for k, v in params.items() if v is not None}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            self._wait()
            self._last_request = time.monotonic()
            try:
                resp = self.session.get(
                    config.API_ROOT, params=clean, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                backoff = min(60.0, 2.0 ** attempt * 2.0)
                log.warning(
                    "request error (%s), retry %d/%d in %.0fs",
                    exc, attempt + 1, self.max_retries, backoff,
                )
                time.sleep(backoff)
                continue

            self.request_count += 1

            if resp.status_code == 200:
                self.bytes_downloaded += len(resp.content)
                return resp

            if resp.status_code == 400:
                # Error bodies are bare field names, not JSON. A complaint
                # about `size` on a CSV export means the row cap was exceeded,
                # which the caller can fix by narrowing the window.
                body = resp.text.strip()[:300]
                if body == "size" and clean.get("format") == "csv":
                    raise CsvRowLimitExceeded(
                        f"CSV export exceeded {config.MAX_CSV_ROWS:,} rows for "
                        f"{clean.get('date_received_min')}.."
                        f"{clean.get('date_received_max')}"
                    )
                # Any other 400 is a genuine parameter error; retrying will not
                # help.
                raise ValueError(
                    f"API rejected parameters: {body} (params={clean})"
                )

            if resp.status_code in (403, 429) or resp.status_code >= 500:
                backoff = min(120.0, 2.0 ** attempt * 3.0)
                log.warning(
                    "HTTP %d, retry %d/%d in %.0fs",
                    resp.status_code, attempt + 1, self.max_retries, backoff,
                )
                last_error = RateLimited(f"HTTP {resp.status_code}")
                time.sleep(backoff)
                continue

            resp.raise_for_status()

        raise RateLimited(
            f"giving up after {self.max_retries} attempts: {last_error}"
        )

    # -- queries -----------------------------------------------------------

    def count(self, **filters: Any) -> int:
        """Number of complaints matching the given filters."""
        resp = self._request({**filters, "size": 0, "no_aggs": "true"})
        return int(resp.json()["hits"]["total"]["value"])

    def aggregate(self, **filters: Any) -> dict[str, list[dict[str, Any]]]:
        """Bucket counts for a filter set, keyed by aggregation name.

        The API nests each aggregation inconsistently, so buckets are located
        by search rather than by a fixed path.
        """
        resp = self._request({**filters, "size": 0})
        raw = resp.json().get("aggregations", {})
        out: dict[str, list[dict[str, Any]]] = {}
        for name, node in raw.items():
            buckets = _find_buckets(node)
            if buckets is not None:
                out[name] = buckets
        return out

    def sample(self, size: int = 1, **filters: Any) -> list[dict[str, Any]]:
        """A few raw _source records, for inspection and testing."""
        size = min(size, config.MAX_SIZE)
        resp = self._request({**filters, "size": size, "no_aggs": "true"})
        return [h["_source"] for h in resp.json()["hits"]["hits"]]

    def fetch_csv_rows(
        self, date_min: str, date_max: str, **filters: Any
    ) -> list[dict[str, str]]:
        """All complaints in an inclusive date window, via the CSV export.

        Returns rows keyed by our internal field names.
        """
        resp = self._request(
            {
                **filters,
                "date_received_min": date_min,
                "date_received_max": date_max,
                "format": "csv",
                "no_aggs": "true",
            }
        )
        text = resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []
        unknown = set(reader.fieldnames) - set(CSV_FIELDS)
        if unknown:
            # Upstream added columns; surface it rather than dropping data.
            log.warning("unrecognised CSV columns from API: %s", sorted(unknown))
        return [
            {CSV_FIELDS[k]: v for k, v in row.items() if k in CSV_FIELDS}
            for row in reader
        ]

    # -- windowed extraction ----------------------------------------------

    def iter_windows(
        self,
        start: str,
        end: str,
        target_rows: int = 40_000,
        min_days: int = 1,
        **filters: Any,
    ) -> Iterator[tuple[str, str, int]]:
        """Split an inclusive date range into windows of ~target_rows rows.

        Uses cheap count() probes to size each window before any bulk download,
        so a high-volume month gets split while a sparse year is fetched in one
        request. Yields (window_start, window_end, expected_rows).

        A single day exceeding target_rows is still emitted whole: the window
        cannot narrow below one day, because date_received filtering has day
        granularity.
        """
        cur = date.fromisoformat(start)
        final = date.fromisoformat(end)
        span = 90  # days; adapts as we learn local density

        while cur <= final:
            win_end = min(final, cur + timedelta(days=span - 1))
            n = self.count(
                date_received_min=cur.isoformat(),
                date_received_max=win_end.isoformat(),
                **filters,
            )

            # Too dense: shrink and re-probe, unless already at one day.
            while n > target_rows and (win_end - cur).days + 1 > min_days:
                width = (win_end - cur).days + 1
                shrink = max(min_days, int(width * target_rows / max(n, 1)))
                if shrink >= width:
                    break
                win_end = min(final, cur + timedelta(days=shrink - 1))
                n = self.count(
                    date_received_min=cur.isoformat(),
                    date_received_max=win_end.isoformat(),
                    **filters,
                )

            days = (win_end - cur).days + 1
            if n:
                yield cur.isoformat(), win_end.isoformat(), n

            # Adapt the next probe span to the density just measured.
            per_day = max(n / days, 0.01)
            span = max(min_days, min(365, int(target_rows / per_day)))
            cur = win_end + timedelta(days=1)


def _find_buckets(node: Any) -> list[dict[str, Any]] | None:
    """Locate the buckets list inside a nested aggregation response."""
    if isinstance(node, dict):
        if "buckets" in node and isinstance(node["buckets"], list):
            return node["buckets"]
        for value in node.values():
            found = _find_buckets(value)
            if found is not None:
                return found
    return None
