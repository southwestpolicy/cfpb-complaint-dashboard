# CFPB Complaint Dashboard — setup and operation

A monthly, automated public dashboard: GitHub Actions pulls new complaints,
updates a compact index, publishes a JSON file to GitHub Pages, and a WordPress
plugin renders it on southwestpolicy.com.

```
CFPB API ──▶ update.py ──▶ dashboard_index.sqlite ──▶ emit.py ──▶ dashboard.json
              (monthly,        (~69 MB, carried              (21 KB, public)
               in Actions)      on a GitHub Release)                │
                                                                    ▼
                                                    WordPress plugin fetches,
                                                    caches 12h, renders inline
```

Nothing heavy runs on the web host. The site only ever reads a 21 KB file.

## Why an index instead of the full extract

The research store is ~15 GB — impractical to move through a CI runner monthly.
Almost all of it is unnecessary for a dashboard of aggregates. The one thing
that *cannot* be pre-aggregated is template membership: a text only counts as a
template once it has been used 50+ times, and it can cross that line years after
first appearing, which retroactively changes past months. So the index keeps
per-text, per-month counts — but with narrative bodies dropped and only an
8-byte hash retained, that is 69 MB (26 MB gzipped).

Every table is keyed by **month**, never year, because CFPB back-fills
complaints into past dates. Each run re-reads the trailing months, purges what
it recorded for them, and re-ingests. A year-keyed table would force
re-fetching a whole year to correct one week of backfill.

## One-time setup

### 1. Create the repository

Push this project to a GitHub repo (public is fine and preferable — the
pipeline is then independently auditable, and Actions and Pages are free).

### 2. Seed the state release

The monthly job needs a starting index. Build it once locally from the full
store, then attach it to a release the job reads and writes:

```bash
python dashboard/build_index.py --bootstrap
gzip -c ~/CFPB-Inspect/data/dashboard_index.sqlite > dashboard_index.sqlite.gz
gh release create dashboard-state dashboard_index.sqlite.gz \
  --title "Dashboard state" --notes "Aggregate index carried between monthly runs."
```

If you ever need to rebuild from scratch, re-run those three commands — the
workflow overwrites the asset with `--clobber` each month.

### 3. Enable Pages

Repository **Settings → Pages → Source: GitHub Actions**. Ignore the suggested
starter workflows (Jekyll, Static HTML) — this repository already has its own.

Two workflows, deliberately separate:

| Workflow | Trigger | Does |
|---|---|---|
| `pages.yml` | push to `main` touching `dashboard/public/**`, or manual | Publishes the site. Seconds. |
| `monthly-dashboard.yml` | 3rd of the month, or manual | Refreshes the data and commits the new payload, which triggers `pages.yml`. ~20 min. |

They are split because the refresh needs the state release to exist, so coupling
them meant a fresh repository could never publish anything. This way the site
goes live from committed data immediately, and only one workflow ever deploys to
Pages, so the two cannot race.

Run `pages.yml` first (Actions → Deploy dashboard to Pages → Run workflow) to get
the site up. The feed lands at:

```
https://<org>.github.io/<repo>/data/dashboard.json
```

### 4. Install the WordPress plugin

Zip `wordpress/sppi-cfpb-dashboard/` and upload it under **Plugins → Add New →
Upload**, or copy the folder into `wp-content/plugins/` over cPanel File
Manager or SFTP. Activate it, then set the feed URL under **Settings → CFPB
Dashboard**.

Place the dashboard on any page with:

```
[sppi_cfpb_dashboard]
```

Or show selected panels only:

```
[sppi_cfpb_dashboard panels="headline,trend"]
```

Panels: `headline`, `trend`, `volume`, `states`, `companies`, `relief`.

## Running

The workflow runs on the 3rd of each month at 07:17 UTC and can be triggered
manually from the Actions tab. A typical run pulls ~2.3M complaints across the
trailing four months in roughly 20 minutes.

Locally:

```bash
python dashboard/update.py --dry-run     # size the refresh window
python dashboard/update.py               # refresh the index
python dashboard/emit.py                 # write dashboard.json
python dashboard/check_payload.py        # validate before publishing
python dashboard/build_map.py            # only if the map geometry needs rebuilding
```

Preview the page as the public sees it:

```bash
cd dashboard/public && python -m http.server 8731
```

## The safety net

`check_payload.py` runs before publication and exits non-zero on an implausible
payload — too few complaints, a templated share outside 5–70%, a collapsed
trend, a stale watermark, trailing zeros that indicate months were purged but
not refilled. An unattended job that half-fails still produces well-formed
JSON; without this check that would land silently on a public page. The
workflow stops rather than deploying, and the plugin keeps serving the last
good copy.

The plugin has its own fallback: on a fetch failure it serves the last good
payload from `wp_options` and shows a quiet notice, so the panel degrades to
stale rather than empty.

## Front-end behaviour

**It inherits your theme.** The dashboard sets no font, no text colour and no
background. Rules, surfaces and muted text are derived from the theme's own ink
via `color-mix(... currentColor ...)`, so a dark theme works with no dark-mode
rules at all and a theme with warm or cool ink tints the whole component to
match. Block themes additionally supply `--wp--preset--color--primary`, which
becomes the accent on the headline figures.

The one thing *not* inherited is the data-series colours. A theme palette is
chosen for branding, not for keeping three lines on a chart distinguishable, and
an accent can easily be invisible against its own background. Those are fixed
mid-tones that clear 3:1 on both white and near-black. Override them from your
theme stylesheet if you want:

```css
.sppi-cfpb { --sppi-s1: #123456; --sppi-s2: #a0522d; --sppi-s3: #2f8f74; }
```

**The charts are interactive.** Hovering a line chart draws a crosshair, marks
every series at that month and shows a tooltip with exact values. Touch users
tap. Keyboard users tab to the chart and use arrow keys (shift-arrow jumps a
year, Home/End go to the ends, Escape dismisses); the readout is mirrored into
an `aria-live` region so it is announced, not just drawn.

**The map is a real choropleth.** Fifty states plus DC, composite Albers
equal-area with Alaska and Hawaii inset — equal-area because the quantity mapped
is a rate per resident, and on a Mercator projection the northern states inflate
and the eye reads area as magnitude. Shading is by sextile, so a couple of
extreme states cannot flatten everyone else into one colour. A toggle switches
between complaints per 100,000 residents and templated share. Every state is
hoverable and keyboard-focusable with an `aria-label` carrying its figures, and
the ranked table below the map is the accessible equivalent and the fallback if
the geometry fails to load.

Geometry comes from the US Census Bureau cartographic boundary file
(1:20,000,000) — a public-domain federal work, so there is no third-party map
licence or attribution string to maintain. It is projected and simplified once
by `dashboard/build_map.py` into 56 KB of plain SVG paths and committed; the
browser gets finished paths and needs no mapping library.

## Things worth knowing before you publish

- **Templating measures provenance, not merit.** A templated complaint can
  describe a real error. The page says so in its footer; keep that.
- **The state panel is not a map of coordination.** High-filing states file
  more of both templated and organic complaints (they correlate at 0.92). The
  panel copy is written to head that misreading off.
- **Recent months are withheld from the trend** until enough narratives are
  published to measure them, because narrative publication lags weeks to months.
  Credit-reporting narrative publication collapsed to 0.1–3% in 2026; if that
  persists, the trend line will simply stop advancing, which is honest.
- **Company names are grouped** across corporate variants via
  `cfpb_inspect/companies.py`. Unmapped firms appear under a title-cased form
  of their normalised name; add aliases there if a name looks wrong.

## Cost

Zero. GitHub Actions and Pages are free for public repositories; a private repo
would use roughly 20 minutes of the monthly Actions allowance.
