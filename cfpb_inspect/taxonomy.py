"""Product taxonomy normalization.

THE PROBLEM THIS SOLVES
-----------------------
CFPB has renamed product categories at least twice over the life of the public
database. The same underlying segment appears under different `product` labels
in different eras. As of 2026-08-20 the credit-reporting segment exists as
three distinct labels:

    Credit reporting                                                    140,426
    Credit reporting, credit repair services, or other personal ...   2,163,770
    Credit reporting or other personal consumer reports              11,696,281

Grouping a time series on the raw `product` field makes each label's series
collapse to zero at its rename date while a new series appears from nothing.
That is a structural break of enormous magnitude, located at an administrative
event, and it will be picked up by any changepoint detector or segmented
regression as a real discontinuity.

For this project the danger is specific: the second credit-reporting rename
took effect 2023-08-24, INSIDE the LLM-adoption window we are testing.
Analyzing raw labels would manufacture exactly the finding we are looking for.
Every series in this tool is therefore built on `canonical_segment`, and
`raw_product_windows()` reports the observed active date range of each raw label
so renames stay visible.

The renames are demonstrably administrative rather than behavioural: on the full
extract, `credit_reporting`, `card` and `consumer_loan` all switch labels on the
same two dates, 2017-04-24 and 2023-08-24.

WHAT THIS CROSSWALK DOES *NOT* FIX
----------------------------------
Mapping labels onto one segment removes the discontinuity caused by the label
CHANGING. It cannot remove a genuine change in what the category COVERS.

The 2017-04-24 rename is the clear case. "Credit reporting" became "Credit
reporting, credit repair services, or other personal consumer reports" -- the
scope broadened to take in credit-repair services and other consumer reports.
More complaints then fall inside the segment for a purely definitional reason.
On the full extract the changepoint detector finds a +285% break at 2017-05-01,
one week after that rename, and the crosswalk does nothing to correct it.

So: a break at 2017-05 or 2023-08/09 in any affected segment should be treated
as taxonomy-driven until shown otherwise, and cross-rename comparisons of
credit_reporting levels are not like-for-like. Sub-product breakdowns are the
route to a genuinely constant-scope series, and are not yet implemented.
"""
from __future__ import annotations

from typing import Iterable

# canonical segment -> raw `product` labels that belong to it
SEGMENT_MAP: dict[str, tuple[str, ...]] = {
    "credit_reporting": (
        "Credit reporting",
        "Credit reporting, credit repair services, or other personal consumer reports",
        "Credit reporting or other personal consumer reports",
    ),
    "debt_collection": (
        "Debt collection",
    ),
    "debt_relief": (
        "Debt or credit management",
    ),
    "mortgage": (
        "Mortgage",
    ),
    "card": (
        "Credit card",
        "Credit card or prepaid card",
        "Prepaid card",
    ),
    "bank_account": (
        "Bank account or service",
        "Checking or savings account",
    ),
    "student_loan": (
        "Student loan",
    ),
    "consumer_loan": (
        "Consumer Loan",
        "Vehicle loan or lease",
        "Payday loan, title loan, personal loan, or advance loan",
        "Payday loan, title loan, or personal loan",
        "Payday loan",
    ),
    "money_transfer": (
        "Money transfer, virtual currency, or money service",
        "Money transfers",
        "Virtual currency",
    ),
    "other_financial_service": (
        "Other financial service",
    ),
}

# Notes on judgement calls in the map above, so reviewers can disagree with a
# specific choice rather than the whole thing.
SEGMENT_NOTES: dict[str, str] = {
    "card": (
        "'Credit card or prepaid card' spans two instruments that were split "
        "into separate labels in other eras. Rolled together so the series is "
        "continuous; use sub_product to separate credit from prepaid."
    ),
    "consumer_loan": (
        "The legacy 'Consumer Loan' label predates the split into vehicle, "
        "payday, title and personal loan labels. Rolled together for series "
        "continuity; use sub_product for the modern breakdown."
    ),
    "debt_relief": (
        "'Debt or credit management' covers credit-repair and debt-settlement "
        "services. Kept SEPARATE from credit_reporting even though credit "
        "repair appears in one credit-reporting label, because this segment is "
        "about complaints AGAINST repair firms -- directly relevant to "
        "astroturfing provenance."
    ),
}

# Segment groupings selected for this project.
SELECTED_SEGMENTS: tuple[str, ...] = (
    "credit_reporting",
    "debt_collection",
    "mortgage",
    "card",
    "student_loan",
    "consumer_loan",
)

# Segments with low plausible exposure to consumer LLM use, usable as a
# comparison series in a difference-in-differences specification.
CONTROL_SEGMENTS: tuple[str, ...] = (
    "mortgage",
    "bank_account",
    "money_transfer",
)

_RAW_TO_SEGMENT: dict[str, str] = {
    raw: seg for seg, raws in SEGMENT_MAP.items() for raw in raws
}


def canonical_segment(raw_product: str | None) -> str:
    """Map a raw CFPB `product` label to a stable canonical segment.

    Unknown labels return 'unmapped:<label>' rather than being silently dropped
    or bucketed into 'other'. A new CFPB rename must surface as a visible
    unmapped value, not vanish into a catch-all.
    """
    if not raw_product:
        return "unmapped:<blank>"
    key = raw_product.strip()
    seg = _RAW_TO_SEGMENT.get(key)
    if seg:
        return seg
    # tolerate case/whitespace drift before giving up
    lowered = key.casefold()
    for raw, seg in _RAW_TO_SEGMENT.items():
        if raw.casefold() == lowered:
            return seg
    return f"unmapped:{key}"


def raw_products_for(segments: Iterable[str]) -> list[str]:
    """All raw `product` labels belonging to the given canonical segments.

    Used to build API `product` filters, since the API filters on raw labels.
    """
    out: list[str] = []
    for seg in segments:
        if seg not in SEGMENT_MAP:
            raise KeyError(
                f"unknown segment {seg!r}; known: {sorted(SEGMENT_MAP)}"
            )
        out.extend(SEGMENT_MAP[seg])
    return out


def unmapped_labels(observed: Iterable[str]) -> list[str]:
    """Observed raw labels that the crosswalk does not cover."""
    return sorted(
        {p for p in observed if p and p.strip() not in _RAW_TO_SEGMENT}
    )
