"""Download U.S. Census Bureau Gazetteer files (places + ZCTAs) and write a compact CONUS search index.

Usage:  python scripts/build_gazetteer.py [YEAR]
Source: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
Output: app/data/gazetteer.json
"""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "gazetteer.json"
URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_{k}_national.zip"
CONUS = (-125.0, 24.4, -66.9, 49.5)
EXCLUDE_STATES = {"AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM"}
LSAD_SUFFIXES = [
    " city and borough", " consolidated government", " unified government", " metropolitan government",
    " urban county", " municipality", " borough", " city", " town", " village", " CDP", " comunidad",
]


def fetch(year: int, kind: str) -> list[dict]:
    r = requests.get(URL.format(y=year, k=kind), timeout=120, headers={"User-Agent": "FieldWise build script"})
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(name).decode("utf-8", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in rows]


def clean_place(name: str) -> str:
    for suf in LSAD_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def in_conus(lon: float, lat: float) -> bool:
    return CONUS[0] <= lon <= CONUS[2] and CONUS[1] <= lat <= CONUS[3]


def main() -> None:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    places, zips = [], []
    for row in fetch(year, "place"):
        if row["USPS"] in EXCLUDE_STATES:
            continue
        lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
        if in_conus(lon, lat):
            places.append([clean_place(row["NAME"]), row["USPS"], round(lat, 5), round(lon, 5), int(row["ALAND"])])
    for row in fetch(year, "zcta"):
        lat, lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
        if in_conus(lon, lat):
            zips.append([row["GEOID"], round(lat, 5), round(lon, 5), int(row["ALAND"])])
    doc = {
        "source": f"U.S. Census Bureau {year} Gazetteer Files (places and ZIP Code Tabulation Areas)",
        "source_url": "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html",
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "notes": "ZCTAs approximate USPS ZIP Code service areas; coordinates are Census internal points.",
        "places": places,
        "zctas": zips,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")))
    print(f"wrote {OUT} places={len(places)} zctas={len(zips)} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
