"""Volume burst detection and submission-channel shift analysis.

Bursts are scored against a TRAILING baseline (median and MAD of the preceding
months) rather than the whole series. The series grows by orders of magnitude
over its life, so a whole-series baseline would score every recent month as an
extreme outlier and every early month as normal -- an artefact of growth, not a
detection of anything.

CHANNEL SHIFT MATTERS FOR PROVENANCE
``submitted_via`` is the closest thing the public data has to a provenance
field. Web submission dominates (16.6M of 17.2M complaints), but the ratio of
web to phone and postal filings is informative: a genuine grassroots increase in
consumer grievance tends to show up across channels, whereas an automated or
brokered filing operation can only realistically scale the web channel. A rise
concentrated entirely in web submissions is consistent with both bulk automated
filing AND with ordinary continued migration to online channels, so this signal
constrains interpretation rather than settling it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..store import Store
from .series import monthly_counts


def _robust_z_trailing(
    values: pd.Series, window: int = 12, min_periods: int = 6
) -> pd.Series:
    """Robust z-score of each point against the preceding `window` points."""
    med = values.shift(1).rolling(window, min_periods=min_periods).median()
    mad = (
        (values - med).abs().shift(1).rolling(window, min_periods=min_periods).median()
    )
    scale = mad * 1.4826
    # Where MAD is zero (a flat baseline), fall back to trailing std so a jump
    # off a constant baseline is not scored as infinitely extreme.
    std = values.shift(1).rolling(window, min_periods=min_periods).std()
    scale = scale.where(scale > 0, std)
    return (values - med) / scale.replace(0, np.nan)


def company_bursts(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    min_monthly: int = 50,
    z_threshold: float = 5.0,
    window: int = 12,
    normalize: bool = True,
) -> pd.DataFrame:
    """Company-months whose volume jumps far above the company's own baseline.

    ``min_monthly`` keeps tiny companies out: going from 1 complaint to 8 is a
    large relative jump and almost never meaningful.

    With ``normalize`` (the default) names are folded to corporate groups first,
    so one firm's variant spellings do not each carry their own artificially low
    baseline. Every burst is annotated with any known corporate event nearby --
    a servicer transfer produces a far larger burst than any plausible
    astroturfing campaign, and must be excluded before the rest is interpreted.
    """
    from ..companies import company_group, competing_corporate_event

    df = monthly_counts(store, segments, start, end, by="company")
    if df.empty:
        return df

    if normalize:
        df = df.copy()
        df["entity"] = df["company"].map(company_group)
        df = (
            df.groupby(["entity", "month", "month_start"], as_index=False)
            ["complaints"].sum()
        )
    else:
        df = df.rename(columns={"company": "entity"})

    out = []
    for entity, grp in df.groupby("entity"):
        if not entity or grp["complaints"].max() < min_monthly:
            continue
        s = (
            grp.sort_values("month_start")
            .set_index("month_start")["complaints"]
            .asfreq("MS", fill_value=0)
        )
        z = _robust_z_trailing(s, window=window)
        baseline = s.shift(1).rolling(window, min_periods=6).median()
        g2 = pd.DataFrame(
            {
                "entity": entity,
                "month": s.index.strftime("%Y-%m"),
                "complaints": s.values,
                "trailing_median": baseline.values,
                "robust_z": z.values,
            }
        )
        out.append(
            g2[(g2["robust_z"] >= z_threshold) & (g2["complaints"] >= min_monthly)]
        )

    if not out:
        return pd.DataFrame()
    res = pd.concat(out, ignore_index=True)
    res["multiple_of_baseline"] = (
        res["complaints"] / res["trailing_median"].replace(0, np.nan)
    ).round(2)

    def _explain(row: pd.Series) -> str:
        hits = competing_corporate_event(row["entity"], row["month"])
        if not hits:
            return ""
        gap, when, desc, _url = hits[0]
        return f"{when} ({gap}d): {desc}"

    res["corporate_event"] = res.apply(_explain, axis=1)
    return res.sort_values("robust_z", ascending=False).reset_index(drop=True)


def segment_bursts(
    store: Store,
    segments: list[str] | None = None,
    z_threshold: float = 3.0,
    window: int = 12,
) -> pd.DataFrame:
    """Segment-months that jump above the segment's own trailing baseline."""
    df = monthly_counts(store, segments, by="segment")
    if df.empty:
        return df
    out = []
    for segment, grp in df.groupby("segment"):
        s = (
            grp.sort_values("month_start")
            .set_index("month_start")["complaints"]
            .asfreq("MS", fill_value=0)
        )
        z = _robust_z_trailing(s, window=window)
        out.append(
            pd.DataFrame(
                {
                    "segment": segment,
                    "month": s.index.strftime("%Y-%m"),
                    "complaints": s.values,
                    "robust_z": z.values,
                }
            )
        )
    res = pd.concat(out, ignore_index=True)
    return (
        res[res["robust_z"] >= z_threshold]
        .sort_values("robust_z", ascending=False)
        .reset_index(drop=True)
    )


def new_entrant_companies(
    store: Store,
    segments: list[str] | None = None,
    min_first_month: int = 200,
) -> pd.DataFrame:
    """Companies whose very first month already carries high volume.

    A company appearing from nothing at high volume is usually a corporate
    rename, an acquisition, or a newly-regulated entity -- all benign. It is
    included because it also produces a large artificial jump in any
    company-level series, and needs to be identifiable as such.
    """
    rows = store.query(
        "SELECT company, MIN(month) AS first_month, COUNT(*) AS total "
        "FROM complaints WHERE company <> '' GROUP BY company"
    )
    firsts = pd.DataFrame([dict(r) for r in rows])
    if firsts.empty:
        return firsts

    df = monthly_counts(store, segments, by="company")
    if df.empty:
        return pd.DataFrame()
    merged = df.merge(firsts, on="company")
    first_rows = merged[merged["month"] == merged["first_month"]]
    hits = first_rows[first_rows["complaints"] >= min_first_month]
    return (
        hits[["company", "first_month", "complaints", "total"]]
        .rename(columns={"complaints": "first_month_complaints"})
        .sort_values("first_month_complaints", ascending=False)
        .reset_index(drop=True)
    )


def channel_mix(
    store: Store,
    segments: list[str] | None = None,
    freq: str = "month",
) -> pd.DataFrame:
    """Submission-channel composition over time, as counts and shares."""
    df = monthly_counts(store, segments, by="submitted_via")
    if df.empty:
        return df
    if freq == "year":
        df["period"] = df["month"].str[:4]
    else:
        df["period"] = df["month"]

    pivot = (
        df.pivot_table(
            index="period", columns="submitted_via",
            values="complaints", aggfunc="sum", fill_value=0,
        )
        .sort_index()
    )
    totals = pivot.sum(axis=1)
    shares = pivot.div(totals, axis=0).add_suffix("_share")
    out = pd.concat([pivot, shares], axis=1)
    out["total"] = totals
    return out.reset_index()


def channel_shift_around(
    store: Store,
    intervention: str,
    segments: list[str] | None = None,
    window_months: int = 18,
) -> pd.DataFrame:
    """Channel mix before vs after an intervention date."""
    mix = channel_mix(store, segments)
    if mix.empty:
        return mix
    mix["period_ts"] = pd.to_datetime(mix["period"] + "-01")
    cut = pd.Timestamp(intervention)
    lo = cut - pd.DateOffset(months=window_months)
    hi = cut + pd.DateOffset(months=window_months)

    pre = mix[(mix["period_ts"] >= lo) & (mix["period_ts"] < cut)]
    post = mix[(mix["period_ts"] >= cut) & (mix["period_ts"] <= hi)]
    if pre.empty or post.empty:
        return pd.DataFrame()

    channels = [c for c in mix.columns if c.endswith("_share")]
    rows = []
    for ch in channels:
        name = ch[: -len("_share")]
        pre_share = float(pre[ch].mean())
        post_share = float(post[ch].mean())
        pre_n = float(pre[name].sum()) if name in pre else 0.0
        post_n = float(post[name].sum()) if name in post else 0.0
        rows.append(
            {
                "channel": name,
                "pre_share": round(pre_share, 5),
                "post_share": round(post_share, 5),
                "share_change_pp": round((post_share - pre_share) * 100, 3),
                "pre_complaints": int(pre_n),
                "post_complaints": int(post_n),
                "pct_volume_change": (
                    round((post_n / pre_n - 1) * 100, 1) if pre_n else None
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("share_change_pp", ascending=False)
