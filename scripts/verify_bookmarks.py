"""Find and verify judge-navigation bookmarks against the live USDA CDL.

For each candidate area (a county-level description, no farm names), this searches a bounded raster
window for a pixel well inside a region of the target class, then confirms it with a point identify.
Writes app/data/bookmarks.json. Re-run after a new CDL year is published.

Usage:  python scripts/verify_bookmarks.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services import usda  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "bookmarks.json"

CANDIDATES = [
    {"id": "story-ia", "area": "Story County, Iowa", "lon": -93.55, "lat": 42.05, "code": 1},
    {"id": "mclean-il", "area": "McLean County, Illinois", "lon": -88.85, "lat": 40.55, "code": 1},
    {"id": "sumner-ks", "area": "Sumner County, Kansas", "lon": -97.55, "lat": 37.15, "code": 24},
    {"id": "whitman-wa", "area": "Whitman County, Washington (Palouse)", "lon": -117.35, "lat": 46.95, "code": 24},
    {"id": "cavalier-nd", "area": "Cavalier County, North Dakota", "lon": -98.45, "lat": 48.75, "code": 23},
    {"id": "divide-nd", "area": "Divide County, North Dakota", "lon": -103.4, "lat": 48.85, "code": 22},
]


def find_point(c: dict, ds) -> dict | None:
    cx, cy = usda.lonlat_to_mercator(c["lon"], c["lat"])
    scale = 1 / math.cos(math.radians(c["lat"]))
    for size_px in (512, 1024):
        half = size_px / 2 * 10 * scale
        bbox = (cx - half, cy - half, cx + half, cy + half)
        arr = usda.export_window(bbox, size_px, size_px, ds)
        m = arr == c["code"]
        # pixel interior to a 9x9 block of the same class (avoid field edges)
        k = 4
        core = np.ones_like(m)
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                core &= np.roll(np.roll(m, dy, 0), dx, 1)
        core[:k, :] = core[-k:, :] = core[:, :k] = core[:, -k:] = False
        ys, xs = np.nonzero(core)
        if len(ys) == 0:
            continue
        d = (ys - size_px / 2) ** 2 + (xs - size_px / 2) ** 2
        i = int(np.argmin(d))
        px = (bbox[2] - bbox[0]) / size_px
        mx = bbox[0] + (xs[i] + 0.5) * px
        my = bbox[3] - (ys[i] + 0.5) * px
        lon, lat = usda.mercator_to_lonlat_arrays(np.array([mx]), np.array([my]))
        lon, lat = round(float(lon[0]), 5), round(float(lat[0]), 5)
        code = usda.identify(lon, lat, ds)
        if code == c["code"]:
            return {"lon": lon, "lat": lat}
    return None


def main() -> None:
    ds = usda.get_dataset()
    if ds.status != "live":
        sys.exit("Dataset catalog not reachable; refusing to verify bookmarks against a fallback record.")
    out = []
    for c in CANDIDATES:
        pt = find_point(c, ds)
        info = usda.describe_code(c["code"])
        if pt is None:
            print(f"SKIP {c['id']}: no verified {info['official_name']} pixel found")
            continue
        out.append({
            "id": c["id"],
            "label": f"{info['official_name']} — {c['area']}",
            "area": c["area"],
            "lon": pt["lon"],
            "lat": pt["lat"],
            "zoom": 14.5,
            "expected_code": c["code"],
            "expected_class": info["official_name"],
            "verified_year": ds.year,
            "verified_raster": ds.raster_name,
            "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        })
        print(f"OK   {c['id']}: {pt} = {info['official_name']}")
    OUT.write_text(json.dumps({
        "note": "Real locations classified as the stated crop in the CDL year shown. Bookmarks describe counties, not farms or owners.",
        "bookmarks": out,
    }, indent=2))
    print(f"wrote {OUT} ({len(out)} bookmarks)")


if __name__ == "__main__":
    main()
