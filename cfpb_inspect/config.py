"""Central configuration: paths, HTTP identity, analysis dates.

Data and the SQLite store live on LOCAL disk, not on the G: shared drive.
Google Drive File Stream re-uploads a database file in full on every write and
can break SQLite's file locking, so the store stays local and only exported
results are written back to the shared project folder.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- paths -----------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
"""The shared-drive project folder (code + exported results)."""

LOCAL_ROOT = Path(os.environ.get("CFPB_INSPECT_HOME", Path.home() / "CFPB-Inspect"))
"""Local working root. Override with the CFPB_INSPECT_HOME env var."""

DATA_DIR = LOCAL_ROOT / "data"
CACHE_DIR = LOCAL_ROOT / "cache"
DB_PATH = DATA_DIR / "complaints.sqlite"
OUT_DIR = PROJECT_DIR / "out"

for _d in (DATA_DIR, CACHE_DIR, OUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- HTTP identity ---------------------------------------------------------

API_ROOT = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"

# A role address, not a personal one: this string is sent in the User-Agent
# of every API request and the source is public.
CONTACT = os.environ.get("CFPB_INSPECT_CONTACT", "info@southwestpolicy.com")

USER_AGENT = (
    f"SPPI-CFPB-Research/0.1 (Southwest Public Policy Institute; {CONTACT})"
)
"""Honest self-identifying User-Agent.

This is not cosmetic. The consumerfinance.gov edge (Akamai) returns 403 for a
spoofed browser User-Agent sent from a non-browser TLS stack, but serves 200 to
a descriptive research agent. Verified empirically 2026-08-20. Do not replace
this with a fake Chrome string -- it breaks the fetcher AND misrepresents us to
a federal agency whose data we are publishing on.
"""

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.consumerfinance.gov/data-research/consumer-complaints/search/",
}

# --- API limits (empirically verified 2026-08-20) --------------------------

MAX_SIZE = 10_000
"""Largest accepted `size` for JSON responses."""

MAX_FRM = 10_000
"""Hard cap on `frm`; the API 400s above this. JSON paging therefore cannot
reach beyond ~10k records per query, which is why bulk extraction uses
`format=csv`."""

MAX_CSV_ROWS = 100_000
"""Row cap on the CSV export, measured empirically 2026-08-20.

`format=csv` streams the full matching result set, but only up to this many
rows. Above it the API returns HTTP 400 with the bare body `size`. Bracketed
precisely: a window matching 97,904 rows exported fine; 101,137 failed.

Together with MAX_FRM this is the binding constraint on extraction -- neither
JSON paging (10k) nor a single CSV export (100k) can retrieve an arbitrarily
large slice, so every pull must be windowed by date."""

REQUEST_TIMEOUT = 900
THROTTLE_SECONDS = float(os.environ.get("CFPB_INSPECT_THROTTLE", "1.5"))
MAX_RETRIES = 5

# --- analysis dates --------------------------------------------------------

DB_START = "2011-12-01"
"""First date_received present in the public database."""

LLM_EVENTS = {
    "chatgpt_public_launch": "2022-11-30",
    "gpt4_release": "2023-03-14",
    "chatgpt_mass_adoption": "2023-01-31",
}
"""Candidate intervention dates for interrupted time-series analysis.

These are *hypotheses to test*, not assumptions. The changepoint detector runs
without reference to them; agreement between a detected break and one of these
dates is evidence, whereas a break only at a date we pre-selected is not.
"""

CONFOUNDING_EVENTS: dict[str, list[tuple[str, str, str]]] = {
    "student_loan": [
        ("2020-03-13", "CARES Act payment pause and interest waiver begin "
                       "(retroactive to this date)",
         "https://www.congress.gov/crs-product/IF12136"),
        ("2021-10-20", "Navient federal servicing contract taken over by "
                       "Maximus/Aidvantage",
         "https://www.forbes.com/advisor/student-loans/"
         "navient-transfers-servicing-of-student-loan-portfolio/"),
        ("2022-06-27", "FedLoan/PHEAA exits servicing; 8.5M loans transfer to "
                       "MOHELA, Nelnet, EdFinancial and Navient through 2022",
         "https://www.cnn.com/2022/06/27/politics/"
         "fedloan-mohela-new-student-loan-servicer/index.html"),
        ("2022-08-24", "Biden administration announces broad loan forgiveness",
         "https://en.wikipedia.org/wiki/Biden_v._Nebraska"),
        ("2023-06-30", "Supreme Court decides Biden v. Nebraska, striking down "
                       "the forgiveness program",
         "https://www.scotusblog.com/2023/06/"
         "supreme-court-strikes-down-biden-student-loan-forgiveness-program/"),
        ("2023-09-01", "interest resumes on federal student loans",
         "https://ncua.gov/regulation-supervision/"
         "letters-credit-unions-other-guidance/"
         "resumption-federal-student-loan-payments"),
        ("2023-10-01", "federal student loan payments resume; 12-month "
                       "credit-reporting on-ramp begins",
         "https://oag.dc.gov/release/"
         "consumer-alert-payments-federal-student-loans-will"),
        ("2024-09-30", "on-ramp ends; delinquencies again reported to credit "
                       "bureaus",
         "https://oag.dc.gov/release/"
         "consumer-alert-payments-federal-student-loans-will"),
        ("2024-10-21", "MOHELA takes over Navient's remaining portfolio",
         "https://www.acainternational.org/news/"
         "navient-announces-transfer-of-student-loan-servicing-to-mohela/"),
    ],
    "credit_reporting": [
        ("2022-07-01", "big three remove paid medical collections; unpaid "
                       "medical debt reporting delayed from 6 months to 1 year",
         "https://www.consumerfinance.gov/about-us/blog/"
         "medical-debt-anything-already-paid-or-under-500-should-no-longer-"
         "be-on-your-credit-report/"),
        ("2023-04-11", "big three remove medical collections under $500, "
                       "roughly 70% of medical collection tradelines",
         "https://www.cdiaonline.org/cdia-statements/2023/04/11/"
         "national-credit-bureaus-remove-medical-collection-debt-under-500-"
         "from-u-s-credit-reports/"),
    ],
    "debt_collection": [
        ("2021-11-30", "CFPB Regulation F debt collection rule takes effect",
         "https://www.consumerfinance.gov/about-us/newsroom/"
         "cfpb-confirms-effective-date-for-debt-collection-final-rules/"),
    ],
    "mortgage": [
        ("2020-03-27", "CARES Act mortgage forbearance provisions enacted",
         "https://www.congress.gov/crs-product/R46314"),
    ],
    "card": [],
    "consumer_loan": [],
    "bank_account": [],
    "money_transfer": [],
    "debt_relief": [],
    "other_financial_service": [],
}
"""Known policy and market shocks that compete with the LLM hypothesis.

Entries are (date, description, source_url). Dates below were verified against
the cited sources on 2026-08-20.

These exist so that a detected structural break is automatically checked against
the obvious alternative explanation before anyone attributes it to LLM adoption.
The student-loan entries matter most, and are not hypothetical: on a test
extract the tool found a +214% break at 2023-06, which is 79 days from GPT-4's
release and 29 days from Biden v. Nebraska.

An EMPTY list means 'nobody has researched this segment yet', NOT 'no confounds
exist'. Segments with the largest complaint volumes -- credit_reporting above
all -- deserve considerably more entries than they currently have. Re-verify any
date before it appears in a published claim.
"""
