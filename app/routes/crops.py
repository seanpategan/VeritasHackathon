"""Crop data routes: dataset info, overview tiles, outlines, point lookup, place search."""
from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, Field

from app import limiter, selection
from app.errors import APIError
from app.services import geocoding, usda

bp = Blueprint("crops", __name__, url_prefix="/api")


def _cache():
    return current_app.extensions["fieldwise_cache"]


def legend() -> list[dict]:
    items = []
    for group, info in usda.MANIFEST["categories"].items():
        for code, meta in info["codes"].items():
            r, g, b = usda.CROP_COLORS[int(code)]
            items.append({
                "group": group, "code": int(code), "label": meta["official_name"],
                "subtype": meta["subtype"], "color": f"#{r:02x}{g:02x}{b:02x}",
            })
    return items


@bp.get("/dataset")
def dataset():
    ds = usda.get_dataset(timeout=current_app.config["USDA_TIMEOUT"])
    m = usda.MANIFEST
    return jsonify({
        "dataset": ds.public(),
        "coverage": m["geographic_coverage"],
        "conus_bbox": m["conus_bbox_wgs84"],
        "legend": legend(),
        "excluded_mixed_categories": m["excluded_mixed_categories"],
        "limitations": m["known_limitations"],
        "zoom": {"tiles_min": usda.TILE_MIN_Z, "tiles_max": usda.TILE_MAX_Z, "outline_grid": usda.OUTLINE_Z},
        "processing": {
            "overview": "At zoom levels below 12, overview tiles are resampled from the 10 m data using the majority class per output pixel; small or narrow crop areas may not appear.",
            "outlines": f"Outlines are traced from raw class pixels on a zoom-{usda.OUTLINE_Z} tile grid, simplified by about {usda.SIMPLIFY_PX:g} pixel; regions under {usda.OUTLINE_MIN_PIXELS} pixels are omitted, and lines along tile edges are removed.",
        },
    })


@bp.get("/tiles/<crop>/<int:z>/<int:x>/<int:y>.png")
@limiter.exempt
def tile(crop: str, z: int, x: int, y: int):
    if crop not in ("corn", "wheat"):
        raise APIError("unsupported_crop", "Only corn and wheat layers are available.", 404)
    ds = usda.get_dataset(timeout=current_app.config["USDA_TIMEOUT"])
    png = usda.tile_png(crop, z, x, y, ds, _cache())
    resp = Response(png, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-CDL-Year"] = str(ds.year)
    return resp


@bp.get("/outlines/<int:z>/<int:x>/<int:y>.json")
@limiter.limit("240 per minute")
def outlines(z: int, x: int, y: int):
    ds = usda.get_dataset(timeout=current_app.config["USDA_TIMEOUT"])
    fc = usda.outline_tile(z, x, y, ds, _cache())
    resp = jsonify(fc)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


class PointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


NOT_TELL = [
    "Who owns or farms this land, or where property boundaries are.",
    "What is planted today — the classification describes the stated growing season only.",
    "Soil type, soil health or soil test results.",
    "Whether the area is irrigated, or how much water or fertilizer is used.",
    "Tillage, cover crop use, rotation history or other management practices.",
    "Crop health, disease or yield.",
]


@bp.post("/crop-at")
@limiter.limit(lambda: current_app.config["RATELIMIT_LOOKUP"])
def crop_at():
    body = PointRequest.model_validate(request.get_json(silent=True) or {})
    lat, lon = body.lat, body.lon
    if not usda.in_conus(lon, lat):
        raise APIError("unsupported_geography", "FieldWise covers the contiguous United States only.", 422)
    if current_app.config["LOG_COORDINATES"]:
        current_app.logger.info("crop-at lookup %.4f,%.4f", lat, lon)

    ds = usda.get_dataset(timeout=current_app.config["USDA_TIMEOUT"])
    code = usda.identify(lon, lat, ds, timeout=current_app.config["USDA_TIMEOUT"])
    info = usda.describe_code(code)
    loc = geocoding.approximate_location(lon, lat, timeout=current_app.config["CENSUS_TIMEOUT"])

    result = {
        "dataset": ds.public(),
        "classification": info,
        "location": {
            "lat": round(lat, 4), "lon": round(lon, 4),
            "county": loc["county"] if loc else None,
            "state": loc["state"] if loc else None,
            "state_abbr": loc["state_abbr"] if loc else None,
            "source": loc["source"] if loc else None,
            "note": None if loc else "County/state lookup was unavailable; coordinates shown instead.",
        },
        "statements": [
            "Mapped crop coverage—not a property boundary.",
            "Current planting and field conditions are not verified.",
        ],
        "does_not_tell": NOT_TELL,
        "limitations": usda.MANIFEST["known_limitations"],
        "supported": info["group"] in ("corn", "wheat"),
        "region": None,
        "selection_token": None,
    }
    if result["supported"]:
        result["region"] = usda.region_at(lon, lat, code, ds, _cache())
        result["selection_token"] = selection.issue(
            code, info["crop"], info["official_name"], info["subtype"], ds.year, ds.raster_id,
            result["location"]["state_abbr"], result["location"]["state"], result["location"]["county"],
        )
    elif info["group"] == "double_crop":
        result["message"] = (
            f"This point is classified as '{info['official_name']}', a double-crop category. FieldWise does not "
            "count double-crop classes as simple corn or wheat, so no crop-specific suggestions are shown."
        )
    elif info["group"] == "no_data":
        result["message"] = "No classification value is available at this point in the selected dataset."
    else:
        name = info["official_name"] or f"class {info['code']}"
        result["message"] = (
            f"This point is classified as '{name}' in the {ds.year} Cropland Data Layer — not corn or wheat. "
            "FieldWise currently provides suggestions for corn and wheat only."
        )
    return jsonify(result)


@bp.get("/search")
@limiter.limit("120 per minute")
def search():
    q = (request.args.get("q") or "").strip()
    if len(q) > 80:
        raise APIError("invalid_query", "Search text is too long.", 400)
    if len(q) < 2:
        return jsonify({"results": []})
    return jsonify(geocoding.search(q))
