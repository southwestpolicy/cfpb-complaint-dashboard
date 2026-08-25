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

### Shortcode attributes

| Attribute | Default | Does |
|---|---|---|
| `panels` | all six | Which panels to show, in order: `headline`, `trend`, `volume`, `states`, `companies`, `relief`. |
| `align` | `wide` | `wide` gives charts, the map and tables the theme's wide measure; `full` spans the viewport; `none` keeps everything in the text column. Prose stays at the site's reading width whichever is chosen. |
| `heading` | `h2` | Heading level for panel titles. `h2` continues the outline under a page title; use `h3` if the dashboard sits under a heading of its own, or if your theme's `h2` is larger than you want repeated five times. |

```
[sppi_cfpb_dashboard panels="headline,trend" align="wide" heading="h3"]
```

## Updating the plugin

The plugin is not on wordpress.org, so nothing would ordinarily tell WordPress
that a newer version exists. It uses the mechanism core added in 5.8 for exactly
this case: the `Update URI` header in the plugin file names a host, WordPress
hands that host its own `update_plugins_{host}` filter, and whatever the filter
returns is treated as the authoritative update record. The notice on the Plugins
screen, the update count in the admin menu, one-click update and auto-updates
are then all core's own — the plugin contains no code that unpacks or installs
anything.

What the plugin asks that host for is one small JSON file:

```
https://<org>.github.io/<repo>/plugin/update.json
```

`dashboard/build_plugin_release.py` writes it, next to a zip of the plugin, and
the Pages workflow runs that script on every deploy. So **releasing a new
version is:**

1. Edit the plugin. Change **both** `Version:` in the file header and the
   `SPPI_CFPB_VERSION` constant below it — the build refuses to package a
   mismatch, because WordPress reads one and the plugin's own code reads the
   other, and a disagreement is invisible until an update half-applies.
2. Add a line to `wordpress/CHANGELOG.md`; it becomes the changelog in the
   "View details" modal.
3. Push to `main`. `pages.yml` packages the plugin, writes the manifest and
   publishes both.

Every site running the plugin then offers the update the next time WordPress
checks, which is roughly twice a day. To see it immediately, go to
**Settings → CFPB Dashboard** and press **Check for updates now**, then update
from the Plugins screen as normal.

Two safeguards worth knowing about. The package has to be served from the same
host as the manifest, so anything able to tamper with the JSON still cannot
point WordPress at an arbitrary zip. And the plugin only ever offers a move
forwards: publishing a lower version number does not trigger a downgrade, so a
bad release is rolled back by publishing a *higher* version containing the older
code, not by reverting the number.

To check what would be packaged without writing anything:

```bash
python dashboard/build_plugin_release.py --check
```

## The templated share in the companies panel

That column needs `text_company_month` — per-company, per-hash, per-month
narrative counts. It cannot be precomputed as a boolean at ingest time, because
whether a text counts as a template depends on its running total across the whole
corpus and it can cross the threshold years after first appearing.

The table was added after the index was first built, and the monthly job only
re-reads its trailing refresh window, so the months the panel reports on would
otherwise stay empty for a year. Two ways to populate it:

```bash
# Narrow and additive: writes only the new table, from the local store.
python dashboard/backfill_company_text.py --months 18

# Correct and complete: re-keys and rebuilds every table. Takes about an hour.
python dashboard/build_index.py --bootstrap
```

**Prefer the bootstrap if the company aliases in `cfpb_inspect/companies.py`
have changed since the index was built.** Company keys are only consistent
across tables if every table was written by the same version of that module. An
index whose `company_month` predates an alias holds the old key — `LEXISNEXIS`
where the current grouping yields `LexisNexis` — and the two never join, so
those firms show a dash in the new column. The same drift is why a stale index
displays names like "Resurgent Capital Services L P" instead of the grouped
form. Only a full rebuild re-keys everything at once; the emitter deliberately
does not match loosely, because a near-miss would attribute one firm's
narratives to another.

A company also shows a dash when it has fewer than 200 scored narratives in the
window, the same floor the state panel uses, or when it falls outside the
`COMPANY_DETAIL_TOP` firms the index keeps text detail for.

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

Type is inherited rather than approximated. The stylesheet sets no font-family
and no font-size on anything that is a paragraph or a heading: a `<p>` in the
dashboard is styled by your theme's paragraph rule and a panel title by its
heading rule, exactly as if they had been typed into the editor. The only text
the plugin sizes is chrome with no editorial equivalent — axis labels, the
legend, the map key, tooltips and the caption under a headline figure.

**Width comes from the theme's own vocabulary.** The wrapper carries
`alignwide` (or `alignfull`, or neither) rather than a hard-coded pixel width,
so charts, the map and tables get whatever wide measure the active theme
defines — 120rem in Twenty Twenty, something else elsewhere — while prose stays
at `--sppi-measure`, the site's reading width. Nothing breaks out of the content
column with negative margins. If your theme's content measure is not 58rem:

```css
.sppi-cfpb { --sppi-measure: 46rem; --sppi-map-max: 70rem; }
```

**Chart text is sized against the rendered width, not the viewBox.** Text inside
an SVG scales with the element, so a fixed label size means one thing in a
580px column and another in a 1200px one. The renderer measures the drawn width
and sets a font size that lands at roughly 12.5px on screen either way, and
re-does it through a `ResizeObserver` when the column changes.

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
