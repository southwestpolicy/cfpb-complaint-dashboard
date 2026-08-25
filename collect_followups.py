"""Second-round analyses: discriminate paid operations from viral DIY scripts,
de-mechanise the geography result, and test whether templated filing works.

Writes out/followups.json.

Motivation for each block:

A) TEMPLATE LIFESPAN. Exact-duplicate text alone cannot separate a paid
   credit-repair firm's client book from a free script circulating on social
   media. Sustained multi-year distribution against the same respondents looks
   like a business; a short sharp burst looks like a video going viral.

B) DAY OF WEEK. A paid operation files on business days. Consumers filing for
   themselves spread into weekends. This is a provenance discriminator that
   needs no assumption about who the filer is.

C) GEOGRAPHY, DE-MECHANISED. Templated complaints sit inside the numerator of
   the per-capita filing rate, so part of the rate/templating correlation is
   arithmetic rather than evidence. Splitting each state's narratives into
   templated and non-templated and rating each separately removes that, and
   also addresses the obvious rebuttal: that high-templating states simply have
   worse credit-score distributions and therefore more genuine disputes.

D) DOES IT WORK. company_response is the outcome field. Comparing relief rates
   for templated against organic complaints tests empirically whether consumers
   are getting anything for a templated filing.

E) LEXINGTON LAW. The company field names the RESPONDENT, not the filer, so a
   spike for a credit-repair firm means complaints AGAINST it.

F) AUGUST 2026. Daily volume at the end of the extract, to characterise the
   narrative-coverage collapse and check for any cessation signature.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfpb_inspect import config
from cfpb_inspect.analysis.dedupe import normalize
from cfpb_inspect.analysis.geo import NON_STATES, load_population
from cfpb_inspect.store import Store

MIN_TOKENS = 25
MIN_GROUP = 50
RELIEF = {"Closed with monetary relief", "Closed with non-monetary relief"}
NON_FINAL = {"In progress", ""}


def main() -> None:
    store = Store()
    out: dict[str, object] = {}

    print("pass 1: hashing narratives...")
    recs: list[tuple[bytes, str, str, str, str, str]] = []
    counts: Counter[bytes] = Counter()
    cur = store.conn.execute(
        "SELECT segment, date_received, state, company_response, company, narrative "
        "FROM complaints WHERE has_narrative = 1 AND narrative IS NOT NULL "
        "AND narrative <> ''"
    )
    n = 0
    while True:
        rows = cur.fetchmany(50_000)
        if not rows:
            break
        for seg, dt, state, resp, comp, narr in rows:
            norm, _ = normalize(narr)
            if len(norm.split()) < MIN_TOKENS:
                continue
            h = hashlib.sha1(norm.encode()).digest()[:8]
            recs.append((h, seg, dt[:10], state or "", resp or "", comp or ""))
            counts[h] += 1
            n += 1
        if n % 1_000_000 < 50_000:
            print(f"  {n:,}")
    templates = {h for h, c in counts.items() if c >= MIN_GROUP}
    print(f"  {n:,} scored, {len(templates):,} templates")

    # ---- A) template lifespan -------------------------------------------
    span: dict[bytes, list] = defaultdict(lambda: ["9999", "0000", 0, set()])
    for h, seg, dt, state, resp, comp in recs:
        if h not in templates:
            continue
        s = span[h]
        s[0] = min(s[0], dt)
        s[1] = max(s[1], dt)
        s[2] += 1
        s[3].add(comp)

    buckets = [(0, 90, "under 3 months"), (90, 365, "3-12 months"),
               (365, 730, "1-2 years"), (730, 10**5, "over 2 years")]
    life_rows = []
    for lo, hi, label in buckets:
        sel = [
            (h, v) for h, v in span.items()
            if lo <= (date.fromisoformat(v[1]) - date.fromisoformat(v[0])).days < hi
        ]
        life_rows.append({
            "band": label,
            "templates": len(sel),
            "complaints": sum(v[2] for _, v in sel),
            "median_firms": (
                sorted(len(v[3]) for _, v in sel)[len(sel) // 2] if sel else 0
            ),
        })
    out["template_lifespan"] = life_rows

    # ---- B) day of week --------------------------------------------------
    dow_t = Counter()
    dow_o = Counter()
    for h, seg, dt, state, resp, comp in recs:
        if seg != "credit_reporting":
            continue
        wd = date.fromisoformat(dt).weekday()  # 0=Mon
        (dow_t if h in templates else dow_o)[wd] += 1
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    tt, to = sum(dow_t.values()), sum(dow_o.values())
    out["day_of_week"] = {
        "templated": {names[i]: round(100 * dow_t[i] / tt, 2) for i in range(7)},
        "organic": {names[i]: round(100 * dow_o[i] / to, 2) for i in range(7)},
        "templated_weekend_pct": round(100 * (dow_t[5] + dow_t[6]) / tt, 2),
        "organic_weekend_pct": round(100 * (dow_o[5] + dow_o[6]) / to, 2),
        "n_templated": tt, "n_organic": to,
    }

    # ---- C) geography, de-mechanised ------------------------------------
    pop = load_population()
    py = int(pop["year"].max())
    pmap = pop[pop["year"] == py].set_index("state")["population"].to_dict()
    st_t: Counter[str] = Counter()
    st_o: Counter[str] = Counter()
    for h, seg, dt, state, resp, comp in recs:
        if seg != "credit_reporting" or not dt.startswith("2025"):
            continue
        if not state or state in NON_STATES or state not in pmap:
            continue
        (st_t if h in templates else st_o)[state] += 1

    geo = []
    for s in sorted(set(st_t) | set(st_o)):
        tot = st_t[s] + st_o[s]
        if tot < 200:
            continue
        geo.append({
            "state": s,
            "templated_per_100k": round(st_t[s] / pmap[s] * 100_000, 1),
            "organic_per_100k": round(st_o[s] / pmap[s] * 100_000, 1),
            "templated_narratives": st_t[s],
            "organic_narratives": st_o[s],
        })
    geo.sort(key=lambda r: -r["templated_per_100k"])
    out["geo_split"] = geo

    import numpy as np

    t = np.array([r["templated_per_100k"] for r in geo])
    o = np.array([r["organic_per_100k"] for r in geo])
    out["geo_split_stats"] = {
        "n_states": len(geo),
        "templated_max_min_ratio": round(float(t.max() / max(t.min(), 1e-9)), 1),
        "organic_max_min_ratio": round(float(o.max() / max(o.min(), 1e-9)), 1),
        "templated_cv": round(float(t.std() / t.mean()), 3),
        "organic_cv": round(float(o.std() / o.mean()), 3),
        "correlation_templated_vs_organic": round(float(np.corrcoef(t, o)[0, 1]), 3),
    }

    # ---- D) does it work -------------------------------------------------
    def relief(seg: str, year: str) -> dict:
        res = {"templated": Counter(), "organic": Counter()}
        for h, s, dt, state, resp, comp in recs:
            if s != seg or not dt.startswith(year) or resp in NON_FINAL:
                continue
            res["templated" if h in templates else "organic"][resp] += 1
        outd = {}
        for k, c in res.items():
            tot = sum(c.values())
            if not tot:
                continue
            outd[k] = {
                "n": tot,
                "relief_pct": round(100 * sum(c[r] for r in RELIEF) / tot, 2),
                "monetary_pct": round(
                    100 * c["Closed with monetary relief"] / tot, 3),
                "nonmonetary_pct": round(
                    100 * c["Closed with non-monetary relief"] / tot, 2),
                "explanation_pct": round(
                    100 * c["Closed with explanation"] / tot, 2),
                "breakdown": dict(c.most_common(6)),
            }
        return outd

    out["relief"] = {
        "credit_reporting_2024": relief("credit_reporting", "2024"),
        "credit_reporting_2023": relief("credit_reporting", "2023"),
        "debt_collection_2024": relief("debt_collection", "2024"),
    }

    # ---- E) Lexington Law / John C Heath ---------------------------------
    lex = [
        dict(r) for r in store.query(
            "SELECT month, COUNT(*) AS n FROM complaints "
            "WHERE company LIKE '%HEATH%' OR company LIKE '%Lexington Law%' "
            "OR company LIKE '%PROGREXION%' GROUP BY month "
            "HAVING n > 20 ORDER BY month"
        )
    ]
    lex_issues = [
        dict(r) for r in store.query(
            "SELECT product, issue, COUNT(*) AS n FROM complaints "
            "WHERE (company LIKE '%HEATH%' OR company LIKE '%Lexington Law%' "
            "OR company LIKE '%PROGREXION%') AND month LIKE '2024-%' "
            "GROUP BY product, issue ORDER BY n DESC LIMIT 6"
        )
    ]
    lex_sample = [
        dict(r) for r in store.query(
            "SELECT date_received, state, issue, substr(narrative,1,320) AS txt "
            "FROM complaints WHERE (company LIKE '%HEATH%' "
            "OR company LIKE '%Lexington Law%') AND has_narrative=1 "
            "AND month LIKE '2024-1%' LIMIT 3"
        )
    ]
    out["lexington"] = {"monthly": lex, "issues_2024": lex_issues,
                        "samples": lex_sample}

    # ---- F) end of extract ------------------------------------------------
    out["august_2026_daily"] = [
        dict(r) for r in store.query(
            "SELECT date_received, COUNT(*) AS n, SUM(has_narrative) AS narr "
            "FROM complaints WHERE date_received >= '2026-07-25' "
            "GROUP BY date_received ORDER BY date_received"
        )
    ]

    path = config.OUT_DIR / "followups.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")

    g = out["geo_split_stats"]
    print(f"\ngeography split: templated rate varies {g['templated_max_min_ratio']}x "
          f"across states, organic varies {g['organic_max_min_ratio']}x")
    print(f"  CV templated {g['templated_cv']}, organic {g['organic_cv']}")
    d = out["day_of_week"]
    print(f"weekend share: templated {d['templated_weekend_pct']}%, "
          f"organic {d['organic_weekend_pct']}%")
    r = out["relief"]["credit_reporting_2024"]
    for k, v in r.items():
        print(f"relief {k}: {v['relief_pct']}% of {v['n']:,}")


if __name__ == "__main__":
    main()
