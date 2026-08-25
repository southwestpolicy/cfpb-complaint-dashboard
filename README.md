# CFPB Complaint Database Inspection

Southwest Public Policy Institute

A tool for pulling the CFPB Consumer Complaint Database and testing two
questions against it:

1. **Astroturfing** — are complaints being filed in coordinated, templated, or
   brokered volume rather than by individual aggrieved consumers?
2. **LLM adoption** — did complaint volume break upward around the point when
   the American public gained access to general-purpose LLMs?

## Quick start

The virtualenv lives outside this shared drive, at `C:\Users\pmbre\CFPB-Inspect\venv`.

```bash
C:/Users/pmbre/CFPB-Inspect/venv/Scripts/python.exe cli.py probe
```

Then, in order:

```bash
C:/Users/pmbre/CFPB-Inspect/venv/Scripts/python.exe cli.py fetch --dry-run
```

```bash
C:/Users/pmbre/CFPB-Inspect/venv/Scripts/python.exe cli.py fetch
```

```bash
C:/Users/pmbre/CFPB-Inspect/venv/Scripts/python.exe cli.py report
```

Or use the wrapper, which finds the interpreter for you:

```bash
./run.ps1 probe
```

## Commands

| command | what it does |
|---|---|
| `probe`  | Check the API, dump the live product taxonomy, size the pull. No download. |
| `fetch`  | Pull complaints into local SQLite. Resumable. `--dry-run` plans windows only. |
| `status` | Store coverage plus the raw-label rename diagnostic. |
| `its`    | Interrupted time series, changepoint detection, placebo distribution. |
| `bursts` | Company and segment volume bursts, channel mix shift, new-entrant flags. |
| `dedupe` | Exact and near-duplicate narrative clusters. |
| `geo`    | Per-capita state rates, anomalies, ZIP concentration. |
| `report` | Writes `out/report.md` plus figures. |

Scope defaults to the six selected segments. Override with a comma-separated
list **before** the subcommand:

```bash
./run.ps1 --segments credit_reporting,debt_collection its
```

## Where things live

| what | where | why |
|---|---|---|
| Code | this folder (G: shared drive) | shared with colleagues |
| Exported results | `out/` | shared |
| SQLite store | `C:\Users\pmbre\CFPB-Inspect\data\` | **local on purpose** |
| Virtualenv | `C:\Users\pmbre\CFPB-Inspect\venv` | **local on purpose** |

The database and venv are deliberately off the shared drive. Google Drive File
Stream re-uploads a file in full on every write, which for a multi-gigabyte
SQLite database means constant re-syncing, and its virtual filesystem can break
SQLite's file locking outright. Override the location with the
`CFPB_INSPECT_HOME` environment variable.

## Verified API behaviour

Probed 2026-08-20 against the live API. These are not documented upstream and
each one shapes the fetcher:

- Base path **requires** its trailing slash. Without it you get the HTML search
  page. `format=json` is not a parameter and 404s — JSON is the default.
- `frm` is hard-capped at **10000**, so JSON paging cannot walk a large result
  set. This is why bulk extraction uses CSV.
- `format=csv` ignores `size` and streams the matching result set **up to
  100,000 rows**. Verified exactly: a 3-day window reporting 15,001 hits
  returned 15,001 CSV rows, and 97,904 rows exported fine while 101,137
  returned HTTP 400. Neither paging (10k) nor one CSV export (100k) can pull an
  arbitrarily large slice, so **every** extraction must be date-windowed.
- Error bodies are **not JSON** — they are bare field names. Over the row cap
  you get the literal string `size`; rate-limited you get `detail`.
- `date_received_max` is **inclusive**.
- Multi-value filters work (`product=A&product=B`), and labels containing commas
  work as single values.
- The edge WAF **rejects spoofed browser User-Agents** but serves an honest
  self-identifying one. Do not "fix" the User-Agent in `config.py` to look like
  Chrome; it breaks the fetcher and misrepresents us to a federal agency.
- HTTP 429 appears under sustained pulling. The client backs off and retries;
  raise `CFPB_INSPECT_THROTTLE` if you see many.

As of the last probe the index holds **17,212,724** complaints, of which
**3,839,782 (22%)** carry a publishable narrative.

## Findings from the first full run (2026-08-20)

Extract: 16,533,564 complaints, Dec 2011 – Aug 2026, matching the API's own
count for this scope exactly. 3,509,494 narratives.

### Astroturfing: confirmed, large, and predating LLMs

**The defensible copy counts come from exact duplicates.** Of 2,313,492
credit-reporting narratives long enough to score, **758,699 (33%) are
byte-identical to at least 49 others**, across 2,104 distinct templates used 50+
times each. Byte-identical grouping cannot chain, so these numbers are solid.
Largest exact groups:

| identical copies | companies | states | span | character |
|---:|---:|---:|---|---|
| 30,896 | 13 | 52 | 2022-04 → 2026-06 | `15 USC 1681 §602` FCRA privacy boilerplate |
| 24,322 | 7 | 55 | 2021-10 → 2026-07 | "avoid future litigation" dispute demand |
| 18,464 | 18 | 47 | 2025-04 → 2026-07 | `1681i`/`1681e(b)` reinvestigation demand |
| 15,068 | 99 | 48 | 2023-06 → 2026-06 | FCRA preamble recitation |
| 14,558 | 3 | 41 | 2022-03 → 2026-05 | "There is no third party involved" |

Near-duplicate clustering (Jaccard ≥ 0.8) links 2,026,636 of 3,263,305
narratives, but **that number must not be read as template membership** — see
the chaining caveat below. Notable template families found this way include
"estoppel by silence" pseudolaw (2025-01 → 2025-06), `15 USC 1666b`
late-payment pseudolaw, FCRA 605B identity-theft block requests, and one that
scripts a declaration *under penalty of perjury* that no third party is
involved.

That last family matters most. CFPB asks filers whether a third party is
submitting on their behalf. A template distributed to thousands of people that
scripts a sworn denial of third-party involvement is itself evidence of
coordination.

#### Chaining caveat on near-duplicate cluster sizes

Clusters are connected components under **single linkage**, so A joins C
whenever some B resembles both — even if A and C do not resemble each other.
Auditing the largest component found pairwise Jaccard between sampled members
ranging **0.36 to 1.00** against a 0.80 threshold: it is a family of
boilerplate variants sharing an opening paragraph, not one document repeated.

The exported CSV therefore reports `chained_size` (never "copies") alongside
`cohesion_mean` and `cohesion_pct_above_threshold`, sampled per cluster. On a
test slice only 2 of 16 clusters were tight (≥80% of members at or above
threshold), so **cohesion must be checked before any cluster is cited.** For an
unimpeachable copy count, use the exact-duplicate groups.

That last one matters most. CFPB asks filers whether a third party is
submitting on their behalf. A template distributed to ten thousand people that
scripts a sworn denial of third-party involvement is itself evidence of
coordination, and it is the strongest single item in the dataset.

**But the trend starts in 2019.** Share of credit-reporting narratives sitting
in a ≥50-copy identical group: 0.4% (2019-01) → 9.7% (2019-10) → 15.9%
(2021-10) → **18.3% (2022-10, before ChatGPT)** → 33.5% (2023-07) → 44.3%
(2024-07) → 49.7% (2025-10). Continuous growth across the LLM window with no
discontinuity at any milestone.

### LLM adoption: not supported

On all 14M credit-reporting complaints, every LLM date returns a "significant"
level shift — +21.8% (p=0.010) at ChatGPT's launch, +24.7% (p=0.009) at GPT-4,
slope-change p-values of 0. **All three fail the placebo test**, landing at the
28th–38th percentile of effects from arbitrary dates: 80–93 of 129 placebo dates
produce an effect at least as large. Reported without the placebo distribution
this would have been a publishable-looking false positive.

Changepoints found blind sit at 2017-05 (+285%, one week after a taxonomy
rename), 2020-04 (+251%, COVID), 2022-05 (+210%, nearer the medical-debt
removal than ChatGPT) and a smooth 12-month ramp through 2024 — none at an LLM
date.

**Caveat that cuts the other way:** exact-duplicate matching is blind to
LLM-assisted drafting, which yields paraphrases rather than copies. If filers
adopted LLMs you would expect exact duplication to *fall*. That near-50% of
2025 narratives are still literal copies suggests bulk filing remains
copy-paste, but it does not rule out an LLM contribution.

### Channel: the surge is web-only

Around ChatGPT's launch, web complaints rose **+135.9%** while phone rose
**+7.9%**, postal +62.7%, and referral fell 53.8%; web share went 95.1% → 98.0%.
A broad rise in genuine consumer harm should lift non-web channels too. This
constrains interpretation without settling it, since ordinary channel migration
looks the same.

### Narrative coverage collapse — read before citing any text result

Credit-reporting narrative coverage falls from ~25% to **0.1–3% from 2026-01**,
while mortgage holds 28–46% in the same months. It is therefore not ordinary
publication lag. **Text analysis has effectively zero coverage of 2026**, so any
2026 template share rests on a few hundred narratives against ~500k
complaints/month and must not be cited. `cli.py status` prints this per month.

## Four traps this tool is built around

**1. Product labels have been renamed twice, and the second is inside the LLM
window.** Measured on the full extract:

| raw label | complaints | active |
|---|---:|---|
| `Credit reporting` | 140,426 | 2012-10-22 → 2017-04-22 |
| `Credit reporting, credit repair services, or other personal consumer reports` | 2,163,770 | 2017-04-24 → 2023-08-25 |
| `Credit reporting or other personal consumer reports` | 11,696,281 | 2023-08-24 → present |

Grouped on the raw label, a 2.16M-complaint series collapses to zero on
2023-08-25 while an 11.7M one appears from nothing — nine months after
ChatGPT's launch. The renames are provably administrative: `credit_reporting`,
`card` and `consumer_loan` all switch on the *same two dates*, 2017-04-24 and
2023-08-24. Everything groups on `canonical_segment`; see `taxonomy.py`.

**Caveat — the crosswalk only fixes half of this.** It removes the break caused
by the label changing; it cannot remove a change in what the category *covers*.
The 2017 rename genuinely broadened scope (adding credit-repair services and
other consumer reports), and the detector duly finds a **+285% break at
2017-05-01**, one week later. Treat breaks at 2017-05 and 2023-08/09 as
taxonomy-driven until shown otherwise, and do not read cross-rename
credit_reporting levels as like-for-like.

**2. The series grew steeply long before LLMs existed.** A segmented regression
on a series like this reports a large significant "level shift" at almost any
date, because the break term absorbs ordinary curvature. Every intervention
estimate ships with a **placebo distribution** — the same model refit at many
irrelevant dates. On the student-loan test extract, all three LLM dates landed
in the *bottom* 11% of placebo effects: no effect, despite respectable-looking
slope p-values.

**3. Narratives are PII-redacted, which fakes textual similarity.** Names and
dates become runs of `X`, so unrelated complaints share tokens. Redaction runs
are collapsed and dropped, and every cluster reports its redaction ratio.

**4. Policy shocks masquerade as LLM effects.** `config.CONFOUNDING_EVENTS`
registers known events per segment, and detected changepoints are automatically
checked against it. This is not decoration: the student-loan test extract shows
a `+214%` break at 2023-06-01, 79 days from GPT-4's release — and 29 days from
the Supreme Court striking down loan forgiveness. **Verify every date in that
registry against a primary source before publishing, and treat an empty entry
as "not yet researched" rather than "no confound exists."**

## Company names and corporate events

`cfpb_inspect/companies.py` folds name variants (`EQUIFAX, INC.`,
`Equifax Information Services LLC`) onto one corporate group, because burst
detection is per-company and variant spellings otherwise split one firm into
fragments with artificially low baselines. Folding is case/punctuation/legal-
suffix only, plus an explicit alias map for genuine renames and acquisitions.
There is deliberately **no fuzzy matching** — wrongly merging two distinct
respondents is far more damaging here than missing a merge. Unmapped names fall
back to their normalized form rather than an `other` bucket. Use
`--raw-companies` to disable folding.

The same file registers **corporate events** — servicer transfers, enforcement
actions — that move complaint volume with no change in consumer behaviour, and
every detected burst is annotated with any event nearby. This is not
decoration. On the student-loan extract it explained the four largest bursts in
the data:

| entity | month | multiple of baseline | actual cause |
|---|---|---:|---|
| EdFinancial | 2022-09 | 70× | FedLoan/PHEAA portfolio transfer |
| Navient | 2017-01 | 17.7× | CFPB enforcement suit, 3 days earlier |
| MOHELA | 2022-10 | 26.6× | FedLoan/PHEAA portfolio transfer |
| Navient | 2024-09 | 6.5× | CFPB ban + $120M order, 3 days earlier |

Without that registry, those four are the most dramatic "astroturfing signals"
in the dataset. Coverage is currently strongest for student-loan servicers,
because that is where testing exposed the problem. **Mortgage servicing
transfers, card portfolio sales and debt-buyer acquisitions move comparable
volume and are not yet catalogued.**

## What a duplicate cluster does and does not prove

A cluster of near-identical narratives is a **template signature**, not proof of
fabrication. Consumers copy template letters from credit-repair firms, advocacy
groups and forums; a credit-repair mill filing for many real clients with real
disputes leaves the same trace as an invented campaign; and neither is separable
from LLM-assisted drafting on text alone. What discriminates is the metadata
reported per cluster — how many distinct companies, states and days it spans.

The student-loan test extract makes the distinction concrete: one 42-complaint
cluster contains the unfilled template placeholder `insert your school here`,
which is direct evidence of templated filing. That is a real finding about
provenance. It is still not evidence that the underlying grievances are false.

## Method summary

- **Counts model**: negative binomial. Complaint counts are overdispersed;
  Poisson and OLS understate standard errors and manufacture significance.
- **Changepoints**: binary segmentation on log counts (growth is
  multiplicative), run *without* reference to the LLM dates.
- **Bursts**: robust z against a **trailing** 12-month median/MAD. A
  whole-series baseline would score every recent month as extreme, purely
  because of growth.
- **Per-capita rates**: Census Bureau state population for the year the
  complaint was received, not one current figure for all years. Regenerate with
  `python -m cfpb_inspect.reference.build_population`.
- **Anomaly scoring**: median/MAD rather than mean/SD throughout, so a few
  genuinely extreme states cannot inflate the scale and hide everything else.

## Known limitations

- `submitted_via` is the only provenance field available, and 96% of complaints
  are "Web". A rise concentrated in web filings is equally consistent with bulk
  automated filing and with ordinary channel migration.
- Only 22% of complaints have narratives, and publication requires consumer
  consent. Narrative-based conclusions describe the consenting subset, which is
  not a random sample.
- ZIP codes are truncated to three digits, so geographic concentration is
  regional, not neighbourhood-level.
- CFPB back-fills recent dates for weeks. `fetch` re-pulls the last 60 days
  every run for this reason; the most recent month is still likely undercounted
  and is dropped from monthly series.
- Territories and military ZIPs have no Census state denominator and are
  excluded from per-capita analysis (reported, not silent).
