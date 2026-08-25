# Changelog

## 1.2.0

- The companies table gains a templated-share column. It is the share of that
  company's *scored narratives*, not of all its complaints — the two differ by
  more than an order of magnitude, because most complaints carry no published
  narrative at all. The column appears only when the payload supplies it, so an
  older feed is unaffected. Needs `text_company_month`, added to the index in
  this release; see `dashboard/README.md`.
- Year labels on the time-series charts are placed on calendar-year boundaries
  instead of every Nth data point. The old scheme also forced a label onto the
  final point, so the last gap was a different width from all the others and the
  trend chart printed "2026" twice.
- Fixed the dashed line that hung in the margin whenever the pointer was away
  from a chart. The crosshair was parked off to the left rather than hidden, and
  the SVG needs `overflow: visible` for its tooltip, so it stayed painted.
- Charts now fit the width they are given instead of holding a minimum and
  scrolling. The renderer picks a squarer viewBox with tighter padding at narrow
  widths, so a phone gets a 215px-tall chart with 12.5px labels where before it
  got a 112px one, 3.4px labels, and a scrollbar on both axes. Crossing a
  breakpoint redraws, so rotating a phone re-proportions the charts.

  The scrollbar on the *vertical* axis came from the same rule as the horizontal
  one: `overflow-x` on its own forces the computed `overflow-y` to `auto`, and
  the off-canvas crosshair above was the overflowing content.

## 1.1.1

- Removed the two-letter abbreviations painted on the map. At the width the map
  is drawn they rendered around 9px — too small to read, but big enough to break
  up the shading underneath — and the north-east was crowded enough that nine
  states had to be suppressed by hand. States remain hoverable and
  keyboard-focusable with their figures in an `aria-label`, and the ranked table
  below the map is unchanged.

  This shipped as a second 1.1.0 build before it had a version of its own, which
  meant two different packages claimed the same version and WordPress had no way
  to tell them apart. Hence 1.1.1.

## 1.1.0

- Panel titles and notes now take the theme's own heading and paragraph styles.
  Previously the plugin sized everything in compounding `em` units, which
  multiplied down the tree and produced sizes like 12.99px and 15.84px that
  matched nothing else on the page.
- Tables inherit the theme's table styling instead of overriding its size, so
  they match every other table on the site.
- New `align` attribute. Charts, the map and tables take the theme's wide
  measure by default (`align="wide"`); `full` spans the viewport and `none`
  keeps everything in the text column. Prose stays at the site's reading width
  whichever is chosen.
- New `heading` attribute, defaulting to `h2` so panel titles continue the page
  outline under the page title instead of skipping a level.
- Removed the proportional bars drawn behind figures in table cells. They
  repeated what the number already said and shifted as the column resized.
- Chart text is now sized against the rendered width, so axis labels stay at a
  readable size instead of shrinking with the viewBox — they were 8.9px in a
  580px column and would have been 18px in a wide one.
- Chart gridlines pick round values, so an axis reads 0/10/20/30% rather than
  0/12.5/25/37.5%.
- Charts hold a workable width on phones and scroll sideways within their frame
  rather than compressing a ten-year series into 112px of height.
- The failure and stale-data notices now set `DONOTCACHEPAGE`, so a few seconds
  of upstream trouble cannot be frozen into the page cache and served to every
  anonymous visitor until something else clears it.
- The plugin can update itself from the published manifest. See "Updating the
  plugin" in `dashboard/README.md`.

## 1.0.1

- First published version.
