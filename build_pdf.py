"""Render the findings as an SPPI whitepaper PDF.

    python build_pdf.py

Layout, typography and furniture follow
Collateral/Whitepapers/010 Bank Charters August 2026/SPPI Report Application
Pending.pdf; see sppi_brand.py for the extracted specification.

The cover of the template carries a blue-duotone photograph of the First Bank
of the United States, which is specific to that paper's subject. This report
generates its own cover art in the same duotone treatment from its own data --
the credit-reporting complaint curve -- rather than reusing imagery about a
different topic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sppi_brand as B  # noqa: E402
from cfpb_inspect import config  # noqa: E402

OUT = config.OUT_DIR
FINDINGS = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
PLACEBO = json.loads((OUT / "placebo_and_series.json").read_text(encoding="utf-8"))
FOLLOWUPS = json.loads((OUT / "followups.json").read_text(encoding="utf-8"))

ISSUE = "NO. 11  |  AUGUST 2026"
TITLE = "Copy, Paste, Dispute"
SUBTITLE = ("816,253 identical complaints: how templated filing took over the "
            "federal consumer complaint database, and why artificial "
            "intelligence did not cause it")
AUTHORS = "Patrick M. Brenner"
QUOTE = ("The banking system is dependent upon fair and accurate credit "
         "reporting. Inaccurate credit reports directly impair the efficiency "
         "of the banking system, and unfair credit reporting methods undermine "
         "the public confidence which is essential to the continued "
         "functioning of the banking system.")
QUOTE_ATTR = "— Fair Credit Reporting Act, 15 U.S.C. § 1681(a)(1)"
SHORTURL = "This paper, in its entirety, can be found at https://southwestpolicy.com/sppi11"


# ---------------------------------------------------------------------------
# cover art: the complaint curve as a duotone field
# ---------------------------------------------------------------------------

def make_cover_art(path: Path, w: int = 2550, h: int = 3300) -> Path:
    """Full-bleed duotone cover in the house blue, drawn from the data."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    series = PLACEBO["_monthly_series"]["credit_reporting"]
    months = sorted(m for m in series if m >= "2012-01")
    vals = np.array([series[m] for m in months], dtype=float)
    logv = np.log10(np.clip(vals, 1, None))

    # vertical gradient, navy at the top to a lighter blue at the foot
    top = np.array([0, 26, 58], dtype=float)
    bot = np.array([31, 74, 122], dtype=float)
    ramp = np.linspace(0, 1, h)[:, None]
    bg = (top[None, None, :] * (1 - ramp[:, :, None])
          + bot[None, None, :] * ramp[:, :, None])
    img = Image.fromarray(np.repeat(bg.astype(np.uint8), w, axis=1), "RGB")

    d = ImageDraw.Draw(img, "RGBA")
    # faint horizontal rules, echoing a chart grid
    for i in range(1, 9):
        y = int(h * (0.36 + i * 0.072))
        d.line([(0, y), (w, y)], fill=(255, 255, 255, 16), width=3)

    # The curve is confined to the lower third and drawn dim. On the first
    # attempt it swept up through the pull quote at full brightness and made
    # the quote unreadable; cover art has to sit behind the type, not compete
    # with it.
    lo, hi = logv.min(), logv.max()
    x = np.linspace(-w * 0.04, w * 1.04, len(logv))
    y = h * 0.985 - (logv - lo) / (hi - lo) * (h * 0.26)
    pts = list(zip(x.tolist(), y.tolist()))

    d.polygon(pts + [(w * 1.04, h), (-w * 0.04, h)], fill=(143, 180, 217, 40))
    d.line(pts, fill=(205, 226, 248, 120), width=6, joint="curve")

    # navy veil: pushes the whole artwork back so white type reads cleanly
    veil = Image.new("RGB", (w, h), (0, 24, 54))
    img = Image.blend(img, veil, 0.34)

    # extra darkening across the top half, where the title and quote sit
    vg = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vg).rectangle([0, 0, w, int(h * 0.62)], fill=105)
    vg = vg.filter(ImageFilter.GaussianBlur(w // 8))
    img = Image.composite(Image.new("RGB", (w, h), (0, 20, 46)), img, vg)

    img.save(path, "PNG")
    return path


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------

def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in B.BRAND_DIR.glob("Minion*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams.update({
        "font.family": "Minion Pro",
        "font.size": 8.5,
        "axes.edgecolor": "#8a8a8a",
        "axes.linewidth": 0.6,
        "axes.labelcolor": "#202020",
        "text.color": "#202020",
        "xtick.color": "#404040",
        "ytick.color": "#404040",
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "figure.dpi": 300,
        "savefig.dpi": 300,
    })
    return plt


NAVY, MID, LIGHT, RED = "#002856", "#345c8a", "#8fb4d9", "#a3312e"


def _finish(ax, plt):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#d8dde2", linewidth=0.5)
    ax.set_axisbelow(True)


def chart_volume(path):
    import numpy as np
    plt = _mpl()
    s = PLACEBO["_monthly_series"]
    months = sorted(m for m in s["credit_reporting"] if m >= "2012-01")
    idx = np.arange(len(months))
    cr = np.array([s["credit_reporting"].get(m, 0) for m in months], float)
    ot = np.array([sum(s[k].get(m, 0) for k in s if k != "credit_reporting")
                   for m in months], float)
    fig, ax = plt.subplots(figsize=(5.5, 2.7))
    ax.plot(idx, np.clip(cr, 1, None), color=NAVY, lw=1.4, label="Credit reporting")
    ax.plot(idx, np.clip(ot, 1, None), color=MID, lw=1.4, ls="--",
            label="All five other segments")
    ax.set_yscale("log")
    ax.axvline(months.index("2022-11"), color="#9aa3aa", lw=0.9, ls=":")
    ax.text(months.index("2022-11") + 1.5, 3.2e5, "ChatGPT", fontsize=7.5,
            color="#5a6068")
    ticks = [i for i, m in enumerate(months) if m.endswith("-01") and int(m[:4]) % 2 == 0]
    ax.set_xticks(ticks); ax.set_xticklabels([months[i][:4] for i in ticks])
    ax.set_ylabel("complaints per month")
    ax.set_yticks([1e2, 1e3, 1e4, 1e5])
    ax.set_yticklabels(["100", "1,000", "10,000", "100,000"])
    ax.minorticks_off()
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _finish(ax, plt)
    fig.tight_layout(pad=0.3); fig.savefig(path); plt.close(fig)
    return path


def chart_templating(path):
    import numpy as np
    plt = _mpl()
    by = FINDINGS["templated_share_by_month"]
    months = [m for m in sorted(by["credit_reporting"]) if "2016-01" <= m <= "2025-12"]

    def pct(keys):
        out = []
        for m in months:
            n = t = 0
            for k in keys:
                r = by.get(k, {}).get(m)
                if r:
                    n += r["narratives"]; t += r["templated"]
            out.append(100 * t / n if n >= 150 else np.nan)
        return np.array(out)

    idx = np.arange(len(months))
    fig, ax = plt.subplots(figsize=(5.5, 2.7))
    ax.plot(idx, pct(["credit_reporting"]), color=NAVY, lw=1.6,
            label="Credit reporting")
    ax.plot(idx, pct(["debt_collection"]), color=MID, lw=1.4,
            label="Debt collection")
    ax.plot(idx, pct(["mortgage", "card", "student_loan", "consumer_loan"]),
            color="#9bb0c4", lw=1.2, ls="--", label="Other four segments")
    ax.axvline(months.index("2022-11"), color="#9aa3aa", lw=0.9, ls=":")
    ax.text(months.index("2022-11") + 1.5, 52, "ChatGPT", fontsize=7.5,
            color="#5a6068")
    ticks = [i for i, m in enumerate(months) if m.endswith("-01")]
    ax.set_xticks(ticks); ax.set_xticklabels([months[i][:4] for i in ticks])
    ax.set_ylim(0, 58); ax.set_ylabel("% of narratives byte-identical\nto ≥49 others")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _finish(ax, plt)
    fig.tight_layout(pad=0.3); fig.savefig(path); plt.close(fig)
    return path


def chart_placebo(path):
    import numpy as np
    plt = _mpl()
    d = PLACEBO["credit_reporting"]
    vals = np.array([abs(v) for v in d["placebo"].values()])
    real = d["real"]["level_change_pct"]
    fig, ax = plt.subplots(figsize=(5.5, 2.4))
    ax.hist(vals, bins=26, color=MID, edgecolor="white", linewidth=0.5)
    ax.axvline(abs(real), color=RED, lw=1.8)
    ax.text(abs(real) + 2, ax.get_ylim()[1] * 0.86,
            f"actual effect at\nChatGPT launch  {real:+.1f}%",
            fontsize=7.8, color=RED)
    ax.set_xlabel("absolute level-change estimate (%)")
    ax.set_ylabel("placebo dates")
    _finish(ax, plt)
    fig.tight_layout(pad=0.3); fig.savefig(path); plt.close(fig)
    return path


def chart_relief(path):
    import numpy as np
    plt = _mpl()
    r = FOLLOWUPS["relief"]
    groups = [("Credit reporting\n2024", r["credit_reporting_2024"]),
              ("Debt collection\n2024", r["debt_collection_2024"])]
    fig, ax = plt.subplots(figsize=(5.5, 2.3))
    x = np.arange(len(groups)); wdt = 0.32
    tv = [g[1]["templated"]["relief_pct"] for g in groups]
    ov = [g[1]["organic"]["relief_pct"] for g in groups]
    b1 = ax.bar(x - wdt / 2, tv, wdt, color=NAVY, label="Templated")
    b2 = ax.bar(x + wdt / 2, ov, wdt, color=LIGHT, label="Organic")
    for bars in (b1, b2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.4,
                    f"{bar.get_height():.1f}%", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([g[0] for g in groups])
    ax.set_ylim(0, 70); ax.set_ylabel("complaints closed with relief (%)")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    _finish(ax, plt)
    fig.tight_layout(pad=0.3); fig.savefig(path); plt.close(fig)
    return path
