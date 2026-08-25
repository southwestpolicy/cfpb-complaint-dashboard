"""Collect the report's headline statistics into out/findings.json.

Exists so every number in the written report is reproducible from the store
rather than copied out of a terminal. Run after a full fetch:

    python collect_findings.py

The templating measure here is EXACT duplication (byte-identical after
normalisation). That is deliberate: near-duplicate clusters are single-linkage
components and chain together texts that are not similar to each other, so they
cannot support a defensible "N copies" claim. See cfpb_inspect/analysis/dedupe.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfpb_inspect import config
from cfpb_inspect.analysis.dedupe import normalize
from cfpb_inspect.analysis.geo import load_population, NON_STATES
from cfpb_inspect.store import Store

MIN_TOKENS = 25
MIN_GROUP = 50  # a text used this many times is treated as a template


def main() -> None:
    store = Store()
    out: dict[str, object] = {}

    out["coverage"] = {k: v for k, v in store.coverage().items()}
    out["segments"] = [dict(r) for r in store.segment_counts()]
    out["raw_product_windows"] = [dict(r) for r in store.raw_product_windows()]

    print("scanning narratives (single pass, computing normalised hashes)...")
    records: list[tuple[bytes, str, str, str]] = []  # hash, segment, month, state
    counts: Counter[bytes] = Counter()
    cur = store.conn.execute(
        "SELECT segment, month, state, narrative FROM complaints "
        "WHERE has_narrative = 1 AND narrative IS NOT NULL AND narrative <> ''"
    )
    scanned = 0
    while True:
        rows = cur.fetchmany(50_000)
        if not rows:
            break
        for seg, month, state, narr in rows:
            norm, _ratio = normalize(narr)
            if len(norm.split()) < MIN_TOKENS:
                continue
            h = hashlib.sha1(norm.encode()).digest()[:8]
            records.append((h, seg, month, state or ""))
            counts[h] += 1
            scanned += 1
        if scanned and scanned % 500_000 < 50_000:
            print(f"  {scanned:,} scored")
    print(f"  {scanned:,} narratives scored, {len(counts):,} distinct texts")

    templates = {h for h, c in counts.items() if c >= MIN_GROUP}
    out["templating"] = {
        "narratives_scored": scanned,
        "distinct_texts": len(counts),
        "min_group_size": MIN_GROUP,
        "template_texts": len(templates),
        "complaints_in_templates": sum(counts[h] for h in templates),
        "exact_dup_any": sum(c for c in counts.values() if c >= 2),
    }

    # --- templated share by segment x month --------------------------------
    by_seg_month: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    by_seg_state: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    for h, seg, month, state in records:
        m = by_seg_month[seg][month]
        m[0] += 1
        s = by_seg_state[seg][state]
        s[0] += 1
        if h in templates:
            m[1] += 1
            s[1] += 1

    out["templated_share_by_month"] = {
        seg: {
            mo: {"narratives": v[0], "templated": v[1],
                 "pct": round(100.0 * v[1] / v[0], 2)}
            for mo, v in sorted(months.items())
        }
        for seg, months in by_seg_month.items()
    }

    # --- does templating explain the geographic anomaly? -------------------
    pop = load_population()
    latest_pop_year = int(pop["year"].max())
    pop_latest = (
        pop[pop["year"] == latest_pop_year].set_index("state")["population"].to_dict()
    )

    # Total complaints (not just narratives) per state, 2025 -- a full year with
    # good narrative coverage, unlike 2026.
    totals_2025 = {
        r["state"]: r["n"]
        for r in store.query(
            "SELECT state, COUNT(*) AS n FROM complaints "
            "WHERE segment='credit_reporting' AND month LIKE '2025-%' "
            "GROUP BY state"
        )
    }
    cr_states = by_seg_state.get("credit_reporting", {})
    geo_rows = []
    for state, total in totals_2025.items():
        if not state or state in NON_STATES or state not in pop_latest:
            continue
        narr, tpl = cr_states.get(state, [0, 0])
        if narr < 200:
            continue
        geo_rows.append(
            {
                "state": state,
                "complaints_2025": total,
                "rate_per_100k_2025": round(total / pop_latest[state] * 100_000, 1),
                "narratives_scored": narr,
                "templated_pct": round(100.0 * tpl / narr, 1),
            }
        )
    geo_rows.sort(key=lambda r: -r["rate_per_100k_2025"])
    out["state_rate_vs_templating"] = geo_rows

    # Correlation between per-capita filing rate and templated share.
    try:
        import numpy as np

        x = np.array([r["rate_per_100k_2025"] for r in geo_rows], dtype=float)
        y = np.array([r["templated_pct"] for r in geo_rows], dtype=float)
        if len(x) > 2:
            out["rate_templating_correlation"] = {
                "pearson_r": round(float(np.corrcoef(x, y)[0, 1]), 3),
                "n_states": int(len(x)),
            }
    except Exception as exc:  # pragma: no cover
        out["rate_templating_correlation"] = {"error": str(exc)}

    # --- issue composition shift ------------------------------------------
    out["issue_composition"] = {
        yr: [
            dict(r)
            for r in store.query(
                "SELECT issue, COUNT(*) AS n FROM complaints "
                "WHERE segment='credit_reporting' AND month LIKE ? "
                "GROUP BY issue ORDER BY n DESC LIMIT 6",
                (f"{yr}-%",),
            )
        ]
        for yr in ("2019", "2022", "2025")
    }

    # --- channel mix by year ----------------------------------------------
    out["channel_by_year"] = [
        dict(r)
        for r in store.query(
            "SELECT substr(date_received,1,4) AS year, submitted_via, "
            "COUNT(*) AS n FROM complaints GROUP BY year, submitted_via "
            "ORDER BY year"
        )
    ]

    path = config.OUT_DIR / "findings.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")

    t = out["templating"]
    print(f"\ntemplating: {t['complaints_in_templates']:,} of "
          f"{t['narratives_scored']:,} narratives "
          f"({100 * t['complaints_in_templates'] / t['narratives_scored']:.1f}%) "
          f"in a >={MIN_GROUP}-copy identical group")
    corr = out.get("rate_templating_correlation", {})
    if "pearson_r" in corr:
        print(f"state filing rate vs templated share: r = {corr['pearson_r']} "
              f"across {corr['n_states']} states")


if __name__ == "__main__":
    main()
