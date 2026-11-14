"""Signed selection tokens.

/api/crop-at verifies a clicked point against real CDL data and returns a token signed with
SECRET_KEY containing only the verified crop facts (no precise coordinates). Recommendation and AI
endpoints accept that token instead of client-supplied crop claims, so reports are only generated
for verified classifications.
"""
from __future__ import annotations

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.errors import APIError
from app.rules.engine import Inputs

SALT = "fieldwise-selection-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def issue(code: int, crop: str, official_name: str, subtype: str | None, year: int, raster_id: int,
          state_abbr: str | None, state_name: str | None, county: str | None) -> str:
    return _serializer().dumps({
        "code": code, "crop": crop, "name": official_name, "subtype": subtype, "year": year,
        "raster": raster_id, "st": state_abbr, "state": state_name, "county": county,
    })


def read(token: str) -> dict:
    try:
        return _serializer().loads(token, max_age=current_app.config["SELECTION_TOKEN_MAX_AGE"])
    except SignatureExpired as exc:
        raise APIError("selection_expired", "This selection has expired. Please select the crop area again.", 410) from exc
    except BadSignature as exc:
        raise APIError("invalid_selection", "Selection could not be verified. Please select the crop area again.", 400) from exc


def to_inputs(sel: dict, context: tuple = ()) -> Inputs:
    return Inputs(
        crop=sel["crop"], official_name=sel["name"], subtype=sel["subtype"], year=int(sel["year"]),
        state_abbr=sel.get("st"), state_name=sel.get("state"), context=context,
    )
