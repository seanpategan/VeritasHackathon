"""USDA Cropland Data Layer access via the CroplandCROS ArcGIS ImageServer.

Everything here works on *raw* U8 class codes requested in EPSG:3857, so the categorical raster
is never resampled into misleading colours, and coordinates stay aligned with the Web Mercator map.
"""
from __future__ import annotations

import io
import json
import math
import re
import threading
import time
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

from app.errors import APIError, UpstreamError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SERVICE = "https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer"
RASTER_NAME_RE = re.compile(r"^(\d{4})_(\d+)m_cdls$")
WEB_MERCATOR_HALF = 20037508.342789244
MAX_EXPORT_PX = 1024  # bound every raster request
USER_AGENT = "FieldWise/1.0 (educational hackathon prototype)"

with open(DATA_DIR / "dataset_manifest.json", encoding="utf-8") as _fh:
    MANIFEST = json.load(_fh)

# rasterio.features.shapes wraps numpy arrays in an un-georeferenced dataset; we pass an explicit
# transform, so its NotGeoreferencedWarning is noise.
warnings.filterwarnings("ignore", message="Dataset has no geotransform")

CONUS_BBOX = tuple(MANIFEST["conus_bbox_wgs84"])  # (min_lon, min_lat, max_lon, max_lat)

# code -> (crop group, official name, subtype)
CROP_CODES: dict[int, tuple[str, str, str | None]] = {}
for _group, _info in MANIFEST["categories"].items():
    for _code, _meta in _info["codes"].items():
        CROP_CODES[int(_code)] = (_group, _meta["official_name"], _meta["subtype"])
MIXED_CODES = {int(k): v for k, v in MANIFEST["excluded_mixed_categories"]["codes"].items()}
CORN_CODES = sorted(c for c, v in CROP_CODES.items() if v[0] == "corn")
WHEAT_CODES = sorted(c for c, v in CROP_CODES.items() if v[0] == "wheat")


@dataclass
class DatasetInfo:
    year: int
    raster_id: int
    raster_name: str
    resolution_m: int | None
    checked_at: str
    status: str  # "live" (verified by catalog query just now) or "last_verified_record"
    status_note: str

    def public(self) -> dict:
        d = asdict(self)
        d.update(
            title=MANIFEST["dataset_title"],
            publisher=MANIFEST["publisher"],
            source_url=MANIFEST["official_source_url"],
            service_endpoint=MANIFEST["integration"]["service_endpoint"],
            faq_url=MANIFEST["faq_url"],
        )
        return d


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


_http = _session()
_dataset_lock = threading.Lock()
_dataset_cache: dict = {"info": None, "expires": 0.0}
DATASET_TTL = 6 * 3600
DATASET_RETRY_TTL = 300


def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = lon * WEB_MERCATOR_HALF / 180.0
    lat = max(min(lat, 85.05112878), -85.05112878)
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * WEB_MERCATOR_HALF / math.pi
    return x, y


def mercator_to_lonlat_arrays(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon = x * 180.0 / WEB_MERCATOR_HALF
    lat = np.degrees(2 * np.arctan(np.exp(y * math.pi / WEB_MERCATOR_HALF)) - math.pi / 2)
    return lon, lat


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = 2 * WEB_MERCATOR_HALF / (2**z)
    minx = -WEB_MERCATOR_HALF + x * size
    maxy = WEB_MERCATOR_HALF - y * size
    return minx, maxy - size, minx + size, maxy


def tile_bounds_lonlat(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = tile_bounds_mercator(z, x, y)
    lons, lats = mercator_to_lonlat_arrays(np.array([minx, maxx]), np.array([miny, maxy]))
    return float(lons[0]), float(lats[0]), float(lons[1]), float(lats[1])


def in_conus(lon: float, lat: float) -> bool:
    return CONUS_BBOX[0] <= lon <= CONUS_BBOX[2] and CONUS_BBOX[1] <= lat <= CONUS_BBOX[3]


def tile_intersects_conus(z: int, x: int, y: int) -> bool:
    w, s, e, n = tile_bounds_lonlat(z, x, y)
    return not (e < CONUS_BBOX[0] or w > CONUS_BBOX[2] or n < CONUS_BBOX[1] or s > CONUS_BBOX[3])


def validate_tile(z: int, x: int, y: int, min_z: int, max_z: int) -> None:
    if not (min_z <= z <= max_z):
        raise APIError("unsupported_zoom", f"Zoom must be between {min_z} and {max_z}.", 400)
    n = 2**z
    if not (0 <= x < n and 0 <= y < n):
        raise APIError("invalid_tile", "Tile coordinates are out of range.", 400)


# --------------------------------------------------------------------------- dataset discovery

def _fallback_dataset(reason: str) -> DatasetInfo:
    lv = MANIFEST["last_verified"]
    return DatasetInfo(
        year=lv["year"],
        raster_id=lv["raster_id"],
        raster_name=lv["raster_name"],
        resolution_m=lv.get("resolution_m"),
        checked_at=lv["checked_at"],
        status="last_verified_record",
        status_note=(
            "The live dataset catalog could not be reached ("
            + reason
            + "). Showing the last verified record from the dataset manifest; a newer year may exist."
        ),
    )


def query_latest_dataset(timeout: float = 15.0) -> DatasetInfo:
    """Ask the ImageServer catalog which yearly rasters exist and return the newest CDL."""
    resp = _http.get(
        f"{SERVICE}/query",
        params={
            "where": "1=1",
            "outFields": "OBJECTID,Name,Year",
            "returnGeometry": "false",
            "orderByFields": "Year DESC",
            "f": "json",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"catalog error: {data['error'].get('message')}")
    best = None
    for feat in data.get("features", []):
        a = feat.get("attributes", {})
        m = RASTER_NAME_RE.match(str(a.get("Name", "")))
        if not m or a.get("Year") is None:
            continue
        year = int(a["Year"])
        if best is None or year > best[0]:
            best = (year, int(a["OBJECTID"]), a["Name"], int(m.group(2)))
    if best is None:
        raise ValueError("catalog returned no CDL rasters")
    return DatasetInfo(
        year=best[0],
        raster_id=best[1],
        raster_name=best[2],
        resolution_m=best[3],
        checked_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        status="live",
        status_note="Newest yearly raster listed by the USDA CroplandCROS service catalog at the time shown.",
    )


def get_dataset(timeout: float = 15.0) -> DatasetInfo:
    now = time.time()
    with _dataset_lock:
        if _dataset_cache["info"] is not None and now < _dataset_cache["expires"]:
            return _dataset_cache["info"]
        try:
            info = query_latest_dataset(timeout)
            ttl = DATASET_TTL
        except (requests.RequestException, ValueError) as exc:
            info = _fallback_dataset(type(exc).__name__)
            ttl = DATASET_RETRY_TTL
        _dataset_cache.update(info=info, expires=now + ttl)
        return info


def reset_dataset_cache() -> None:
    with _dataset_lock:
        _dataset_cache.update(info=None, expires=0.0)


def _mosaic_rule(ds: DatasetInfo) -> str:
    return json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [ds.raster_id]})


# --------------------------------------------------------------------------- classification

def describe_code(code: int | None) -> dict:
    """Map an official CDL class code to FieldWise's crop groups without blending mixed classes."""
    if code is None:
        return {"code": None, "official_name": None, "group": "no_data", "crop": None, "subtype": None}
    if code in CROP_CODES:
        group, name, subtype = CROP_CODES[code]
        return {"code": code, "official_name": name, "group": group, "crop": group, "subtype": subtype}
    if code in MIXED_CODES:
        return {"code": code, "official_name": MIXED_CODES[code], "group": "double_crop", "crop": None, "subtype": None}
    return {"code": code, "official_name": class_name(code), "group": "other", "crop": None, "subtype": None}


_class_names: dict[int, str] | None = None
_class_names_lock = threading.Lock()


def class_name(code: int) -> str | None:
    """Official class name from the service's raster attribute table (fetched once, cached)."""
    global _class_names
    with _class_names_lock:
        if _class_names is None:
            try:
                ds = get_dataset()
                r = _http.get(
                    f"{SERVICE}/rasterAttributeTable",
                    params={"f": "json", "mosaicRule": _mosaic_rule(ds)},
                    timeout=15,
                )
                r.raise_for_status()
                _class_names = {
                    int(f["attributes"]["Value"]): str(f["attributes"]["Class_Names"]).strip()
                    for f in r.json().get("features", [])
                    if f["attributes"].get("Class_Names")
                }
            except (requests.RequestException, ValueError, KeyError):
                return None  # retry next time
        return _class_names.get(code)


def identify(lon: float, lat: float, ds: DatasetInfo, timeout: float = 20.0) -> int | None:
    x, y = lonlat_to_mercator(lon, lat)
    try:
        r = _http.get(
            f"{SERVICE}/identify",
            params={
                "geometry": json.dumps({"x": x, "y": y, "spatialReference": {"wkid": 3857}}),
                "geometryType": "esriGeometryPoint",
                "mosaicRule": _mosaic_rule(ds),
                "returnGeometry": "false",
                "returnCatalogItems": "false",
                "f": "json",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError("usda_unavailable", "The USDA Cropland Data Layer service did not respond.") from exc
    if "error" in data:
        raise UpstreamError("usda_unavailable", "The USDA Cropland Data Layer service returned an error.")
    value = str(data.get("value", "")).strip()
    if not value or value.lower() == "nodata":
        return None
    try:
        code = int(float(value))
    except ValueError:
        return None
    return code or None  # 0 = background / no data


def export_window(bbox: tuple[float, float, float, float], width: int, height: int, ds: DatasetInfo,
                  cache=None, resample: str = "nearest", timeout: float = 20.0) -> np.ndarray:
    """Raw class codes for an EPSG:3857 bbox. Bounded in size; cached by raster ID + bbox."""
    if not (1 <= width <= MAX_EXPORT_PX and 1 <= height <= MAX_EXPORT_PX):
        raise APIError("window_too_large", "Requested raster window is too large.", 400)
    minx, miny, maxx, maxy = bbox
    if not (maxx > minx and maxy > miny):
        raise APIError("invalid_bbox", "Invalid bounding box.", 400)
    interp = "RSP_NearestNeighbor" if resample == "nearest" else "RSP_Majority"
    key = f"win:{ds.raster_id}:{minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f}:{width}x{height}:{interp}"
    if cache is not None:
        hit = cache.get(key, ".npy")
        if hit is not None:
            return np.load(io.BytesIO(hit))
    try:
        r = _http.get(
            f"{SERVICE}/exportImage",
            params={
                "bbox": f"{minx},{miny},{maxx},{maxy}",
                "bboxSR": 3857,
                "imageSR": 3857,
                "size": f"{width},{height}",
                "format": "tiff",
                "pixelType": "U8",
                "noData": 0,
                "interpolation": interp,
                "mosaicRule": _mosaic_rule(ds),
                "f": "image",
            },
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamError("usda_unavailable", "The USDA Cropland Data Layer service did not respond.") from exc
    if "image/tiff" not in r.headers.get("content-type", ""):
        raise UpstreamError("usda_unavailable", "The USDA service returned an unexpected response.")
    arr = _read_tiff(r.content)
    if arr.shape != (height, width):
        raise UpstreamError("usda_unexpected_shape", "The USDA service returned an unexpected raster size.")
    if cache is not None:
        buf = io.BytesIO()
        np.save(buf, arr)
        cache.set(key, buf.getvalue(), ".npy")
    return arr


def _read_tiff(content: bytes) -> np.ndarray:
    from rasterio.io import MemoryFile

    try:
        with MemoryFile(content) as mem, mem.open() as src:
            return src.read(1).astype(np.uint8)
    except Exception as exc:  # rasterio raises several error types for corrupt input
        raise UpstreamError("usda_bad_raster", "Could not read the raster returned by USDA.") from exc


# --------------------------------------------------------------------------- tiles (overview)

CROP_COLORS = {
    # Corn: yellow family. Wheat: violet family. Blue/yellow axis stays distinct for common colour-vision deficiencies.
    1: (255, 204, 26),
    12: (255, 228, 120),
    13: (230, 170, 0),
    22: (120, 72, 255),   # durum
    23: (196, 160, 255),  # spring
    24: (160, 108, 255),  # winter
}
TILE_MIN_Z, TILE_MAX_Z = 4, 15


def render_tile_png(arr: np.ndarray, crop: str) -> bytes:
    from PIL import Image

    codes = CORN_CODES if crop == "corn" else WHEAT_CODES
    rgba = np.zeros(arr.shape + (4,), dtype=np.uint8)
    for code in codes:
        m = arr == code
        if m.any():
            rgba[m, :3] = CROP_COLORS[code]
            rgba[m, 3] = 255
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


_EMPTY_PNG: bytes | None = None


def empty_png() -> bytes:
    global _EMPTY_PNG
    if _EMPTY_PNG is None:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, "PNG", optimize=True)
        _EMPTY_PNG = buf.getvalue()
    return _EMPTY_PNG


def tile_png(crop: str, z: int, x: int, y: int, ds: DatasetInfo, cache) -> bytes:
    validate_tile(z, x, y, TILE_MIN_Z, TILE_MAX_Z)
    if not tile_intersects_conus(z, x, y):
        return empty_png()
    key = f"tile:{ds.raster_id}:{crop}:{z}/{x}/{y}"
    hit = cache.get(key, ".png") if cache else None
    if hit is not None:
        return hit
    # Broad zooms: majority resampling gives an honest categorical overview; close zooms: nearest neighbour.
    resample = "majority" if z < 12 else "nearest"
    arr = export_window(tile_bounds_mercator(z, x, y), 256, 256, ds, cache=cache, resample=resample)
    png = render_tile_png(arr, crop)
    if cache:
        cache.set(key, png, ".png")
    return png


# --------------------------------------------------------------------------- polygonization

OUTLINE_Z = 13
OUTLINE_PX = 512          # ~7-9 m pixels at z13 in CONUS: close to the 10 m native resolution
OUTLINE_MIN_PIXELS = 12   # drop specks smaller than this many pixels from the outline layer
SIMPLIFY_PX = 0.5         # Douglas-Peucker tolerance in pixels (disclosed in the UI)


def _affine(bbox, width, height):
    from rasterio.transform import from_bounds

    return from_bounds(*bbox, width, height)


def _to_lonlat_geom(geom):
    import shapely

    def fn(coords):
        lon, lat = mercator_to_lonlat_arrays(coords[:, 0], coords[:, 1])
        return np.column_stack([np.round(lon, 6), np.round(lat, 6)])

    return shapely.transform(geom, fn)


def outline_tile(z: int, x: int, y: int, ds: DatasetInfo, cache) -> dict:
    """GeoJSON boundary lines of corn/wheat class regions for one z13 tile.

    Lines that coincide with the tile frame are removed, so tile seams are never drawn as if they were
    region boundaries. Regions that touch the frame are flagged as clipped.
    """
    import shapely
    from rasterio import features
    from shapely.geometry import box, mapping, shape

    if z != OUTLINE_Z:
        raise APIError("unsupported_zoom", f"Outlines are generated on the z{OUTLINE_Z} tile grid only.", 400)
    validate_tile(z, x, y, OUTLINE_Z, OUTLINE_Z)
    key = f"outline:v2:{ds.raster_id}:{z}/{x}/{y}"
    hit = cache.get(key, ".json") if cache else None
    if hit is not None:
        return json.loads(hit)
    if not tile_intersects_conus(z, x, y):
        return {"type": "FeatureCollection", "features": []}

    bbox = tile_bounds_mercator(z, x, y)
    arr = export_window(bbox, OUTLINE_PX, OUTLINE_PX, ds, cache=cache)
    transform = _affine(bbox, OUTLINE_PX, OUTLINE_PX)
    px = (bbox[2] - bbox[0]) / OUTLINE_PX
    frame = box(*bbox).boundary.buffer(px * 0.25)
    inner = box(*bbox).buffer(-px * 0.5)
    crop_mask = np.isin(arr, CORN_CODES + WHEAT_CODES)
    out = []
    for geom, val in features.shapes(arr, mask=crop_mask, connectivity=4, transform=transform):
        poly = shape(geom)
        if poly.area < OUTLINE_MIN_PIXELS * px * px:
            continue
        clipped = not inner.contains(poly)
        poly = poly.simplify(px * SIMPLIFY_PX, preserve_topology=True)
        line = poly.boundary.difference(frame)
        if line.is_empty:
            continue
        info = describe_code(int(val))
        out.append({
            "type": "Feature",
            "properties": {"code": int(val), "crop": info["crop"], "clipped": clipped},
            "geometry": mapping(_to_lonlat_geom(line)),
        })
    fc = {"type": "FeatureCollection", "features": out}
    if cache:
        cache.set(key, json.dumps(fc, separators=(",", ":")).encode(), ".json")
    return fc


def region_at(lon: float, lat: float, code: int, ds: DatasetInfo, cache) -> dict:
    """Connected region (4-connectivity) of the clicked pixel's class, within a bounded window.

    Tries a ~5 km window, then a ~10 km window. If the region still touches the window edge it is
    reported as clipped (incomplete) and no area is given.
    """
    from pyproj import Geod
    from rasterio import features
    from shapely.geometry import Point, box, mapping, shape

    cx, cy = lonlat_to_mercator(lon, lat)
    # metres per pixel on the ground ~= mercator units * cos(lat); request near-native 10 m ground pixels.
    scale = 1.0 / max(math.cos(math.radians(lat)), 0.2)
    pt = Point(cx, cy)
    result = None
    for size_px in (512, 1024):
        half = (size_px / 2) * 10.0 * scale
        bbox = (cx - half, cy - half, cx + half, cy + half)
        arr = export_window(bbox, size_px, size_px, ds, cache=cache)
        transform = _affine(bbox, size_px, size_px)
        px = (bbox[2] - bbox[0]) / size_px
        mask = arr == code
        found = None
        for geom, _val in features.shapes(arr, mask=mask, connectivity=4, transform=transform):
            poly = shape(geom)
            if poly.buffer(px * 0.01).contains(pt):
                found = poly
                break
        if found is None:
            # The point-identify and window disagree (e.g. pixel-boundary rounding). Report honestly.
            return {"available": False, "reason": "The clicked pixel's region could not be traced in the raster window."}
        inner = box(*bbox).buffer(-px * 0.5)
        clipped = not inner.contains(found)
        result = (found, clipped, px, size_px)
        if not clipped:
            break

    poly, clipped, px, size_px = result
    pixel_count = int(round(poly.area / (px * px)))
    simplified = poly.simplify(px * SIMPLIFY_PX, preserve_topology=True)
    geom_ll = _to_lonlat_geom(simplified)
    area = None
    if not clipped:
        geod = Geod(ellps="WGS84")
        area_m2 = abs(geod.geometry_area_perimeter(_to_lonlat_geom(poly))[0])
        area = {"hectares": round(area_m2 / 10000, 1), "acres": round(area_m2 / 4046.8564224, 1)}
    window_km = round(size_px * 10.0 / 1000, 1)
    return {
        "available": True,
        "geometry": mapping(geom_ll),
        "clipped": clipped,
        "mapped_area": area,
        "pixel_count": pixel_count,
        "window_km": window_km,
        "notes": [
            "Region = connected pixels (edge-adjacent) with the same CDL class as the clicked pixel.",
            f"Outline simplified with a tolerance of about {SIMPLIFY_PX:g} pixel for display; the area is computed from the unsimplified pixel outline.",
        ] + ([
            f"This region extends beyond the {window_km} km analysis window, so the shape shown is incomplete and no size is given."
        ] if clipped else []),
    }
