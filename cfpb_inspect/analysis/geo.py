"""Per-capita geographic anomaly detection.

Complaint counts by state are dominated by population, so raw counts only ever
rediscover that California and Texas are large. Rates are computed per 100,000
residents using the population of the year the complaint was received.

INTERPRETING A HIGH RATE
A state with an unusually high per-capita rate is not evidence of fabrication.
Real drivers include the presence of a large credit-repair industry, a single
aggressive debt buyer operating regionally, state-level enforcement publicity,
and genuine differences in consumer harm. What is more diagnostic than a high
level is a high rate that appears abruptly, is concentrated in a handful of ZIP
prefixes, and is attached to few companies -- which is why
``state_rate_changes`` reports the change in rate around an intervention rather
than the level, and ``zip_concentration`` measures how tightly a state's
complaints cluster geographically.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

from ..store import Store

POP_PATH = Path(__file__).parent.parent / "reference" / "state_population.csv"

# Non-state values that appear in the CFPB `state` field. These have no
# population denominator in the Census state file and are excluded from rate
# calculations rather than silently divided by zero.
NON_STATES = {
    "PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP", "FM", "MH", "PW", "UM", "",
}


def load_population() -> pd.DataFrame:
    if not POP_PATH.exists():
        raise FileNotFoundError(
            f"{POP_PATH} missing; run: "
            "python -m cfpb_inspect.reference.build_population"
        )
    df = pd.read_csv(POP_PATH)
    return df.astype({"year": int, "population": int})


def state_year_rates(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Complaints per 100k residents by state and year."""
    clauses, params = [], []
    if segments:
        clauses.append(f"segment IN ({','.join('?' * len(segments))})")
        params.extend(segments)
    if start:
        clauses.append("date_received >= ?")
        params.append(start)
    if end:
        clauses.append("date_received <= ?")
        params.append(end)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = store.query(
        "SELECT state, substr(date_received,1,4) AS year, COUNT(*) AS complaints "
        f"FROM complaints {where} GROUP BY state, year",
        params,
    )
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df["year"] = df["year"].astype(int)

    excluded = df[df["state"].isin(NON_STATES)]["complaints"].sum()
    df = df[~df["state"].isin(NON_STATES)].copy()

    pop = load_population()
    merged = df.merge(pop, on=["state", "year"], how="left")

    # Years beyond the population file (e.g. the current year) carry forward
    # the latest available estimate, flagged so it is visible in output.
    latest_year = int(pop["year"].max())
    missing = merged["population"].isna()
    if missing.any():
        fallback = (
            pop[pop["year"] == latest_year].set_index("state")["population"]
        )
        merged.loc[missing, "population"] = merged.loc[missing, "state"].map(fallback)
        merged["population_carried_forward"] = missing
    else:
        merged["population_carried_forward"] = False

    merged = merged.dropna(subset=["population"])
    merged["rate_per_100k"] = (
        merged["complaints"] / merged["population"] * 100_000
    )
    merged.attrs["excluded_non_state_complaints"] = int(excluded)
    return merged.sort_values(["year", "rate_per_100k"], ascending=[True, False])


def rate_anomalies(rates: pd.DataFrame, min_year: int | None = None) -> pd.DataFrame:
    """Flag state-years whose rate is extreme relative to that year's states.

    Uses median and MAD rather than mean and standard deviation: a handful of
    genuinely extreme states would inflate a standard deviation enough to hide
    everything else.
    """
    df = rates.copy()
    if min_year:
        df = df[df["year"] >= min_year]

    out = []
    for year, grp in df.groupby("year"):
        med = grp["rate_per_100k"].median()
        mad = (grp["rate_per_100k"] - med).abs().median()
        scale = mad * 1.4826 if mad > 0 else grp["rate_per_100k"].std()
        g = grp.copy()
        g["national_median_rate"] = med
        g["robust_z"] = (
            (g["rate_per_100k"] - med) / scale if scale else np.nan
        )
        g["rate_ratio_to_median"] = g["rate_per_100k"] / med if med else np.nan
        out.append(g)

    res = pd.concat(out, ignore_index=True)
    return res.sort_values("robust_z", ascending=False)


def state_rate_changes(
    store: Store,
    intervention: str,
    segments: list[str] | None = None,
    window_years: int = 2,
) -> pd.DataFrame:
    """Change in each state's per-capita rate before vs after a date.

    A coordinated campaign should show up as a small number of states moving
    far more than the national shift, rather than every state rising together.
    """
    cut = pd.Timestamp(intervention)
    pre_start = (cut - pd.DateOffset(years=window_years)).date().isoformat()
    post_end = (cut + pd.DateOffset(years=window_years)).date().isoformat()

    pre = state_year_rates(
        store, segments, start=pre_start, end=(cut - pd.Timedelta(days=1)).date().isoformat()
    )
    post = state_year_rates(store, segments, start=cut.date().isoformat(), end=post_end)
    if pre.empty or post.empty:
        return pd.DataFrame()

    pre_avg = pre.groupby("state")["rate_per_100k"].mean().rename("pre_rate")
    post_avg = post.groupby("state")["rate_per_100k"].mean().rename("post_rate")
    df = pd.concat([pre_avg, post_avg], axis=1).dropna()
    df["pct_change"] = (df["post_rate"] / df["pre_rate"] - 1) * 100

    national = (df["post_rate"].sum() / df["pre_rate"].sum() - 1) * 100
    df["excess_vs_national_pp"] = df["pct_change"] - national
    df.attrs["national_pct_change"] = round(float(national), 2)
    df.attrs["intervention"] = str(cut.date())
    return df.sort_values("excess_vs_national_pp", ascending=False).reset_index()


def zip_concentration(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    min_complaints: int = 500,
) -> pd.DataFrame:
    """How concentrated each state's complaints are across ZIP prefixes.

    CFPB publishes ZIP codes truncated to three digits plus XX, so this is a
    regional measure, not a neighbourhood one. Reported as a Herfindahl index
    and as the share held by the single largest prefix; a state whose
    complaints collapse onto one prefix is worth a closer look.
    """
    clauses = ["zip_code IS NOT NULL", "zip_code <> ''"]
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

    rows = store.query(
        "SELECT state, substr(zip_code,1,3) AS zip3, COUNT(*) AS n "
        f"FROM complaints WHERE {' AND '.join(clauses)} "
        "GROUP BY state, zip3",
        params,
    )
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df = df[~df["state"].isin(NON_STATES)]

    out = []
    for state, grp in df.groupby("state"):
        total = grp["n"].sum()
        if total < min_complaints:
            continue
        shares = grp["n"] / total
        out.append(
            {
                "state": state,
                "complaints": int(total),
                "zip3_count": int(len(grp)),
                "herfindahl": round(float((shares ** 2).sum()), 4),
                "top_zip3": grp.loc[grp["n"].idxmax(), "zip3"],
                "top_zip3_share": round(float(shares.max()), 4),
            }
        )
    return pd.DataFrame(out).sort_values("herfindahl", ascending=False)
