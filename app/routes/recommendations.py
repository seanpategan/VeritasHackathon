"""Deterministic recommendations for a verified selection."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, ConfigDict, Field

from app import selection
from app.errors import APIError
from app.rules import engine

bp = Blueprint("recommendations", __name__, url_prefix="/api")


class RecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_token: str = Field(min_length=10, max_length=2048)
    context: dict[str, str] | None = Field(default=None, max_length=20)


def parse_context(raw) -> tuple[tuple[str, str], ...]:
    try:
        return engine.normalize_context(raw)
    except engine.InvalidContext as exc:
        raise APIError("invalid_context", f"Invalid answer: {exc}.", 422) from exc


@bp.post("/recommendations")
def recommendations():
    body = RecRequest.model_validate(request.get_json(silent=True) or {})
    sel = selection.read(body.selection_token)
    context = parse_context(body.context)
    try:
        return jsonify(engine.generate(selection.to_inputs(sel, context)))
    except engine.UnsupportedCrop as exc:
        raise APIError("unsupported_crop", "Suggestions are available for corn and wheat only.", 422) from exc


@bp.get("/context-questions")
def context_questions():
    return jsonify(engine.load_questions())


@bp.get("/sources")
def sources():
    return jsonify({
        "sources": list(engine.load_sources().values()),
        "case_studies": list(engine.load_case_studies().values()),
        "ruleset_version": engine.load_ruleset()["ruleset_version"],
    })
