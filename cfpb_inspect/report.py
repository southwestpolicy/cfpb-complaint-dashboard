"""Assemble a markdown report with figures from whatever is in the store.

The report leads with data provenance and the known confounds, before any
result. That ordering is deliberate: the headline number this project produces
(a complaint-volume jump coinciding with LLM adoption) has at least four
mundane explanations that must be ruled out before it means anything, and a
report that buries them under a chart invites the reader to skip them.
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import config, taxonomy
from .analysis import bursts as bursts_mod
from .analysis import geo as geo_mod
from .analysis import its as its_mod
from .analysis.series import monthly_counts, to_series
from .store import Store

log = logging.getLogger(__name__)


def _fig_segment_series(store: Store, segments: list[str]) -> Path | None:
    df = monthly_counts(store, segments, by="segment")
    if df.empty:
        return None
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for seg, grp in df.groupby("segment"):
        g = grp.sort_values("month_start")
        ax.plot(g["month_start"], g["complaints"], label=seg, linewidth=1.4)
    for name, when in config.LLM_EVENTS.items():
        ax.axvline(pd.Timestamp(when), color="0.4", linestyle="--", linewidth=0.9)
        ax.text(
            pd.Timestamp(when), ax.get_ylim()[1] * 0.97, f" {name}",
            rotation=90, va="top", fontsize=7, color="0.3",
        )
    ax.set_yscale("log")
    ax.set_ylabel("complaints per month (log scale)")
    ax.set_xlabel("month received")
    ax.set_title("Monthly complaint volume by canonical segment")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.25)
    out = config.OUT_DIR / "segment_series.png"
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def _fig_channel_mix(store: Store, segments: list[str]) -> Path | None:
    mix = bursts_mod.channel_mix(store, segments)
    if mix.empty:
        return None
    share_cols = [c for c in mix.columns if c.endswith("_share")]
    mix["period_ts"] = pd.to_datetime(mix["period"] + "-01")
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for c in share_cols:
        if mix[c].max() < 0.005:  # keep the legend readable
            continue
        ax.plot(mix["period_ts"], mix[c], label=c[: -len("_share")], linewidth=1.3)
    for when in config.LLM_EVENTS.values():
        ax.axvline(pd.Timestamp(when), color="0.4", linestyle="--", linewidth=0.9)
    ax.set_yscale("log")
    ax.set_ylabel("share of monthly complaints (log)")
    ax.set_title("Submission channel mix over time")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    out = config.OUT_DIR / "channel_mix.png"
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def build_report(
    segments: list[str], start: str | None = None, end: str | None = None
) -> Path:
    store = Store()
    cov = store.coverage()
    lines: list[str] = []
    w = lines.append

    w("# CFPB Complaint Database Inspection")
    w("")
    w("Southwest Public Policy Institute")
    w("")
    w(f"Generated from a local extract of {cov['n']:,} complaints "
      f"({cov['first_date']} to {cov['last_date']}), "
      f"{cov['narratives']:,} with published narrative text.")
    w("")

    # ---- provenance and confounds first -------------------------------
    w("## Read this before the results")
    w("")
    w("### 1. Product labels have been renamed, twice")
    w("")
    w("CFPB has renamed product categories over the life of the database. The "
      "same segment appears under different `product` values in different eras. "
      "Every series below is grouped on a **canonical segment** from the "
      "crosswalk in `cfpb_inspect/taxonomy.py`, never on the raw label. "
      "Grouping on raw labels makes each series collapse to zero at its rename "
      "date and a new one appear from nothing -- a structural break located at "
      "an administrative event, which any changepoint detector will report as "
      "real. One of the credit-reporting renames falls near the LLM-adoption "
      "window, so this is not a hypothetical concern for this analysis.")
    w("")
    w("Observed active window of each raw label:")
    w("")
    w("| complaints | first seen | last seen | segment | raw label |")
    w("|---:|---|---|---|---|")
    for r in store.raw_product_windows():
        w(f"| {r['n']:,} | {r['first_seen']} | {r['last_seen']} | "
          f"`{r['segment']}` | {r['product']} |")
    w("")

    w("### 2. Complaint volume grew steeply before LLMs existed")
    w("")
    w("A segmented regression fitted to a steeply growing series reports a "
      "large, significant 'level shift' at nearly any date, because the break "
      "term absorbs ordinary curvature. Every intervention estimate below is "
      "therefore accompanied by a **placebo distribution**: the same model "
      "refitted at many dates where nothing relevant happened. An effect that "
      "is not extreme against that distribution is not evidence of an effect, "
      "whatever its p-value.")
    w("")

    w("### 3. Narratives are PII-redacted, which fakes similarity")
    w("")
    w("Published narratives have names, dates and addresses replaced by runs "
      "of `X`. Two unrelated complaints can therefore share most of their "
      "tokens purely through redaction. The near-duplicate detector collapses "
      "redaction runs to a dropped sentinel and reports a redaction ratio per "
      "cluster; clusters that are similar only because they are mostly "
      "redacted should be discarded.")
    w("")

    w("### 4. A template cluster is not proof of astroturfing")
    w("")
    w("Consumers copy template letters from credit-repair firms, advocacy "
      "sites and forums. A credit-repair mill filing on behalf of many real "
      "clients with real disputes produces the same textual signature as a "
      "fabricated campaign, and neither is separable from LLM-assisted "
      "drafting on text alone. The company, state and date spread reported per "
      "cluster is what carries the distinction.")
    w("")

    # ---- coverage ------------------------------------------------------
    w("## Extract coverage")
    w("")
    w("| segment | complaints | first | last |")
    w("|---|---:|---|---|")
    for r in store.segment_counts():
        w(f"| `{r['segment']}` | {r['n']:,} | {r['first_date']} | {r['last_date']} |")
    w("")

    fig = _fig_segment_series(store, segments)
    if fig:
        w(f"![monthly volume by segment]({fig.name})")
        w("")

    # ---- ITS ------------------------------------------------------------
    w("## Interrupted time series and changepoints")
    w("")
    for seg in list(segments) + ["ALL_SELECTED"]:
        use = segments if seg == "ALL_SELECTED" else [seg]
        df = monthly_counts(store, use, start=start, end=end)
        if df.empty:
            continue
        s = to_series(df)
        if len(s) < 24:
            continue
        w(f"### `{seg}`")
        w("")
        w(f"{len(s)} months, {s.index.min().date()} to {s.index.max().date()}")
        w("")

        breaks = its_mod.detect_changepoints(s)
        w("Changepoints found **without** reference to any LLM date:")
        w("")
        if breaks:
            w("| break | mean before | mean after | change | nearest LLM milestone "
              "| competing explanation |")
            w("|---|---:|---:|---:|---|---|")
            for b in breaks:
                name, gap = its_mod.nearest_event(b["break_date"], config.LLM_EVENTS)
                competing = its_mod.competing_explanations(b["break_date"], seg)
                if competing:
                    cgap, cdate, cdesc, curl = competing[0]
                    closer = " **(closer than the LLM date)**" if cgap < gap else ""
                    desc = f"[{cdesc}]({curl})" if curl else cdesc
                    comp = f"{cdate} ({cgap}d) {desc}{closer}"
                else:
                    comp = "none registered"
                w(f"| {b['break_date']} | {b['mean_before']} | {b['mean_after']} | "
                  f"{b['pct_change']}% | {name} ({gap}d) | {comp} |")
        else:
            w("None detected.")
        w("")
        if any(its_mod.competing_explanations(b["break_date"], seg) for b in breaks):
            w("> Competing explanations come from the analyst-maintained registry "
              "in `cfpb_inspect/config.py`. Verify each date against a primary "
              "source before publishing, and treat an empty entry as "
              "'not yet researched' rather than 'no confound exists'.")
            w("")

        w("| intervention | level change | p | placebo pct | verdict |")
        w("|---|---:|---:|---:|---|")
        for name, when in config.LLM_EVENTS.items():
            try:
                pl = its_mod.placebo_test(s, when)
            except Exception as exc:
                log.warning("%s @ %s: %s", seg, when, exc)
                continue
            real = pl["real"]
            w(f"| {name} ({when}) | {real['level_change_pct']:+.1f}% | "
              f"{real['level_p']:.3g} | {pl['real_effect_percentile']} | "
              f"{pl['verdict']} |")
        w("")

    # ---- channel -------------------------------------------------------
    w("## Submission channel")
    w("")
    fig = _fig_channel_mix(store, segments)
    if fig:
        w(f"![channel mix]({fig.name})")
        w("")
    for name, when in config.LLM_EVENTS.items():
        cs = bursts_mod.channel_shift_around(store, when, segments)
        if cs.empty:
            continue
        w(f"Channel mix around **{name}** ({when}):")
        w("")
        w(cs.to_markdown(index=False))
        w("")

    # ---- bursts --------------------------------------------------------
    w("## Volume bursts")
    w("")
    cb = bursts_mod.company_bursts(store, segments)
    if not cb.empty:
        w("Company-months exceeding their own trailing baseline "
          "(robust z >= 5), top 25. Names are folded to corporate groups, and "
          "`corporate_event` names any registered servicer transfer or "
          "enforcement action near the burst. **A burst with a corporate event "
          "beside it is explained and is not an astroturfing signal.**")
        w("")
        w(cb.head(25).to_markdown(index=False))
        explained = int((cb["corporate_event"] != "").sum())
        w("")
        w(f"{explained} of {len(cb)} detected bursts have a registered "
          f"corporate cause. An unexplained burst is not thereby suspicious -- "
          f"the registry is incomplete, and segment-level policy shocks in "
          f"`CONFOUNDING_EVENTS` account for others.")
    else:
        w("No company-level bursts above threshold.")
    w("")
    ne = bursts_mod.new_entrant_companies(store, segments)
    if not ne.empty:
        w("High-volume first appearances. These are usually corporate renames "
          "or acquisitions rather than anything suspicious, but they create "
          "artificial jumps in company-level series:")
        w("")
        w(ne.head(15).to_markdown(index=False))
        w("")

    # ---- geo -----------------------------------------------------------
    w("## Per-capita geography")
    w("")
    rates = geo_mod.state_year_rates(store, segments, start=start, end=end)
    if not rates.empty:
        excluded = rates.attrs.get("excluded_non_state_complaints", 0)
        if excluded:
            w(f"Excluded {excluded:,} complaints from territories and military "
              f"ZIP codes, which have no Census state population denominator.")
            w("")
        anom = geo_mod.rate_anomalies(rates)
        latest = anom["year"].max()
        cols = ["state", "year", "complaints", "rate_per_100k",
                "rate_ratio_to_median", "robust_z"]
        w(f"Highest per-capita rates in {latest}:")
        w("")
        w(anom[anom["year"] == latest][cols].head(15).round(2)
          .to_markdown(index=False))
        w("")
        conc = geo_mod.zip_concentration(store, segments)
        if not conc.empty:
            w("Most geographically concentrated states (ZIP3 Herfindahl). "
              "CFPB truncates ZIP codes to three digits, so this is regional, "
              "not neighbourhood-level:")
            w("")
            w(conc.head(12).to_markdown(index=False))
            w("")

    w("## Method notes")
    w("")
    w(f"- Canonical segment crosswalk: {len(taxonomy.SEGMENT_MAP)} segments over "
      f"{sum(len(v) for v in taxonomy.SEGMENT_MAP.values())} raw labels.")
    for seg, note in taxonomy.SEGMENT_NOTES.items():
        w(f"  - `{seg}`: {note}")
    w("- Count model: negative binomial (complaint counts are overdispersed; "
      "Poisson and OLS understate standard errors here).")
    w("- Changepoints: binary segmentation on log counts.")
    w("- Bursts: robust z against a trailing 12-month median/MAD baseline, not "
      "a whole-series baseline, which would score all recent months extreme.")
    w("- Population: Census Bureau state estimates by year "
      "(`cfpb_inspect/reference/build_population.py`).")
    w("")

    out = config.OUT_DIR / "report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
