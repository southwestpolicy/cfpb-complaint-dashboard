#!/usr/bin/env python3
"""Package the WordPress plugin and write the manifest that drives its updates.

The plugin declares an ``Update URI`` pointing at the GitHub Pages site, which
makes WordPress ask that host — and only that host — whether a newer version
exists. This script produces the two files it asks for:

    dashboard/public/plugin/update.json                 what version is current
    dashboard/public/plugin/sppi-cfpb-dashboard.zip     the package itself

Both are published by the same Pages deployment that publishes the data, so
releasing is: edit ``Version:`` in the plugin header, push, done. Every site
running the plugin offers the update within about twelve hours, or immediately
if an administrator hits "Check for updates now".

The version is read from the plugin header rather than passed in, so the zip and
the manifest can never disagree about what is inside the zip.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "wordpress" / "sppi-cfpb-dashboard"
PLUGIN_FILE = PLUGIN_DIR / "sppi-cfpb-dashboard.php"
OUT_DIR = ROOT / "dashboard" / "public" / "plugin"
SLUG = "sppi-cfpb-dashboard"

# Anything matching these is development residue, not part of the plugin.
EXCLUDE_SUFFIXES = {".bak", ".orig", ".rej", ".pyc", ".log"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", ".gitignore"}
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules"}


def read_header(text: str, field: str) -> str:
    """Pull one value out of the plugin's file header block."""
    m = re.search(rf"^\s*\*?\s*{re.escape(field)}:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


def included_files() -> list[Path]:
    """Every file that belongs in the package, sorted for a stable archive."""
    out = []
    for p in sorted(PLUGIN_DIR.rglob("*")):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(PLUGIN_DIR).parts):
            continue
        if p.suffix in EXCLUDE_SUFFIXES or p.name in EXCLUDE_NAMES:
            continue
        out.append(p)
    return out


def build_zip(dest: Path, files: list[Path]) -> None:
    """Write the package.

    Every entry is prefixed with the slug directory, because WordPress installs
    a plugin zip by unpacking it into wp-content/plugins and expects exactly one
    top-level folder. A flat zip would scatter the files across the plugins
    directory, and a differently named folder would install a second copy
    alongside the existing one rather than updating it.

    Timestamps are pinned so an unchanged plugin produces a byte-identical zip
    and the Pages deploy has nothing to publish.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            arc = Path(SLUG) / p.relative_to(PLUGIN_DIR)
            info = zipfile.ZipInfo(arc.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base-url",
        default="https://southwestpolicy.github.io/cfpb-complaint-dashboard",
        help="Public base URL of the Pages site.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Report the version and what would be packaged, write nothing.",
    )
    args = ap.parse_args()

    if not PLUGIN_FILE.exists():
        print(f"plugin file not found: {PLUGIN_FILE}", file=sys.stderr)
        return 1

    text = PLUGIN_FILE.read_text(encoding="utf-8")
    version = read_header(text, "Version")
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        print(f"unusable Version header: {version!r}", file=sys.stderr)
        return 1

    # The header constant and the header comment are read by different things —
    # WordPress reads the comment, the plugin's own code reads the constant — so
    # a mismatch is invisible until an update half-applies.
    m = re.search(r"define\(\s*'SPPI_CFPB_VERSION',\s*'([^']+)'\s*\)", text)
    if not m:
        print("SPPI_CFPB_VERSION constant not found", file=sys.stderr)
        return 1
    if m.group(1) != version:
        print(
            f"version mismatch: header says {version}, "
            f"SPPI_CFPB_VERSION says {m.group(1)}",
            file=sys.stderr,
        )
        return 1

    files = included_files()
    if args.check:
        print(f"version {version}, {len(files)} files")
        for p in files:
            print("  ", p.relative_to(PLUGIN_DIR).as_posix())
        return 0

    base = args.base_url.rstrip("/")
    zip_path = OUT_DIR / f"{SLUG}.zip"
    build_zip(zip_path, files)

    changelog = ROOT / "wordpress" / "CHANGELOG.md"
    manifest = {
        "name": read_header(text, "Plugin Name"),
        "slug": SLUG,
        "version": version,
        "requires": read_header(text, "Requires at least"),
        "requires_php": read_header(text, "Requires PHP"),
        "tested": read_header(text, "Tested up to"),
        "author": read_header(text, "Author"),
        "homepage": "https://github.com/southwestpolicy/cfpb-complaint-dashboard",
        "last_updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "download_url": f"{base}/plugin/{SLUG}.zip",
        "sections": {
            "description": read_header(text, "Description"),
            "changelog": changelog.read_text(encoding="utf-8") if changelog.exists() else "",
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "update.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(f"packaged {SLUG} {version}: {len(files)} files, {zip_path.stat().st_size} bytes")
    print(f"manifest -> {(OUT_DIR / 'update.json').relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
