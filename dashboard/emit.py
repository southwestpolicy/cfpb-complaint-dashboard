"""Compute dashboard.json from the aggregate index.

    python dashboard/emit.py [--out dashboard/public/data/dashboard.json]

The output is a few tens of kilobytes and is the only artefact the website
consumes. Everything the page shows is precomputed here, so the browser does no
analysis and the web host needs no database.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.build_index import ALL_HASH, open_index  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
POP_CSV = REPO / "cfpb_inspect" / "reference" / "state_population.csv"

# A text counts as a template at this many uses. Matches the published paper so
# the dashboard and the report cannot disagree.
TEMPLATE_MIN = 50
TREND_FROM = "2016-01"
# Narrative publication lags the complaint by weeks, so recent months
# understate the templated share until they fill in. Months below this
# narrative count are withheld from the trend rather than shown as a false dip.
MIN_NARRATIVES_FOR_TREND = 150

SEG_LABEL = {
    "credit_reporting": "Credit reporting",
    "debt_collection": "Debt collection",
    "mortgage": "Mortgage",
    "card": "Cards",
    "student_loan": "Student loans",
    "consumer_loan": "Consumer loans",
}
NON_STATES = {"PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP", "FM", "MH",
              "PW", "UM", ""}


def _display_name(name: str) -> str:
    """Presentable form of a corporate group key.

    Mapped groups already carry proper casing ("TransUnion"). Unmapped firms
    fall back to the normalisation key, which is upper-case and would shout on
    a public page, so those are title-cased.
    """
    if not name.isupper():
        return name
    small = {"of", "and", "the", "for", "de", "at"}
    words = []
    for i, w in enumerate(name.split()):
        if len(w) <= 3 and w.isalpha() and w.lower() not in small and i == 0:
            words.append(w)           # keep short initialisms such as CNG, LDF
        elif w.lower() in small and i:
            words.append(w.lower())
        else:
            words.append(w.capitalize())
    return " ".join(words)


def _complete_months(conn) -> list[str]:
    """Months with data, excluding the current (partial) one."""
    rows = [r[0] for r in conn.execute(
        "SELECT DISTINCT month FROM monthly ORDER BY month")]
    this_month = date.today().strftime("%Y-%m")
    return [m for m in rows if m < this_month]


def build(conn) -> dict:
    months = _complete_months(conn)
    last_month = months[-1] if months else None

    # ---- template set -----------------------------------------------------
    templates = {h for (h,) in conn.execute(
        "SELECT hash FROM text_month GROUP BY hash HAVING SUM(n) >= ?",
        (TEMPLATE_MIN,))} - {ALL_HASH}
    n_templates = len(templates)

    # ---- templating trend, per segment is not derivable from text_month ----
    # text_month is not segmented (a hash can appear in several segments), so
    # the trend is reported for the corpus as a whole plus the two segments
    # that carry the phenomenon, using narrative counts from `monthly`.
    tmpl_by_month = defaultdict(int)
    narr_by_month = defaultdict(int)
    for h, m, n in conn.execute("SELECT hash, month, n FROM text_month"):
        narr_by_month[m] += n
        if h in templates:
            tmpl_by_month[m] += n

    trend = []
    for m in months:
        if m < TREND_FROM:
            continue
        tot = narr_by_month.get(m, 0)
        if tot < MIN_NARRATIVES_FOR_TREND:
            continue
        trend.append({"month": m, "narratives": tot,
                      "templated": tmpl_by_month.get(m, 0),
                      "pct": round(100 * tmpl_by_month.get(m, 0) / tot, 2)})

    # ---- volume by segment ------------------------------------------------
    vol = defaultdict(dict)
    seg_totals = defaultdict(lambda: [0, 0])
    for seg, m, c, nn in conn.execute(
            "SELECT segment, month, complaints, narratives FROM monthly"):
        if m in set(months):
            vol[seg][m] = c
        seg_totals[seg][0] += c
        seg_totals[seg][1] += nn

    volume = {
        "months": months,
        "series": [{"segment": s, "label": SEG_LABEL.get(s, s),
                    "counts": [vol[s].get(m, 0) for m in months]}
                   for s in sorted(vol, key=lambda s: -seg_totals[s][0])],
    }

    # ---- states -----------------------------------------------------------
    pop = {}
    if POP_CSV.exists():
        with POP_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pop.setdefault(row["state"], {})[int(row["year"])] = int(row["population"])
    latest_pop_year = max((max(v) for v in pop.values()), default=None)

    # most recent 12 complete months
    window = months[-12:]
    win_set = set(window)
    st_complaints = defaultdict(int)
    st_narr = defaultdict(int)
    for st, m, c, nn in conn.execute(
            "SELECT state, month, complaints, narratives FROM state_month"):
        if m in win_set:
            st_complaints[st] += c
            st_narr[st] += nn
    # The denominator comes from the ALL_HASH sentinel row, not from summing
    # the surviving per-text rows: those are pruned to repeated texts, so
    # summing them would divide templated counts by a subset of themselves and
    # report ~85% templated everywhere.
    st_tmpl = defaultdict(int)
    st_scored = defaultdict(int)
    for h, st, m, n in conn.execute(
            "SELECT hash, state, month, n FROM text_state_month"):
        if m not in win_set:
            continue
        if h == ALL_HASH:
            st_scored[st] += n
        elif h in templates:
            st_tmpl[st] += n

    states = []
    for st, c in sorted(st_complaints.items(), key=lambda kv: -kv[1]):
        if st in NON_STATES or st not in pop:
            continue
        p = pop[st].get(latest_pop_year)
        if not p:
            continue
        scored = st_scored.get(st, 0)
        states.append({
            "state": st,
            "complaints": c,
            "per_100k": round(c / p * 100_000, 1),
            "templated_pct": (round(100 * st_tmpl.get(st, 0) / scored, 1)
                              if scored >= 200 else None),
        })

    # ---- companies --------------------------------------------------------
    comp = defaultdict(int)
    comp_narr = defaultdict(int)
    for name, seg, m, c, nn in conn.execute(
            "SELECT company, segment, month, complaints, narratives FROM company_month"):
        if m in win_set:
            comp[name] += c
            comp_narr[name] += nn
    # Templated share per company, over the same window. Two reasons a company
    # legitimately has no rows here, and both produce None rather than a
    # misleading zero:
    #
    #   * text_company_month is kept only for the busiest firms
    #     (COMPANY_DETAIL_TOP in build_index.py);
    #   * the join is on the grouped company key, and those keys are only
    #     consistent across tables if every table was written by the same
    #     version of cfpb_inspect.companies. An index whose company_month
    #     predates an alias being added holds the old key -- 'LEXISNEXIS' where
    #     the current grouping yields 'LexisNexis' -- and the two do not meet.
    #     A full `build_index.py --bootstrap` re-keys every table at once and is
    #     the only thing that fixes it; matching loosely here would risk
    #     attributing one firm's narratives to another.
    #
    # The denominator is the ALL_HASH sentinel row -- scored narratives for that
    # company and month -- not the `narratives` column of company_month. The two
    # differ: company_month counts every complaint that arrived with a narrative,
    # while only narratives long enough to score are hashed. Dividing templated
    # counts by the larger figure would understate every share.
    co_tmpl: dict[str, int] = defaultdict(int)
    co_scored: dict[str, int] = defaultdict(int)
    for h, name, m, n in conn.execute(
            "SELECT hash, company, month, n FROM text_company_month"):
        if m not in win_set:
            continue
        if h == ALL_HASH:
            co_scored[name] += n
        elif h in templates:
            co_tmpl[name] += n

    companies = []
    for n, c in sorted(comp.items(), key=lambda kv: -kv[1])[:20]:
        if not n:
            continue
        scored = co_scored.get(n, 0)
        companies.append({
            "company": _display_name(n),
            "complaints": c,
            "narratives": comp_narr.get(n, 0),
            # Same floor as the state panel: below this the percentage swings on
            # a handful of filings and reads as precision that is not there.
            "templated_pct": (round(100 * co_tmpl.get(n, 0) / scored, 1)
                              if scored >= 200 else None),
        })

    # ---- relief -----------------------------------------------------------
    # Two years of complete months. A single calendar year lands on 2026, where
    # credit-reporting narrative publication has collapsed, leaving the
    # templated bucket too thin to compare. Both buckets contain only
    # complaints that have a scored narrative, so like is compared with like.
    rel = defaultdict(lambda: {"templated": [0, 0], "organic": [0, 0]})
    relief_window = months[-24:]
    recent = set(relief_window)
    for seg, m, h, relieved, n in conn.execute(
            "SELECT segment, month, hash, relieved, n FROM relief_month"):
        if m not in recent:
            continue
        kind = "templated" if (h and h in templates) else "organic"
        rel[seg][kind][0] += n              # closed
        if relieved:
            rel[seg][kind][1] += n          # relieved

    # Both sides need enough closed complaints to be worth comparing. Segments
    # with almost no templated filings -- mortgages, student loans -- would
    # otherwise show a headline percentage computed from a handful of cases.
    MIN_CLOSED = 500
    relief = []
    for seg, v in rel.items():
        row = {"segment": seg, "label": SEG_LABEL.get(seg, seg)}
        for kind in ("templated", "organic"):
            closed, got = v[kind]
            row[kind] = {"closed": closed,
                         "relief_pct": round(100 * got / closed, 1) if closed else None}
        if all(row[k]["closed"] >= MIN_CLOSED for k in ("templated", "organic")):
            relief.append(row)
    relief.sort(key=lambda r: -(r["templated"]["closed"] + r["organic"]["closed"]))

    total_complaints = sum(v[0] for v in seg_totals.values())
    total_narr = sum(v[1] for v in seg_totals.values())
    scored_total = sum(narr_by_month.values())
    tmpl_total = sum(tmpl_by_month.values())

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_through": conn.execute(
                "SELECT value FROM meta WHERE key='last_date'").fetchone()[0],
            "last_complete_month": last_month,
            "template_threshold": TEMPLATE_MIN,
            "source": "CFPB Consumer Complaint Database public API",
            "publisher": "Southwest Public Policy Institute",
            "window_months": len(window),
        },
        "headline": {
            "complaints": total_complaints,
            "narratives": total_narr,
            "scored_narratives": scored_total,
            "templated": tmpl_total,
            "templated_pct": round(100 * tmpl_total / scored_total, 2) if scored_total else None,
            "distinct_templates": n_templates,
        },
        "trend": trend,
        "volume": volume,
        "states": states,
        "companies": companies,
        "relief": relief,
        "relief_window": {"from": relief_window[0] if relief_window else None,
                          "to": relief_window[-1] if relief_window else None,
                          "months": len(relief_window)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "dashboard" / "public" / "data" / "dashboard.json"))
    a = ap.parse_args()
    conn = open_index()
    payload = build(conn)
    conn.close()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    h = payload["headline"]
    print(f"wrote {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"  data through {payload['meta']['data_through']}, "
          f"{h['complaints']:,} complaints, {h['templated_pct']}% templated")
    print(f"  trend points {len(payload['trend'])}, states {len(payload['states'])}, "
          f"companies {len(payload['companies'])}, relief rows {len(payload['relief'])}")


if __name__ == "__main__":
    main()
