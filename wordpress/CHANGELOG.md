# Changelog

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
- Removed the two-letter abbreviations painted on the map. At the width the map
  is drawn they rendered around 9px — too small to read, but big enough to break
  up the shading underneath — and the north-east was crowded enough that nine
  states had to be suppressed by hand. States remain hoverable and
  keyboard-focusable with their figures in an `aria-label`, and the ranked table
  below the map is unchanged.
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
