"""Town / ZIP search (U.S. Census Gazetteer, served locally) and approximate-location lookup
(U.S. Census Geocoder 'geographies/coordinates', a documented public API).

This is place navigation only. It is not a cadastral, parcel, or ownership lookup.
"""
from __future__ import annotations

import json
import math
import re
import threading
import unicodedata
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data" / "gazetteer.json"
CENSUS_COORDS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

STATE_NAMES = {
    "AL": "Alabama", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_ABBR = {v.lower(): k for k, v in STATE_NAMES.items()}

_index = None
_lock = threading.Lock()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("saint ", "st ").replace("st. ", "st ").replace("ft. ", "fort ")
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def _load():
    global _index
    with _lock:
        if _index is None:
            doc = json.loads(DATA.read_text())
            places = [(_norm(p[0]), p) for p in doc["places"]]
            _index = {"places": places, "zctas": {z[0]: z for z in doc["zctas"]}, "meta": {
                "source": doc["source"], "source_url": doc["source_url"], "retrieved_at": doc["retrieved_at"]}}
    return _index


def _bbox(lat: float, lon: float, aland_m2: int) -> list[float]:
    radius_m = max(math.sqrt(max(aland_m2, 1) / math.pi) * 1.6, 2500.0)
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.2))
    return [round(lon - dlon, 5), round(lat - dlat, 5), round(lon + dlon, 5), round(lat + dlat, 5)]


def search(query: str, limit: int = 8) -> dict:
    idx = _load()
    q = query.strip()
    results = []
    if re.fullmatch(r"\d{3,5}", q):
        if len(q) == 5 and q in idx["zctas"]:
            matches = [idx["zctas"][q]]
        else:
            matches = [z for k, z in idx["zctas"].items() if k.startswith(q)][:limit]
        for z in matches:
            results.append({"label": f"ZIP {z[0]}", "kind": "zip", "lat": z[1], "lon": z[2], "bbox": _bbox(z[1], z[2], z[3])})
    else:
        state = None
        name = q
        if "," in q:
            name, st = [s.strip() for s in q.rsplit(",", 1)]
            st_l = st.lower()
            state = st.upper() if st.upper() in STATE_NAMES else NAME_TO_ABBR.get(st_l)
        nq = _norm(name)
        if len(nq) < 2:
            return {"results": [], "source": idx["meta"]}
        scored = []
        for norm_name, p in idx["places"]:
            if state and p[1] != state:
                continue
            if norm_name == nq:
                rank = 0
            elif norm_name.startswith(nq):
                rank = 1
            elif f" {nq}" in f" {norm_name}":
                rank = 2
            else:
                continue
            scored.append((rank, -p[4], p[0], p[1], p))
        scored.sort()
        for _r, _a, _n, _s, p in scored[:limit]:
            results.append({
                "label": f"{p[0]}, {p[1]}", "kind": "place", "lat": p[2], "lon": p[3], "bbox": _bbox(p[2], p[3], p[4]),
            })
    return {"results": results, "source": idx["meta"]}


_session = requests.Session()
_session.headers["User-Agent"] = "FieldWise/1.0 (educational hackathon prototype)"


def approximate_location(lon: float, lat: float, timeout: float = 6.0) -> dict | None:
    """County and state for a point via the Census Geocoder. Returns None on any failure."""
    try:
        r = _session.get(
            CENSUS_COORDS_URL,
            params={"x": f"{lon:.5f}", "y": f"{lat:.5f}", "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current", "layers": "States,Counties", "format": "json"},
            timeout=timeout,
        )
        r.raise_for_status()
        geos = r.json()["result"]["geographies"]
        state = geos.get("States", [{}])[0]
        county = geos.get("Counties", [{}])[0]
        if not state.get("STUSAB"):
            return None
        return {
            "state": state.get("NAME"),
            "state_abbr": state.get("STUSAB"),
            "county": county.get("NAME"),
            "source": "U.S. Census Bureau Geocoder (geographies/coordinates)",
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None
