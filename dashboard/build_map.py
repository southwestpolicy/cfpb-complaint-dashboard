"""Generate SVG paths for a US choropleth, once, at build time.

    python dashboard/build_map.py

Source: US Census Bureau cartographic boundary file (1:20,000,000), which is a
public-domain federal work -- no attribution requirement and no third-party
licence to track.

The projection and simplification happen here rather than in the browser so the
page needs no mapping library, no TopoJSON decoder and no runtime geometry: it
receives finished path strings and colours them.

Projection is a composite Albers equal-area, the conventional choice for a US
choropleth. Equal-area matters here because the quantity mapped is a rate per
resident; on a Mercator projection the northern states are inflated and the eye
reads area as magnitude. Alaska is scaled to 0.35 and Alaska and Hawaii are
moved beneath the southwest, the standard inset arrangement.
"""
from __future__ import annotations

import io
import json
import math
import urllib.request
import zipfile
from pathlib import Path

SOURCE = ("https://www2.census.gov/geo/tiger/GENZ2023/shp/"
          "cb_2023_us_state_20m.zip")
OUT = Path(__file__).resolve().parent / "public" / "assets" / "us-states.json"

VIEW_W, VIEW_H = 960.0, 600.0
SIMPLIFY_TOL = 0.35          # pixels, in the output viewBox
MIN_RING_AREA = 1.2          # square pixels; drops specks, keeps real islands

# Territories and non-state entities are excluded: the dashboard's rates need a
# Census state population denominator, which these do not have.
EXCLUDE = {"PR", "VI", "GU", "AS", "MP"}


def conic_equal_area(rotate_lon, center_lat, p1, p2, scale, tx, ty):
    """Return a lon/lat -> (x, y) function for one Albers cone."""
    r = math.radians
    phi1, phi2, phi0 = r(p1), r(p2), r(center_lat)
    n = (math.sin(phi1) + math.sin(phi2)) / 2.0
    C = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    rho0 = math.sqrt(C - 2 * n * math.sin(phi0)) / n

    def project(lon, lat):
        lam = r(lon + rotate_lon)
        phi = r(lat)
        inner = C - 2 * n * math.sin(phi)
        if inner < 0:
            inner = 0.0
        rho = math.sqrt(inner) / n
        theta = n * lam
        x = rho * math.sin(theta)
        y = rho0 - rho * math.cos(theta)
        return (tx + scale * x, ty - scale * y)

    return project


# Continental scale chosen so the lower 48 fill a 960x600 frame.
CONUS = conic_equal_area(96, 37.5, 29.5, 45.5, 1285.0, 487.0, 315.0)

# The insets get their own cone, then are fitted to an explicit target box.
# Hand-picking a scale and translate for Alaska put it on top of California;
# measuring the projected extent and fitting it is self-correcting, and keeps
# the arrangement stable if the source geometry is ever revised.
ALASKA_RAW = conic_equal_area(154, 50.0, 55.0, 65.0, 1.0, 0.0, 0.0)
HAWAII_RAW = conic_equal_area(157, 20.9, 8.0, 18.0, 1.0, 0.0, 0.0)

# (x0, y0, x1, y1) in the output viewBox, in the empty space south-west of
# the continental outline.
ALASKA_BOX = (18.0, 400.0, 228.0, 578.0)
HAWAII_BOX = (250.0, 505.0, 340.0, 566.0)


def fit_transform(raw_points, box):
    """Uniform scale + translate mapping a projected extent into `box`."""
    xs = [p[0] for p in raw_points]
    ys = [p[1] for p in raw_points]
    x0, y0, x1, y1 = box
    sx = (x1 - x0) / (max(xs) - min(xs))
    sy = (y1 - y0) / (max(ys) - min(ys))
    s = min(sx, sy)
    ox = x0 + ((x1 - x0) - (max(xs) - min(xs)) * s) / 2 - min(xs) * s
    oy = y0 + ((y1 - y0) - (max(ys) - min(ys)) * s) / 2 - min(ys) * s
    return lambda p: (ox + p[0] * s, oy + p[1] * s)


def projector_for(abbr):
    if abbr == "AK":
        return ALASKA_RAW
    if abbr == "HI":
        return HAWAII_RAW
    return CONUS


def ring_area(pts):
    """Absolute polygon area by the shoelace formula."""
    a = 0.0
    for i in range(len(pts) - 1):
        a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(a) / 2.0


def simplify(points, tol):
    """Douglas-Peucker, iterative to avoid recursion limits on long rings."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = points[lo]
        bx, by = points[hi]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        best, best_d = -1, 0.0
        for i in range(lo + 1, hi):
            px, py = points[i]
            if seg == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / seg
            if d > best_d:
                best, best_d = i, d
        if best_d > tol and best > 0:
            keep[best] = True
            stack.append((lo, best))
            stack.append((best, hi))
    return [p for p, k in zip(points, keep) if k]


def to_path(rings):
    out = []
    for ring in rings:
        if len(ring) < 3:
            continue
        d = "M" + " ".join(f"{x:.1f},{y:.1f}" for x, y in ring) + "Z"
        out.append(d)
    return "".join(out)


def main() -> None:
    import shapefile

    print(f"downloading {SOURCE}")
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "SPPI-CFPB-Research/0.1"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    z = zipfile.ZipFile(io.BytesIO(blob))
    name = [n for n in z.namelist() if n.endswith(".shp")][0][:-4]
    sf = shapefile.Reader(
        shp=io.BytesIO(z.read(name + ".shp")),
        dbf=io.BytesIO(z.read(name + ".dbf")),
        shx=io.BytesIO(z.read(name + ".shx")),
    )

    states, labels = {}, {}
    kept_pts = dropped_pts = 0
    for shape_rec in sf.shapeRecords():
        abbr = shape_rec.record["STUSPS"]
        if abbr in EXCLUDE:
            continue
        proj = projector_for(abbr)
        shp = shape_rec.shape
        parts = list(shp.parts) + [len(shp.points)]
        rings = []
        for i in range(len(parts) - 1):
            raw = shp.points[parts[i]:parts[i + 1]]
            # The Aleutians run past the antimeridian into positive longitude.
            # Projected with a single cone those rings wrap to the far side of
            # the frame; they are tiny, so they are dropped rather than split.
            if abbr == "AK" and any(lon > 0 for lon, _ in raw):
                continue
            pts = [proj(lon, lat) for lon, lat in raw]
            dropped_pts += len(pts)
            rings.append(pts)
        if not rings:
            continue

        # Insets are projected in raw cone units, so they must be fitted into
        # viewBox space BEFORE the area filter and simplification tolerance --
        # both are expressed in output pixels and would discard everything at
        # raw scale.
        box = ALASKA_BOX if abbr == "AK" else HAWAII_BOX if abbr == "HI" else None
        if box:
            xf = fit_transform([p for r in rings for p in r], box)
            rings = [[xf(p) for p in r] for r in rings]

        cleaned = []
        for pts in rings:
            if ring_area(pts) < MIN_RING_AREA:
                continue
            pts = simplify(pts, SIMPLIFY_TOL)
            kept_pts += len(pts)
            cleaned.append(pts)
        if not cleaned:
            continue
        rings = cleaned

        rings.sort(key=ring_area, reverse=True)
        states[abbr] = to_path(rings)

        # Label anchor: centroid of the largest ring, which sits inside the
        # polygon for every state in this file.
        big = rings[0]
        labels[abbr] = [round(sum(p[0] for p in big) / len(big), 1),
                        round(sum(p[1] for p in big) / len(big), 1)]

    payload = {
        "viewBox": f"0 0 {VIEW_W:.0f} {VIEW_H:.0f}",
        "source": "US Census Bureau cartographic boundary file, 1:20,000,000 "
                  "(public domain)",
        "projection": "Composite Albers equal-area; Alaska inset at 0.35 scale",
        "states": states,
        "labels": labels,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"  {len(states)} states, points {dropped_pts:,} -> {kept_pts:,} "
          f"after simplification")
    xs, ys = [], []
    for d in states.values():
        for pair in d.replace("M", " ").replace("Z", " ").split():
            if "," in pair:
                a, b = pair.split(",")
                xs.append(float(a)); ys.append(float(b))
    print(f"  extent x {min(xs):.0f}..{max(xs):.0f}  y {min(ys):.0f}..{max(ys):.0f} "
          f"(viewBox {VIEW_W:.0f}x{VIEW_H:.0f})")


if __name__ == "__main__":
    main()
