"""Build analysis-ready time series from the local store.

All series are grouped on ``segment`` (the canonical crosswalk value), never on
the raw ``product`` label -- see cfpb_inspect.taxonomy for why that distinction
is load-bearing rather than cosmetic.
"""
from __future__ import annotations

import pandas as pd

from ..store import Store


def monthly_counts(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    by: str | None = None,
    drop_partial_final_month: bool = True,
) -> pd.DataFrame:
    """Monthly complaint counts, optionally split by another column.

    ``drop_partial_final_month`` removes the current month, which is always
    incomplete and would otherwise read as a collapse in volume at the end of
    every series.
    """
    cols = ["month"]
    if by:
        cols.append(by)
    where, params = _where(segments, start, end)
    sql = (
        f"SELECT {', '.join(cols)}, COUNT(*) AS complaints, "
        "SUM(has_narrative) AS narratives "
        f"FROM complaints {where} GROUP BY {', '.join(cols)} ORDER BY month"
    )
    df = pd.DataFrame([dict(r) for r in store.query(sql, params)])
    if df.empty:
        return df

    df["month_start"] = pd.to_datetime(df["month"] + "-01")
    if drop_partial_final_month:
        last = df["month_start"].max()
        today = pd.Timestamp.today().normalize().replace(day=1)
        if last >= today:
            df = df[df["month_start"] < today]
    return df.reset_index(drop=True)


def daily_counts(
    store: Store,
    segments: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    by: str | None = None,
) -> pd.DataFrame:
    """Daily counts, used for burst detection where monthly is too coarse."""
    cols = ["date_received"]
    if by:
        cols.append(by)
    where, params = _where(segments, start, end)
    sql = (
        f"SELECT {', '.join(cols)}, COUNT(*) AS complaints "
        f"FROM complaints {where} GROUP BY {', '.join(cols)} "
        "ORDER BY date_received"
    )
    df = pd.DataFrame([dict(r) for r in store.query(sql, params)])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date_received"])
    return df


def to_series(df: pd.DataFrame, value: str = "complaints") -> pd.Series:
    """Collapse a monthly frame to a gap-filled, date-indexed series.

    Months with no complaints are filled with 0 rather than left absent: an
    absent month silently shortens the series and shifts every subsequent time
    index, which would misplace an intervention date.
    """
    s = (
        df.groupby("month_start")[value]
        .sum()
        .sort_index()
        .asfreq("MS", fill_value=0)
    )
    s.name = value
    return s


def _where(
    segments: list[str] | None, start: str | None, end: str | None
) -> tuple[str, list]:
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
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params
