"""Re-verify the newest retrievable USDA CDL year and record the evidence in the dataset manifest.

Checks performed (all real requests):
  1. CroplandCROS ImageServer catalog -> newest YYYY_<res>m_cdls raster.
  2. ImageServer identify at a known corn location with the mosaic locked to that raster.
  3. CropScape GetCDLValue for (newest year + 1) -> service-reported valid year range.

Usage:  python scripts/check_dataset.py           (prints results)
        python scripts/check_dataset.py --write   (also updates app/data/dataset_manifest.json)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services import usda  # noqa: E402

MANIFEST = Path(__file__).resolve().parent.parent / "app" / "data" / "dataset_manifest.json"
PROBE = (-93.54994, 42.04996)  # Story County, Iowa


def main() -> None:
    ds = usda.query_latest_dataset()
    evidence = [f"ImageServer catalog query returned {ds.raster_name} (OBJECTID {ds.raster_id}) as the highest Year."]
    code = usda.identify(*PROBE, ds)
    evidence.append(f"ImageServer identify at Story County, Iowa returned class {code} ({usda.describe_code(code)['official_name']}) with the mosaic locked to raster {ds.raster_id}.")
    try:
        from pyproj import Transformer

        x, y = Transformer.from_crs(4326, 5070, always_xy=True).transform(*PROBE)
        r = requests.get("https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue",
                         params={"year": ds.year + 1, "x": x, "y": y}, timeout=30)
        m = re.search(r"year must be between (\d{4}) and (\d{4})", r.text)
        if m:
            evidence.append(f"CropScape GetCDLValue for year={ds.year + 1} reported valid years {m.group(1)}-{m.group(2)}.")
        else:
            evidence.append(f"CropScape GetCDLValue for year={ds.year + 1} responded: {r.text[:160]!r} — a newer year may exist; investigate.")
    except requests.RequestException as exc:
        evidence.append(f"CropScape cross-check failed: {type(exc).__name__} (unverified).")

    print(json.dumps({"year": ds.year, "raster": ds.raster_name, "checked_at": ds.checked_at, "evidence": evidence}, indent=2))
    if "--write" in sys.argv:
        m = json.loads(MANIFEST.read_text())
        m["last_verified"] = {
            "year": ds.year, "raster_id": ds.raster_id, "raster_name": ds.raster_name,
            "resolution_m": ds.resolution_m, "checked_at": ds.checked_at, "evidence": evidence,
        }
        MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
        print(f"updated {MANIFEST}")


if __name__ == "__main__":
    main()
