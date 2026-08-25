"""Command-line entry point for the CFPB complaint inspection tool.

    python cli.py probe                     # check API, dump taxonomy, size the pull
    python cli.py fetch --dry-run           # plan the windows without downloading
    python cli.py fetch                     # pull selected segments into SQLite
    python cli.py status                    # what is in the store + rename diagnostics
    python cli.py its                       # interrupted time series + changepoints
    python cli.py bursts                    # volume bursts and channel shift
    python cli.py dedupe                    # near-duplicate narrative clusters
    python cli.py geo                       # per-capita geographic anomalies
    python cli.py report                    # write everything to out/
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfpb_inspect import config, taxonomy
from cfpb_inspect.api import CFPBClient
from cfpb_inspect.fetch import fetch_segments
from cfpb_inspect.store import Store

log = logging.getLogger("cfpb")


def _segments(args: argparse.Namespace) -> list[str]:
    raw = getattr(args, "segments", None)
    if not raw:
        return list(taxonomy.SELECTED_SEGMENTS)
    segs = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [s for s in segs if s not in taxonomy.SEGMENT_MAP]
    if unknown:
        raise SystemExit(
            f"unknown segment(s): {', '.join(unknown)}\n"
            f"known: {', '.join(sorted(taxonomy.SEGMENT_MAP))}"
        )
    return segs


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------

def cmd_probe(args: argparse.Namespace) -> None:
    client = CFPBClient()
    total = client.count()
    print(f"API reachable. Total complaints in public index: {total:,}\n")

    aggs = client.aggregate(size=0)
    products = aggs.get("product", [])
    print("Raw product labels and canonical segment mapping:")
    print(f"{'count':>12}  {'segment':<24} raw label")
    unmapped = []
    for b in products:
        seg = taxonomy.canonical_segment(b["key"])
        if seg.startswith("unmapped:"):
            unmapped.append(b["key"])
        print(f"{b['doc_count']:>12,}  {seg:<24} {b['key']}")

    if unmapped:
        print("\n!! UNMAPPED product labels -- update cfpb_inspect/taxonomy.py:")
        for label in unmapped:
            print(f"   - {label}")

    segs = _segments(args)
    raw = taxonomy.raw_products_for(segs)
    in_scope = sum(
        b["doc_count"] for b in products if b["key"] in set(raw)
    )
    print(f"\nSelected segments: {', '.join(segs)}")
    print(f"Complaints in scope: {in_scope:,} ({in_scope / total * 100:.1f}% of index)")

    with_narr = client.count(product=raw, has_narrative="true")
    print(f"  with narrative:    {with_narr:,}")
    print(f"  without narrative: {in_scope - with_narr:,}")
    est_gb = (with_narr * 2000 + (in_scope - with_narr) * 250) / 1e9
    print(f"Rough download estimate: {est_gb:.1f} GB")
    print(f"\nRequests used: {client.request_count}")


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> None:
    store = Store()
    totals = fetch_segments(
        segments=_segments(args),
        start=args.start,
        end=args.end,
        narrative_mode=args.narrative_mode,
        store=store,
        refetch_recent_days=args.refetch_recent_days,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )
    print(json.dumps(totals, indent=2))
    if not args.dry_run:
        print(json.dumps(store.coverage(), indent=2, default=str))


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    store = Store()
    segs = _segments(args)
    cov = store.coverage()
    print(f"Store: {store.path}")
    print(json.dumps(cov, indent=2, default=str))

    print("\nBy canonical segment:")
    for r in store.segment_counts():
        print(
            f"  {r['segment']:<26} {r['n']:>10,}  "
            f"{r['first_date']} .. {r['last_date']}"
        )

    print(f"\nNarrative coverage by month for {', '.join(segs)} "
          f"(last 18 shown).")
    print("  Text-based astroturfing detection can only see published")
    print("  narratives. Where coverage is near zero, a null result means")
    print("  'no text to compare', not 'no templating'.")
    cov_rows = store.narrative_coverage(segments=segs, since="2015-01")
    for r in cov_rows[-18:]:
        flag = "  <-- effectively invisible to text analysis" if (
            r["narrative_pct"] is not None and r["narrative_pct"] < 5.0
        ) else ""
        print(
            f"  {r['month']}  {r['complaints']:>9,} complaints  "
            f"{r['narrative_pct'] or 0:>5.1f}% with narrative{flag}"
        )

    print("\nRaw product label active windows (rename diagnostic):")
    print("  A label that stops on roughly the date another starts is a RENAME,")
    print("  not a change in complaint behaviour. Series are grouped on segment")
    print("  precisely so these do not appear as structural breaks.")
    for r in store.raw_product_windows():
        print(
            f"  {r['n']:>10,}  {r['first_seen']} .. {r['last_seen']}  "
            f"[{r['segment']}]  {r['product']}"
        )


# --------------------------------------------------------------------------
# its
# --------------------------------------------------------------------------

def cmd_its(args: argparse.Namespace) -> None:
    import pandas as pd
    from cfpb_inspect.analysis import its as its_mod
    from cfpb_inspect.analysis.series import monthly_counts, to_series

    store = Store()
    segs = _segments(args)
    events = dict(config.LLM_EVENTS)
    if args.intervention:
        events = {"custom": args.intervention}

    rows = []
    for seg in segs + ["ALL_SELECTED"]:
        use = segs if seg == "ALL_SELECTED" else [seg]
        df = monthly_counts(store, use, start=args.start, end=args.end)
        if df.empty:
            continue
        s = to_series(df)
        if len(s) < 24:
            log.warning("%s: only %d months, skipping", seg, len(s))
            continue

        print(f"\n{'=' * 72}\n{seg}  ({len(s)} months, "
              f"{s.index.min().date()} .. {s.index.max().date()})\n{'=' * 72}")

        breaks = its_mod.detect_changepoints(s)
        print("\nChangepoints detected WITHOUT reference to any LLM date:")
        if not breaks:
            print("  none")
        for b in breaks:
            name, gap = its_mod.nearest_event(b["break_date"], config.LLM_EVENTS)
            print(
                f"  {b['break_date']}  {str(b['mean_before']):>12} -> "
                f"{str(b['mean_after']):<12} ({b['pct_change']}%)  "
                f"nearest LLM milestone: {name} ({gap}d away)"
            )
            for cgap, cdate, cdesc, _url in its_mod.competing_explanations(
                b["break_date"], seg
            ):
                flag = "  <-- CLOSER THAN THE LLM DATE" if cgap < gap else ""
                print(f"        competing: {cdate} ({cgap}d) {cdesc}{flag}")

        for name, when in events.items():
            try:
                pl = its_mod.placebo_test(s, when, model=args.model)
            except Exception as exc:
                log.warning("%s @ %s failed: %s", seg, when, exc)
                continue
            real = pl["real"]
            print(f"\n  intervention: {name} ({when})  model={args.model}")
            print(
                f"    level change {real['level_change_pct']:+.1f}% "
                f"(p={real['level_p']:.4g}), slope change "
                f"{real['slope_change']:+.4f} (p={real['slope_p']:.4g})"
            )
            print(
                f"    placebo: {pl['placebo_n']} dates, median |effect| "
                f"{pl['placebo_median_abs_effect']}%, 95th pct "
                f"{pl['placebo_p95_abs_effect']}%"
            )
            print(f"    real effect is at the {pl['real_effect_percentile']}th "
                  f"percentile of placebo effects")
            print(f"    VERDICT: {pl['verdict']}")
            rows.append({"segment": seg, "event": name, **real,
                         "placebo_percentile": pl["real_effect_percentile"],
                         "verdict": pl["verdict"]})

    if rows:
        out = config.OUT_DIR / "its_results.csv"
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"\nwrote {out}")


# --------------------------------------------------------------------------
# bursts
# --------------------------------------------------------------------------

def cmd_bursts(args: argparse.Namespace) -> None:
    from cfpb_inspect.analysis import bursts as b

    store = Store()
    segs = _segments(args)

    print("Segment-level bursts (trailing-baseline robust z >= 3):")
    sb = b.segment_bursts(store, segs)
    print(sb.head(25).to_string(index=False) if not sb.empty else "  none")

    label = "raw names" if args.raw_companies else "normalized to corporate groups"
    print(f"\nCompany-level bursts ({label}, robust z >= 5, "
          f">= {args.min_monthly} complaints/month):")
    cb = b.company_bursts(
        store, segs, min_monthly=args.min_monthly,
        normalize=not args.raw_companies,
    )
    print(cb.head(30).to_string(index=False) if not cb.empty else "  none")

    print("\nHigh-volume first appearances (rename/acquisition candidates):")
    ne = b.new_entrant_companies(store, segs)
    print(ne.head(20).to_string(index=False) if not ne.empty else "  none")

    for name, when in config.LLM_EVENTS.items():
        cs = b.channel_shift_around(store, when, segs)
        if cs.empty:
            continue
        print(f"\nChannel mix shift around {name} ({when}):")
        print(cs.to_string(index=False))

    if not cb.empty:
        out = config.OUT_DIR / "company_bursts.csv"
        cb.to_csv(out, index=False)
        print(f"\nwrote {out}")


# --------------------------------------------------------------------------
# dedupe
# --------------------------------------------------------------------------

def cmd_dedupe(args: argparse.Namespace) -> None:
    import pandas as pd
    from cfpb_inspect.analysis import dedupe as dd

    store = Store()
    segs = _segments(args)

    print("Exact duplicate narrative groups (after normalisation):")
    ex = dd.exact_duplicate_groups(
        store, segs, start=args.start, end=args.end, min_tokens=args.min_tokens
    )
    if ex:
        df = pd.DataFrame(ex)
        print(df.head(25).to_string(index=False))
        print(f"  {len(ex)} groups, {sum(g['size'] for g in ex):,} complaints")
        df.to_csv(config.OUT_DIR / "exact_duplicate_groups.csv", index=False)
    else:
        print("  none")

    print(f"\nNear-duplicate clusters (Jaccard >= {args.threshold}):")
    clusters = dd.near_duplicate_clusters(
        store, segs, start=args.start, end=args.end,
        threshold=args.threshold, min_tokens=args.min_tokens, limit=args.limit,
    )
    if clusters:
        df = pd.DataFrame([c.as_row() for c in clusters])
        print(df.head(30).to_string(index=False))

        print("\ncluster size distribution:")
        bounds = [(2, 2), (3, 9), (10, 49), (50, 499), (500, 4999), (5000, 10**9)]
        for lo, hi in bounds:
            sel = df[(df["chained_size"] >= lo) & (df["chained_size"] <= hi)]
            if sel.empty:
                continue
            label = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
            print(f"  {label:>10}  {len(sel):>8,} clusters  "
                  f"{sel['chained_size'].sum():>10,} complaints")

        # Exporting all clusters produced a 104 MB CSV on the shared drive,
        # which Google Drive re-uploads in full on every write. Small clusters
        # (2-9 copies) are mostly noise for this purpose, so only clusters at
        # or above the export floor are written out.
        floor = args.export_min_size
        big = df[df["chained_size"] >= floor]
        out = config.OUT_DIR / "near_duplicate_clusters.csv"
        big.to_csv(out, index=False)
        print(f"\n{len(clusters):,} clusters covering "
              f"{sum(c.size for c in clusters):,} complaints")
        print(f"exported {len(big):,} clusters with >= {floor} copies -> {out}")
        coh = big[big["cohesion_mean"].notna()]
        if not coh.empty:
            tight = coh[coh["cohesion_pct_above_threshold"] >= 80]
            print(
                f"\nOf {len(coh):,} clusters with a cohesion measurement, "
                f"{len(tight):,} are tight (>=80% of sampled members at or "
                f"above the similarity threshold), covering "
                f"{tight['chained_size'].sum():,} complaints."
            )
        print(
            "\nTWO REMINDERS:\n"
            "  1. chained_size is a SINGLE-LINKAGE component size, not a copy "
            "count. A large, low-cohesion cluster is a family of related "
            "boilerplate, not one document repeated N times. For a defensible "
            "copy count use the exact-duplicate groups above.\n"
            "  2. A template signature is not proof of fabrication. "
            "Distinguishing a credit-repair mill filing for real clients from "
            "an invented campaign needs the company/state/date spread, not the "
            "text alone."
        )
    else:
        print("  none")


# --------------------------------------------------------------------------
# geo
# --------------------------------------------------------------------------

def cmd_geo(args: argparse.Namespace) -> None:
    from cfpb_inspect.analysis import geo

    store = Store()
    segs = _segments(args)

    rates = geo.state_year_rates(store, segs, start=args.start, end=args.end)
    if rates.empty:
        print("no data in store")
        return
    excluded = rates.attrs.get("excluded_non_state_complaints", 0)
    if excluded:
        print(f"(excluded {excluded:,} complaints from territories/military "
              f"ZIPs with no Census state denominator)\n")

    anom = geo.rate_anomalies(rates)
    latest = anom["year"].max()
    print(f"Highest per-capita rates, {latest}:")
    cols = ["state", "year", "complaints", "rate_per_100k",
            "rate_ratio_to_median", "robust_z"]
    print(anom[anom["year"] == latest][cols].head(15).to_string(index=False))

    for name, when in config.LLM_EVENTS.items():
        ch = geo.state_rate_changes(store, when, segs)
        if ch.empty:
            continue
        print(f"\nPer-capita rate change around {name} ({when}); "
              f"national {ch.attrs['national_pct_change']}%:")
        print(ch.head(12).to_string(index=False))

    conc = geo.zip_concentration(store, segs, start=args.start, end=args.end)
    if not conc.empty:
        print("\nMost geographically concentrated states (ZIP3 Herfindahl):")
        print(conc.head(12).to_string(index=False))

    rates.to_csv(config.OUT_DIR / "state_year_rates.csv", index=False)
    print(f"\nwrote {config.OUT_DIR / 'state_year_rates.csv'}")


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def cmd_report(args: argparse.Namespace) -> None:
    from cfpb_inspect.report import build_report

    path = build_report(_segments(args), start=args.start, end=args.end)
    print(f"wrote {path}")


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cli.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-v", "--verbose", action="store_true")
    # Comma-separated rather than nargs="+", which would otherwise swallow the
    # subcommand name when --segments is given before it.
    p.add_argument(
        "--segments", metavar="SEG,SEG",
        help="comma-separated canonical segments (default: "
             f"{','.join(taxonomy.SELECTED_SEGMENTS)})",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("probe", help="check API and size the pull")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("fetch", help="download complaints into the local store")
    sp.add_argument("--start", default=config.DB_START)
    sp.add_argument("--end", default=None)
    sp.add_argument(
        "--narrative-mode", default="split",
        choices=["split", "with", "without", "any"],
    )
    sp.add_argument("--refetch-recent-days", type=int, default=60)
    sp.add_argument("--no-resume", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("status", help="store coverage and rename diagnostics")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("its", help="interrupted time series + changepoints")
    sp.add_argument("--start", default=None)
    sp.add_argument("--end", default=None)
    sp.add_argument("--intervention", default=None,
                    help="test one custom date instead of the LLM milestones")
    sp.add_argument("--model", default="nbinom",
                    choices=["nbinom", "poisson", "ols_log"])
    sp.set_defaults(func=cmd_its)

    sp = sub.add_parser("bursts", help="volume bursts and channel shift")
    sp.add_argument("--min-monthly", type=int, default=50)
    sp.add_argument(
        "--raw-companies", action="store_true",
        help="do not fold company name variants into corporate groups",
    )
    sp.set_defaults(func=cmd_bursts)

    sp = sub.add_parser("dedupe", help="duplicate/near-duplicate narratives")
    sp.add_argument("--start", default=None)
    sp.add_argument("--end", default=None)
    sp.add_argument("--threshold", type=float, default=0.8)
    sp.add_argument("--min-tokens", type=int, default=25)
    sp.add_argument("--limit", type=int, default=None,
                    help="cap narratives indexed (for a quick pass)")
    sp.add_argument("--export-min-size", type=int, default=10,
                    help="only export clusters with at least this many copies "
                         "(default 10; exporting all produced a 104 MB CSV)")
    sp.set_defaults(func=cmd_dedupe)

    sp = sub.add_parser("geo", help="per-capita geographic anomalies")
    sp.add_argument("--start", default=None)
    sp.add_argument("--end", default=None)
    sp.set_defaults(func=cmd_geo)

    sp = sub.add_parser("report", help="write a full markdown report to out/")
    sp.add_argument("--start", default=None)
    sp.add_argument("--end", default=None)
    sp.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
