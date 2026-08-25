"""Interrupted time series and changepoint detection.

WHY THIS MODULE IS DELIBERATELY CONSERVATIVE
--------------------------------------------
The CFPB complaint series grows steeply and non-linearly over its whole life,
long before any LLM existed. Fitting a segmented regression to a series like
that will report a large, highly significant "level shift" at almost ANY date
you nominate, because the break term is absorbing ordinary curvature. Reporting
such a coefficient as an LLM effect would be a straightforward statistical
error, and one that is easy to make and hard to see.

Three guardrails are built in:

1. ``placebo_test`` refits the identical model at many dates where nothing
   relevant happened. If the real intervention date is unremarkable against
   that distribution, there is no effect to report -- regardless of its p-value.
2. ``detect_changepoints`` searches for breaks WITHOUT being told the candidate
   dates, so agreement with an LLM milestone is a finding rather than an
   assumption.
3. Negative binomial is the default count model. Complaint counts are
   overdispersed, and OLS or Poisson on data like this produce standard errors
   that are far too small, which manufactures significance.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm


@dataclass
class ITSResult:
    intervention: str
    n_obs: int
    model: str
    level_change_pct: float
    level_pvalue: float
    slope_change: float
    slope_pvalue: float
    pre_mean: float
    post_mean: float
    params: dict[str, float] = field(default_factory=dict)
    pvalues: dict[str, float] = field(default_factory=dict)
    summary_text: str = ""

    def as_row(self) -> dict[str, object]:
        return {
            "intervention": self.intervention,
            "model": self.model,
            "n_obs": self.n_obs,
            "level_change_pct": round(self.level_change_pct, 2),
            "level_p": round(self.level_pvalue, 5),
            "slope_change": round(self.slope_change, 5),
            "slope_p": round(self.slope_pvalue, 5),
            "pre_mean": round(self.pre_mean, 1),
            "post_mean": round(self.post_mean, 1),
        }


def _design(
    series: pd.Series, intervention: str, seasonality: bool
) -> tuple[pd.DataFrame, pd.Series]:
    """Standard ITS design matrix: trend, step, and slope-change terms."""
    idx = series.index
    cut = pd.Timestamp(intervention).to_period("M").to_timestamp()
    t = np.arange(len(idx), dtype=float)
    post = (idx >= cut).astype(float)
    # Months elapsed since the intervention, 0 before it.
    time_since = np.where(post > 0, np.cumsum(post) - 1, 0).astype(float)

    X = pd.DataFrame(
        {"t": t, "post": post, "t_post": time_since}, index=idx
    )
    if seasonality:
        # 11 month dummies (January is the reference level).
        for m in range(2, 13):
            X[f"m{m:02d}"] = (idx.month == m).astype(float)
    return sm.add_constant(X), series.astype(float)


def fit_its(
    series: pd.Series,
    intervention: str,
    model: str = "nbinom",
    seasonality: bool = True,
) -> ITSResult:
    """Fit a segmented regression with a level and slope change.

    model: ``nbinom`` (default, handles overdispersed counts), ``poisson``,
    or ``ols_log`` (OLS on log counts with HAC standard errors).
    """
    X, y = _design(series, intervention, seasonality)
    if len(y) < 24:
        raise ValueError(
            f"need at least 24 months for an ITS fit, got {len(y)}"
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if model == "nbinom":
            # Estimate dispersion from a Poisson first pass, then refit.
            poisson = sm.GLM(y, X, family=sm.families.Poisson()).fit()
            alpha = _estimate_alpha(y, poisson.mu, X.shape[1])
            res = sm.GLM(
                y, X, family=sm.families.NegativeBinomial(alpha=alpha)
            ).fit()
        elif model == "poisson":
            res = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        elif model == "ols_log":
            res = sm.OLS(np.log1p(y), X).fit(
                cov_type="HAC", cov_kwds={"maxlags": 12}
            )
        else:
            raise ValueError(f"unknown model {model!r}")

    cut = pd.Timestamp(intervention)
    pre, post = series[series.index < cut], series[series.index >= cut]
    # Coefficients are on a log scale in every supported model, so
    # exp(beta) - 1 is the proportional level change.
    level_pct = (float(np.exp(res.params["post"])) - 1.0) * 100.0

    return ITSResult(
        intervention=str(pd.Timestamp(intervention).date()),
        n_obs=len(y),
        model=model,
        level_change_pct=level_pct,
        level_pvalue=float(res.pvalues["post"]),
        slope_change=float(res.params["t_post"]),
        slope_pvalue=float(res.pvalues["t_post"]),
        pre_mean=float(pre.mean()) if len(pre) else float("nan"),
        post_mean=float(post.mean()) if len(post) else float("nan"),
        params={k: float(v) for k, v in res.params.items()},
        pvalues={k: float(v) for k, v in res.pvalues.items()},
        summary_text=str(res.summary()),
    )


def _estimate_alpha(y: pd.Series, mu: np.ndarray, k: int) -> float:
    """Method-of-moments dispersion estimate for the negative binomial."""
    resid = (np.asarray(y, dtype=float) - mu) ** 2 - mu
    denom = mu ** 2
    dof = max(len(y) - k, 1)
    alpha = float(np.sum(resid / denom) / dof)
    # A non-positive estimate means the data are not overdispersed; a tiny
    # positive alpha then makes the NB fit reduce to Poisson.
    return max(alpha, 1e-6)


def placebo_test(
    series: pd.Series,
    intervention: str,
    model: str = "nbinom",
    seasonality: bool = True,
    min_side: int = 12,
    exclude_months: int = 6,
) -> dict[str, object]:
    """Refit the model at every other candidate date for comparison.

    Returns the real estimate alongside the distribution of placebo estimates
    and an empirical percentile. A real intervention should sit in the tail; if
    it sits mid-distribution, the model is describing the series' own curvature
    rather than an event.

    ``exclude_months`` drops placebo dates near the real one, since those would
    partly capture the same shift.
    """
    real = fit_its(series, intervention, model=model, seasonality=seasonality)
    cut = pd.Timestamp(intervention)

    placebo_effects: list[float] = []
    placebo_dates: list[str] = []
    candidates = series.index[min_side: len(series) - min_side]
    for cand in candidates:
        if abs((cand.to_period("M") - cut.to_period("M")).n) <= exclude_months:
            continue
        try:
            r = fit_its(
                series, str(cand.date()), model=model, seasonality=seasonality
            )
        except Exception:
            continue
        if np.isfinite(r.level_change_pct):
            placebo_effects.append(r.level_change_pct)
            placebo_dates.append(str(cand.date()))

    arr = np.array(placebo_effects, dtype=float)
    if arr.size:
        pct = float((np.abs(arr) < abs(real.level_change_pct)).mean() * 100.0)
        larger = int((np.abs(arr) >= abs(real.level_change_pct)).sum())
    else:
        pct, larger = float("nan"), 0

    return {
        "real": real.as_row(),
        "placebo_n": int(arr.size),
        "placebo_median_abs_effect": (
            round(float(np.median(np.abs(arr))), 2) if arr.size else None
        ),
        "placebo_p95_abs_effect": (
            round(float(np.percentile(np.abs(arr), 95)), 2) if arr.size else None
        ),
        "real_effect_percentile": round(pct, 1) if arr.size else None,
        "placebo_dates_with_larger_effect": larger,
        "verdict": _verdict(pct, larger, arr.size),
        "placebo_detail": dict(zip(placebo_dates, [round(v, 2) for v in arr])),
    }


def _verdict(pct: float, larger: int, n: int) -> str:
    if not n or not np.isfinite(pct):
        return "inconclusive: no placebo fits converged"
    if pct >= 95:
        return (
            "distinctive: the effect at the real date exceeds 95% of placebo "
            "dates, so it is unlikely to be ordinary series curvature"
        )
    if pct >= 80:
        return (
            "suggestive: larger than most placebo dates but inside the range "
            "the series produces on its own"
        )
    return (
        f"NOT distinctive: {larger} of {n} placebo dates produce an effect at "
        "least as large. The segmented regression is fitting the series' own "
        "curvature, not an event at this date"
    )


def detect_changepoints(
    series: pd.Series,
    max_breaks: int = 5,
    penalty: float | None = None,
    log_transform: bool = True,
) -> list[dict[str, object]]:
    """Find structural breaks without being told where to look.

    Uses binary segmentation on a log-transformed series (growth in complaint
    volume is multiplicative, so breaks are additive in logs). Returns detected
    break dates with the mean level either side.
    """
    import ruptures as rpt

    y = np.asarray(series, dtype=float)
    signal = np.log1p(y) if log_transform else y
    if len(signal) < 24:
        return []

    algo = rpt.Binseg(model="l2").fit(signal.reshape(-1, 1))
    pen = penalty if penalty is not None else 3.0 * float(np.std(signal))
    try:
        bkps = algo.predict(pen=pen)
    except Exception:
        bkps = algo.predict(n_bkps=min(max_breaks, len(signal) // 12))

    out: list[dict[str, object]] = []
    prev = 0
    for b in bkps:
        if b >= len(series):
            break
        before = y[prev:b]
        after = y[b: min(len(y), b + len(before) or b + 1)]
        out.append(
            {
                "break_date": str(series.index[b].date()),
                "index": int(b),
                "mean_before": round(float(np.mean(before)), 1) if before.size else None,
                "mean_after": round(float(np.mean(after)), 1) if after.size else None,
                "pct_change": (
                    round((float(np.mean(after)) / float(np.mean(before)) - 1) * 100, 1)
                    if before.size and after.size and np.mean(before) > 0
                    else None
                ),
            }
        )
        prev = b
    return out


def nearest_event(break_date: str, events: dict[str, str]) -> tuple[str, int]:
    """Closest named event to a detected break, and the gap in days."""
    b = pd.Timestamp(break_date)
    best, best_gap = "", 10**9
    for name, when in events.items():
        gap = abs((b - pd.Timestamp(when)).days)
        if gap < best_gap:
            best, best_gap = name, gap
    return best, best_gap


def competing_explanations(
    break_date: str, segment: str, within_days: int = 180
) -> list[tuple[int, str, str, str]]:
    """Known policy/market shocks near a detected break, closest first.

    A break that sits nearer a policy shock than an LLM milestone should be
    attributed to the policy shock unless there is a specific reason not to.
    Returns (gap_days, event_date, description, source_url).
    """
    from .. import config

    b = pd.Timestamp(break_date)
    hits = []
    for entry in config.CONFOUNDING_EVENTS.get(segment, []):
        when, desc = entry[0], entry[1]
        url = entry[2] if len(entry) > 2 else ""
        gap = abs((b - pd.Timestamp(when)).days)
        if gap <= within_days:
            hits.append((gap, when, desc, url))
    return sorted(hits)
