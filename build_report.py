"""Render out/report.html -- the written findings report.

Every figure and table is computed from out/findings.json,
out/placebo_and_series.json and out/exact_duplicate_groups.csv, so the prose and
the numbers cannot drift apart. Charts are emitted as inline theme-aware SVG
(CSS custom properties, no external assets) so the page works as a published
Artifact in both light and dark mode.

    python collect_findings.py     # first: gather statistics
    python build_report.py         # then: render the page
"""
from __future__ import annotations

import ast
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfpb_inspect import config
from cfpb_inspect.store import Store

OUT = config.OUT_DIR
FINDINGS = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
PLACEBO = json.loads((OUT / "placebo_and_series.json").read_text(encoding="utf-8"))
_fu = OUT / "followups.json"
FOLLOWUPS = json.loads(_fu.read_text(encoding="utf-8")) if _fu.exists() else {}

SEG_LABEL = {
    "credit_reporting": "Credit reporting",
    "debt_collection": "Debt collection",
    "mortgage": "Mortgage",
    "card": "Cards",
    "student_loan": "Student loans",
    "consumer_loan": "Consumer loans",
}

# ---------------------------------------------------------------------------
# SVG chart primitives
# ---------------------------------------------------------------------------

W, H = 860, 380
PAD = {"l": 62, "r": 24, "t": 18, "b": 46}


def _x(i: int, n: int) -> float:
    span = W - PAD["l"] - PAD["r"]
    return PAD["l"] + (span * i / max(n - 1, 1))


def _y(v: float, lo: float, hi: float) -> float:
    span = H - PAD["t"] - PAD["b"]
    frac = 0.0 if hi == lo else (v - lo) / (hi - lo)
    return H - PAD["b"] - span * frac


def _svg_open(title: str, desc: str) -> list[str]:
    return [
        f'<svg viewBox="0 0 {W} {H}" role="img" class="chart" '
        f'aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        f"<desc>{html.escape(desc)}</desc>",
    ]


def _grid_y(ticks: list[tuple[float, str]], lo: float, hi: float) -> list[str]:
    parts = []
    for val, label in ticks:
        y = _y(val, lo, hi)
        parts.append(
            f'<line x1="{PAD["l"]}" y1="{y:.1f}" x2="{W - PAD["r"]}" '
            f'y2="{y:.1f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{PAD["l"] - 10}" y="{y + 4:.1f}" class="tick" '
            f'text-anchor="end">{html.escape(label)}</text>'
        )
    return parts


def _x_labels(months: list[str], every: int) -> list[str]:
    parts = []
    for i, m in enumerate(months):
        if i % every and i != len(months) - 1:
            continue
        parts.append(
            f'<text x="{_x(i, len(months)):.1f}" y="{H - PAD["b"] + 20}" '
            f'class="tick" text-anchor="middle">{m[:4]}</text>'
        )
    return parts


def line_chart(
    months: list[str],
    series: list[tuple[str, list[float | None], int]],
    ticks: list[tuple[float, str]],
    lo: float,
    hi: float,
    title: str,
    desc: str,
    markers: list[tuple[str, str]] | None = None,
    x_every: int = 24,
) -> str:
    parts = _svg_open(title, desc)
    parts += _grid_y(ticks, lo, hi)
    parts += _x_labels(months, x_every)

    for when, label in markers or []:
        if when not in months:
            continue
        xi = _x(months.index(when), len(months))
        parts.append(
            f'<line x1="{xi:.1f}" y1="{PAD["t"]}" x2="{xi:.1f}" '
            f'y2="{H - PAD["b"]}" class="event"/>'
        )
        parts.append(
            f'<text x="{xi + 5:.1f}" y="{PAD["t"] + 12}" class="event-label">'
            f"{html.escape(label)}</text>"
        )

    for name, values, slot in series:
        pts, run = [], []
        for i, v in enumerate(values):
            if v is None:
                if len(run) > 1:
                    pts.append(run)
                run = []
                continue
            run.append(f"{_x(i, len(months)):.1f},{_y(v, lo, hi):.1f}")
        if len(run) > 1:
            pts.append(run)
        for chunk in pts:
            parts.append(
                f'<polyline points="{" ".join(chunk)}" class="ln s{slot}"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def scatter_chart(
    points: list[tuple[float, float, str]],
    xlo: float, xhi: float, ylo: float, yhi: float,
    xticks: list[tuple[float, str]], yticks: list[tuple[float, str]],
    title: str, desc: str, label_states: set[str],
    x_title: str = "", y_title: str = "",
) -> str:
    parts = _svg_open(title, desc)
    for val, label in yticks:
        y = _y(val, ylo, yhi)
        parts.append(f'<line x1="{PAD["l"]}" y1="{y:.1f}" x2="{W - PAD["r"]}" '
                     f'y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD["l"] - 10}" y="{y + 4:.1f}" class="tick" '
                     f'text-anchor="end">{html.escape(label)}</text>')
    span = W - PAD["l"] - PAD["r"]
    for val, label in xticks:
        x = PAD["l"] + span * (val - xlo) / (xhi - xlo)
        parts.append(f'<text x="{x:.1f}" y="{H - PAD["b"] + 20}" class="tick" '
                     f'text-anchor="middle">{html.escape(label)}</text>')

    for xv, yv, name in points:
        cx = PAD["l"] + span * (xv - xlo) / (xhi - xlo)
        cy = _y(yv, ylo, yhi)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.5" '
                     f'class="dot s1"><title>{html.escape(name)}: '
                     f'{xv:,.0f} per 100k, {yv:.1f}% templated</title></circle>')
        if name in label_states:
            parts.append(f'<text x="{cx + 9:.1f}" y="{cy + 4:.1f}" '
                         f'class="pt-label">{html.escape(name)}</text>')
    if x_title:
        parts.append(
            f'<text x="{(PAD["l"] + W - PAD["r"]) / 2:.0f}" y="{H - 6}" '
            f'class="axis-title" text-anchor="middle">{html.escape(x_title)}</text>'
        )
    if y_title:
        parts.append(
            f'<text x="14" y="{(PAD["t"] + H - PAD["b"]) / 2:.0f}" '
            f'class="axis-title" text-anchor="middle" '
            f'transform="rotate(-90 14 {(PAD["t"] + H - PAD["b"]) / 2:.0f})">'
            f"{html.escape(y_title)}</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


def placebo_chart(
    placebo: list[float], real: float, title: str, desc: str, seg_label: str
) -> str:
    lo, hi = 0.0, max(max(placebo, default=1.0), abs(real)) * 1.05
    nbins = 26
    edges = [lo + (hi - lo) * i / nbins for i in range(nbins + 1)]
    counts = [0] * nbins
    for v in placebo:
        for b in range(nbins):
            if edges[b] <= v < edges[b + 1] or (b == nbins - 1 and v >= edges[b]):
                counts[b] += 1
                break
    ymax = max(counts) or 1
    parts = _svg_open(title, desc)
    ticks = [(0, "0"), (ymax / 2, f"{ymax / 2:.0f}"), (ymax, str(ymax))]
    parts += _grid_y(ticks, 0, ymax)

    span = W - PAD["l"] - PAD["r"]
    bw = span / nbins
    for b, c in enumerate(counts):
        if not c:
            continue
        x = PAD["l"] + bw * b
        y = _y(c, 0, ymax)
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{y:.1f}" width="{bw - 2:.1f}" '
            f'height="{H - PAD["b"] - y:.1f}" rx="3" class="bar s1"/>'
        )
    rx = PAD["l"] + span * (abs(real) - lo) / (hi - lo)
    parts.append(f'<line x1="{rx:.1f}" y1="{PAD["t"]}" x2="{rx:.1f}" '
                 f'y2="{H - PAD["b"]}" class="real"/>')
    anchor = "end" if rx > W * 0.62 else "start"
    dx = -8 if anchor == "end" else 8
    parts.append(
        f'<text x="{rx + dx:.1f}" y="{PAD["t"] + 14}" class="real-label" '
        f'text-anchor="{anchor}">actual effect at ChatGPT launch '
        f"{real:+.1f}%</text>"
    )
    for val, lbl in [(lo, "0%"), (hi / 2, f"{hi / 2:.0f}%"), (hi, f"{hi:.0f}%")]:
        x = PAD["l"] + span * (val - lo) / (hi - lo)
        parts.append(f'<text x="{x:.1f}" y="{H - PAD["b"] + 20}" class="tick" '
                     f'text-anchor="middle">{html.escape(lbl)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# chart construction from the collected data
# ---------------------------------------------------------------------------

def build_volume_chart() -> str:
    import math

    series = PLACEBO["_monthly_series"]
    months = sorted(series["credit_reporting"])
    months = [m for m in months if m >= "2012-01"]
    cr = [series["credit_reporting"].get(m, 0) for m in months]
    other = [
        sum(series[s].get(m, 0) for s in series if s != "credit_reporting")
        for m in months
    ]

    def lg(vals):
        return [math.log10(v) if v and v > 0 else None for v in vals]

    lo, hi = 2.0, 6.0
    ticks = [(2, "100"), (3, "1k"), (4, "10k"), (5, "100k"), (6, "1M")]
    return line_chart(
        months,
        [("Credit reporting", lg(cr), 1), ("All five other segments", lg(other), 2)],
        ticks, lo, hi,
        "Monthly complaint volume by segment, log scale",
        "Credit reporting rises from roughly 100 complaints a month in 2012 to "
        "over 600,000 by mid-2026, far outpacing every other segment combined.",
        markers=[("2022-11", "ChatGPT")],
    )


def build_templating_chart() -> str:
    by = FINDINGS["templated_share_by_month"]
    months = [m for m in sorted(by["credit_reporting"]) if "2016-01" <= m <= "2025-12"]

    def pct(seg_names):
        out = []
        for m in months:
            n = t = 0
            for s in seg_names:
                row = by.get(s, {}).get(m)
                if row:
                    n += row["narratives"]
                    t += row["templated"]
            out.append(100.0 * t / n if n >= 150 else None)
        return out

    others = ["mortgage", "card", "student_loan", "consumer_loan"]
    ticks = [(0, "0%"), (15, "15%"), (30, "30%"), (45, "45%"), (60, "60%")]
    return line_chart(
        months,
        [
            ("Credit reporting", pct(["credit_reporting"]), 1),
            ("Debt collection", pct(["debt_collection"]), 2),
            ("Other four segments", pct(others), 3),
        ],
        ticks, 0, 60,
        "Share of narratives that are byte-identical to at least 49 others",
        "Templating in credit reporting climbs steadily from under 1% in 2016 to "
        "about 50% by late 2025, with no break at the ChatGPT launch line. "
        "Mortgage, cards, student and consumer loans stay near zero throughout.",
        markers=[("2022-11", "ChatGPT")],
        x_every=12,
    )


def build_state_chart() -> str:
    rows = FINDINGS["state_rate_vs_templating"]
    pts = [(r["rate_per_100k_2025"], r["templated_pct"], r["state"]) for r in rows]
    xhi = max(p[0] for p in pts) * 1.06
    yhi = max(p[1] for p in pts) * 1.12
    highlight = {"GA", "MS", "FL", "AL", "LA", "TX", "SC", "WY", "SD", "MT", "VT", "ME"}
    r = FINDINGS.get("rate_templating_correlation", {}).get("pearson_r")
    return scatter_chart(
        pts, 0, xhi, 0, yhi,
        [(0, "0"), (xhi / 2, f"{xhi / 2:,.0f}"), (xhi, f"{xhi:,.0f}")],
        [(0, "0%"), (yhi / 2, f"{yhi / 2:.0f}%"), (yhi, f"{yhi:.0f}%")],
        "State filing rate against templated share, credit reporting, 2025",
        f"Each point is a state. States that file more complaints per resident "
        f"also file more templated ones; Pearson r = {r}.",
        highlight,
        x_title="Credit-reporting complaints per 100,000 residents, 2025",
        y_title="Templated share of narratives",
    )


def build_placebo_charts() -> tuple[str, str]:
    out = []
    for seg in ("credit_reporting", "card"):
        d = PLACEBO[seg]
        vals = [abs(v) for v in d["placebo"].values()]
        out.append(
            placebo_chart(
                vals, d["real"]["level_change_pct"],
                f"Placebo distribution, {SEG_LABEL[seg]}",
                "Distribution of absolute level-change estimates from refitting the "
                "same model at every other candidate date, with the estimate at "
                "the real intervention date marked.",
                SEG_LABEL[seg],
            )
        )
    return out[0], out[1]


def cohesion_summary() -> dict | None:
    """Cluster counts by within-cluster cohesion band.

    Single-linkage components chain, so a component's size says nothing about
    whether one template is being reused. Splitting the export by measured
    cohesion separates genuine mass-copied templates from families of related
    boilerplate that merely share an opening paragraph.
    """
    import pandas as pd

    path = OUT / "near_duplicate_clusters.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "cohesion_pct_above_threshold" not in df.columns:
        return None
    df = df[df["cohesion_mean"].notna()]
    if df.empty:
        return None

    bands = [
        ("tight", 80, 101, "at least 80% of sampled members meet the threshold"),
        ("moderate", 50, 80, "50-79%"),
        ("loose", 20, 50, "20-49%"),
        ("chained", 0, 20, "under 20%"),
    ]
    rows = []
    for name, lo, hi, note in bands:
        sel = df[
            (df["cohesion_pct_above_threshold"] >= lo)
            & (df["cohesion_pct_above_threshold"] < hi)
        ]
        rows.append({
            "band": name, "note": note, "clusters": int(len(sel)),
            "complaints": int(sel["chained_size"].sum()),
        })
    biggest = df.nlargest(6, "chained_size")[
        ["chained_size", "cohesion_mean", "cohesion_pct_above_threshold",
         "distinct_companies", "distinct_states"]
    ].to_dict("records")
    return {
        "measured": int(len(df)),
        "bands": rows,
        "tight_complaints": rows[0]["complaints"],
        "tight_clusters": rows[0]["clusters"],
        "biggest": biggest,
    }


def ordinal(n: float) -> str:
    """1st/2nd/3rd/11th... Plain f"{n}th" produced "2th" and "82th"."""
    i = int(round(n))
    if 10 <= i % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suf}"


def esc(s) -> str:
    return html.escape(str(s))


def legend(items: list[tuple[str, int]]) -> str:
    """Legend markup. Identity is carried by a swatch beside text in ink
    tokens, never by colouring the label text itself."""
    sw = "".join(
        f'<span class="lg"><i class="sw s{slot}"></i>{esc(name)}</span>'
        for name, slot in items
    )
    return f'<div class="legend">{sw}</div>'


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)

    def cell(c: str) -> str:
        # A cell whose whole content is a numeric span gets right-aligned, so
        # magnitudes line up without every call site passing an alignment spec.
        klass = ' class="n"' if str(c).startswith("<span class='n'>") else ""
        return f"<td{klass}>{c}</td>"

    body = "".join(
        "<tr>" + "".join(cell(c) for c in r) + "</tr>" for r in rows
    )
    return (
        f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def top_templates(n: int = 6) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(OUT / "exact_duplicate_groups.csv")
    df = df.nlargest(n, "size")
    store = Store()
    rows = []
    for _, r in df.iterrows():
        ids = r["complaint_ids"]
        ids = ast.literal_eval(ids) if isinstance(ids, str) else []
        txt, issue = "", ""
        if ids:
            got = store.query(
                "SELECT narrative, issue FROM complaints WHERE complaint_id=?",
                (int(ids[0]),),
            )
            if got:
                txt = " ".join((got[0]["narrative"] or "").split())
                issue = got[0]["issue"] or ""
        rows.append(
            {
                "size": int(r["size"]),
                "companies": int(r["distinct_companies"]),
                "states": int(r["distinct_states"]),
                "first": str(r["first_date"])[:7],
                "last": str(r["last_date"])[:7],
                "issue": issue,
                "text": txt,
            }
        )
    return rows
