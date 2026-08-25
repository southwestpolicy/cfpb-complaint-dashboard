"""Company name normalization and corporate-history tracking.

WHY
CFPB publishes the company name as the filer supplied or as the entity is
registered, so one firm appears as several strings: ``EQUIFAX, INC.``,
``Equifax Information Services LLC``, ``Navient Solutions, LLC.`` with a
trailing period. Burst detection is per-company, so name variants split a single
entity's series into fragments, each with its own artificially low baseline --
which both hides real bursts and invents fake ones when volume migrates between
spellings.

Normalization here is deliberately conservative. It folds case, punctuation and
legal suffixes, which is safe and reversible. It does NOT do fuzzy matching:
collapsing ``First National Bank of X`` into ``First National Bank of Y``
because they look similar would silently merge distinct respondents, and a wrong
merge is far more damaging to this analysis than a missed one.

CORPORATE EVENTS ARE CONFOUNDS TOO
A servicer transfer moves millions of accounts between companies in weeks. The
receiving company's complaint volume jumps by orders of magnitude with no change
whatsoever in consumer behaviour or filing authenticity. On a test extract of
student loans, the two largest company bursts found were EdFinancial in
2022-09 (455 complaints against a baseline of 6.5) and MOHELA in 2022-10 --
both squarely inside the FedLoan/PHEAA portfolio transfer. Without this
registry, those read as the most dramatic astroturfing signals in the data.

Note this module is applied at ANALYSIS time, not at insert time, so the
normalization rules can be revised without re-fetching 16 million rows.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Legal-form suffixes stripped from the end of a name, repeatedly.
_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L L C", "LLP", "LP", "PLC", "PC", "PA",
    "CORP", "CORPORATION", "CO", "COMPANY", "NA", "N A", "FSB", "FA", "SB",
    "SSB", "LTD", "LIMITED", "SA", "AG", "NV", "TRUST", "BANK NA",
}

_PUNCT_RE = re.compile(r"[.,;:'\"()\[\]/\\]+")
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=200_000)
def normalize_company(name: str | None) -> str:
    """Fold case, punctuation and legal suffixes to a comparison key.

    ``EQUIFAX, INC.`` and ``Equifax Inc`` both become ``EQUIFAX``.
    """
    if not name:
        return ""
    text = _PUNCT_RE.sub(" ", str(name).upper())
    text = text.replace("&", " AND ")
    text = _WS_RE.sub(" ", text).strip()
    if text.startswith("THE "):
        text = text[4:]

    # Strip trailing legal forms until none remain (handles "X Corp Inc").
    changed = True
    while changed and text:
        changed = False
        for suffix in _SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
    return text


# Normalized key -> corporate group. Maps genuine renames, acquisitions and
# operating brands onto one entity. Verified entries carry a source in
# CORPORATE_EVENTS below; entries without one are analyst judgement and should
# be checked before appearing in a published claim.
_GROUP_ALIASES: dict[str, str] = {
    # Credit bureaus and other nationwide specialty reporting agencies
    "LEXISNEXIS": "LexisNexis",
    "LEXISNEXIS RISK SOLUTIONS": "LexisNexis",
    "RESURGENT CAPITAL SERVICES L P": "Resurgent Capital Services",
    "RESURGENT CAPITAL SERVICES": "Resurgent Capital Services",
    "CBC COMPANIES": "CBC Companies",
    "EQUIFAX": "Equifax",
    "EQUIFAX INFORMATION SERVICES": "Equifax",
    "EXPERIAN": "Experian",
    "EXPERIAN INFORMATION SOLUTIONS": "Experian",
    "TRANSUNION": "TransUnion",
    "TRANS UNION": "TransUnion",
    "TRANSUNION INTERMEDIATE HOLDINGS": "TransUnion",
    # Student loan servicers
    "NAVIENT SOLUTIONS": "Navient",
    "NAVIENT": "Navient",
    "SALLIE MAE": "Sallie Mae",
    "SLM": "Sallie Mae",
    "AIDVANTAGE": "Maximus/Aidvantage",
    "MAXIMUS FEDERAL SERVICES": "Maximus/Aidvantage",
    "MOHELA": "MOHELA",
    "MISSOURI HIGHER EDUCATION LOAN AUTHORITY": "MOHELA",
    "NELNET": "Nelnet",
    "GREAT LAKES EDUCATIONAL LOAN SERVICES": "Nelnet",
    "FEDLOAN SERVICING": "PHEAA/FedLoan",
    "PHEAA": "PHEAA/FedLoan",
    "AES PHEAA": "PHEAA/FedLoan",
    "AES": "PHEAA/FedLoan",
    "AMERICAN EDUCATION SERVICES": "PHEAA/FedLoan",
    "PENNSYLVANIA HIGHER EDUCATION ASSISTANCE AGENCY": "PHEAA/FedLoan",
    "EDFINANCIAL SERVICES": "EdFinancial",
    # Mortgage servicers
    "NATIONSTAR MORTGAGE": "Mr. Cooper",
    "MR COOPER": "Mr. Cooper",
    "MR COOPER GROUP": "Mr. Cooper",
    "OCWEN LOAN SERVICING": "Ocwen/PHH",
    "OCWEN FINANCIAL": "Ocwen/PHH",
    "PHH MORTGAGE": "Ocwen/PHH",
    # Debt buyers
    "PORTFOLIO RECOVERY ASSOCIATES": "PRA Group",
    "PRA GROUP": "PRA Group",
    "MIDLAND CREDIT MANAGEMENT": "Encore Capital",
    "MIDLAND FUNDING": "Encore Capital",
    "ENCORE CAPITAL GROUP": "Encore Capital",
    # Large banks and card issuers
    "JPMORGAN CHASE AND": "JPMorgan Chase",
    "JPMORGAN CHASE": "JPMorgan Chase",
    "CHASE": "JPMorgan Chase",
    "BANK OF AMERICA": "Bank of America",
    "WELLS FARGO AND": "Wells Fargo",
    "WELLS FARGO": "Wells Fargo",
    "CITIBANK": "Citigroup",
    "CITIGROUP": "Citigroup",
    "CAPITAL ONE": "Capital One",
    "CAPITAL ONE FINANCIAL": "Capital One",
    "SYNCHRONY": "Synchrony",
    "SYNCHRONY BANK": "Synchrony",
    "SYNCHRONY FINANCIAL": "Synchrony",
    "EQUIFAX INFORMATION SERVICES LL": "Equifax",  # observed truncation
}


def company_group(name: str | None) -> str:
    """Corporate group for a company name, falling back to the normalized key.

    Falling back rather than returning 'other' keeps unmapped companies as
    distinct analyzable entities instead of merging thousands of unrelated
    firms into one meaningless bucket.
    """
    key = normalize_company(name)
    return _GROUP_ALIASES.get(key, key)


# Corporate group -> (date, description, source_url).
# Dates verified 2026-08-20 against the cited sources.
CORPORATE_EVENTS: dict[str, list[tuple[str, str, str]]] = {
    "Maximus/Aidvantage": [
        ("2021-10-20",
         "takes over Navient's federal servicing contract (2.7M borrowers)",
         "https://www.forbes.com/advisor/student-loans/"
         "navient-transfers-servicing-of-student-loan-portfolio/"),
    ],
    "Navient": [
        ("2017-01-18",
         "CFPB sues Navient for failing borrowers at every stage of repayment",
         "https://www.consumerfinance.gov/archive/newsroom/"
         "cfpb-sues-nations-largest-student-loan-company-navient-failing-"
         "borrowers-every-stage-repayment/"),
        ("2021-12-31", "stops servicing Direct Loans for the Dept of Education",
         "https://www.forbes.com/advisor/student-loans/"
         "navient-transfers-servicing-of-student-loan-portfolio/"),
        ("2024-09-12",
         "CFPB bans Navient from federal student loan servicing and orders "
         "$120M in penalties and redress",
         "https://www.consumerfinance.gov/archive/newsroom/"
         "cfpb-bans-navient-from-federal-student-loan-servicing-and-orders-"
         "the-company-to-pay-120-million-for-wide-ranging-student-lending-"
         "failures/"),
        ("2024-10-21", "remaining portfolio transfers to MOHELA",
         "https://www.acainternational.org/news/"
         "navient-announces-transfer-of-student-loan-servicing-to-mohela/"),
    ],
    "PHEAA/FedLoan": [
        ("2022-06-27",
         "exits federal servicing; 8.5M loans transfer out through 2022",
         "https://www.cnn.com/2022/06/27/politics/"
         "fedloan-mohela-new-student-loan-servicer/index.html"),
    ],
    "MOHELA": [
        ("2022-06-27", "receives FedLoan/PHEAA transfer volume",
         "https://www.cnn.com/2022/06/27/politics/"
         "fedloan-mohela-new-student-loan-servicer/index.html"),
        ("2024-10-21", "receives Navient's remaining portfolio",
         "https://www.acainternational.org/news/"
         "navient-announces-transfer-of-student-loan-servicing-to-mohela/"),
    ],
    "EdFinancial": [
        ("2022-06-27", "receives FedLoan/PHEAA transfer volume",
         "https://www.cnn.com/2022/06/27/politics/"
         "fedloan-mohela-new-student-loan-servicer/index.html"),
    ],
    "Nelnet": [
        ("2022-06-27", "receives FedLoan/PHEAA transfer volume",
         "https://www.cnn.com/2022/06/27/politics/"
         "fedloan-mohela-new-student-loan-servicer/index.html"),
    ],
}
"""Corporate events that move complaint volume without any behavioural change.

Coverage is currently strongest for student loan servicers, because that is
where the test extract exposed the problem. Mortgage servicing transfers, card
portfolio sales and debt-buyer acquisitions move comparable volume and are NOT
yet catalogued here. An absent entry means unresearched, not benign.
"""


def competing_corporate_event(
    group: str, month: str, within_days: int = 120
) -> list[tuple[int, str, str, str]]:
    """Corporate events near a burst month, closest first.

    ``month`` is 'YYYY-MM'. Returns (gap_days, date, description, source_url).
    """
    import pandas as pd

    events = CORPORATE_EVENTS.get(group, [])
    if not events:
        return []
    # Compare against mid-month, so a transfer at either end of the month is
    # not spuriously distant.
    ref = pd.Timestamp(month + "-15")
    hits = []
    for when, desc, url in events:
        gap = abs((ref - pd.Timestamp(when)).days)
        if gap <= within_days:
            hits.append((gap, when, desc, url))
    return sorted(hits)
