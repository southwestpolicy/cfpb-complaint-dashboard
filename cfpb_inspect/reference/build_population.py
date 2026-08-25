"""Build the state population reference table from Census Bureau sources.

Run this to regenerate cfpb_inspect/reference/state_population.csv:

    python -m cfpb_inspect.reference.build_population

Sources (both keyless bulk CSVs; the Census *API* now requires a key):
  2010-2020  https://www2.census.gov/programs-surveys/popest/datasets/
             2010-2020/state/totals/nst-est2020.csv
  2020-2024  https://www2.census.gov/programs-surveys/popest/datasets/
             2020-2024/state/totals/NST-EST2024-ALLDATA.csv

Population is stored per state per YEAR, not as a single current figure,
because complaint rates are computed against the population of the year the
complaint was received. Using one recent population for the whole 2011-2025
span would misstate per-capita rates for fast-growing and shrinking states in
opposite directions.
"""
from __future__ import annotations

import csv
import io
import urllib.request
from pathlib import Path

OUT_PATH = Path(__file__).with_name("state_population.csv")

VINTAGE_2010 = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2010-2020/state/totals/nst-est2020.csv"
)
VINTAGE_2020 = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2024/state/totals/NST-EST2024-ALLDATA.csv"
)

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT",
    "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL",
    "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY",
    "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}

HEADERS = {"User-Agent": "SPPI-CFPB-Research/0.1"}


def _fetch_csv(url: str) -> list[dict[str, str]]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def build() -> Path:
    records: dict[tuple[str, int], int] = {}

    for url in (VINTAGE_2010, VINTAGE_2020):
        for row in _fetch_csv(url):
            # SUMLEV 040 = state-level rows; skip nation and region totals.
            if row.get("SUMLEV") != "040":
                continue
            abbr = STATE_ABBR.get(row["NAME"].strip())
            if not abbr:
                continue
            for key, value in row.items():
                if not key.startswith("POPESTIMATE"):
                    continue
                suffix = key[len("POPESTIMATE"):]
                if not suffix.isdigit() or len(suffix) != 4:
                    continue  # skips POPESTIMATE042020 (April-2020 base)
                year = int(suffix)
                if value and value.strip().isdigit():
                    # Later vintage wins for overlapping years (2020), since it
                    # incorporates the revised post-census base.
                    records[(abbr, year)] = int(value)

    rows = sorted(records.items())
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "year", "population"])
        for (abbr, year), pop in rows:
            writer.writerow([abbr, year, pop])

    states = len({a for a, _ in records})
    years = sorted({y for _, y in records})
    print(
        f"wrote {OUT_PATH} :: {len(rows)} rows, {states} states, "
        f"years {years[0]}-{years[-1]}"
    )
    return OUT_PATH


if __name__ == "__main__":
    build()
