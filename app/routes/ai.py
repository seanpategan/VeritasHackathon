"""'Run AI audit' — explains the deterministic suggestions and adds clearly labeled AI considerations."""
from __future__ import annotations

import hashlib
import json

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, Field

from app import limiter, selection
from app.errors import APIError
from app.routes.crops import NOT_TELL
from app.rules import engine
from app.services import ai_provider, turnstile, usda

bp = Blueprint("ai", __name__, url_prefix="/api")


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_token: str = Field(min_length=10, max_length=2048)
    turnstile_token: str = Field(default="", max_length=2048)
    context: dict[str, str] | None = Field(default=None, max_length=20)


def get_provider():
    """Factory (monkeypatched in tests)."""
    cfg = current_app.config
    return ai_provider.AnthropicProvider(
        api_key=cfg["ANTHROPIC_API_KEY"], model=cfg["AI_MODEL"], max_output_tokens=cfg["AI_MAX_OUTPUT_TOKENS"],
        timeout=cfg["AI_TIMEOUT"], max_attempts=cfg["AI_MAX_ATTEMPTS"],
    )


def ai_status() -> dict:
    cfg = current_app.config
    if not cfg["AI_ENABLED"]:
        return {"available": False, "code": "ai_disabled", "message": "The AI audit is switched off on this server."}
    if not cfg["ANTHROPIC_API_KEY"]:
        return {"available": False, "code": "ai_not_configured", "message": "The AI audit is not configured on this server (missing ANTHROPIC_API_KEY)."}
    if not cfg["TURNSTILE_SECRET_KEY"] or not cfg["TURNSTILE_SITE_KEY"]:
        return {"available": False, "code": "turnstile_not_configured", "message": "Bot protection is not configured, so the AI audit is disabled."}
    return {"available": True, "code": "ok", "message": ""}


def build_context(sel: dict, recs: dict) -> dict:
    sources = engine.load_sources()
    used = []
    for g in recs["groups"]:
        for r in g["recommendations"]:
            for s in r["sources"]:
                if s["id"] not in used:
                    used.append(s["id"])
    return {
        "selection": {
            "classified_crop": sel["name"], "crop_group": sel["crop"], "subtype": sel["subtype"],
            "classification_year": sel["year"], "dataset": usda.MANIFEST["dataset_title"],
            "approximate_location": ", ".join(p for p in (sel.get("county"), sel.get("state")) if p) or "unknown",
        },
        "recommendations_in_order": [
            {
                "id": r["id"], "category": r["category_label"], "conditional_on": r["conditional_prefix"],
                "action": r["action"], "why_it_may_help": r["why"], "general_context": r["general_context"],
                "known_observations": r["supporting_observations"], "cost_effort": r["cost_effort"],
                "verify_before_acting": r["verify_before_acting"], "limitations": r["limitations"],
            }
            for g in recs["groups"] for r in g["recommendations"]
        ],
        "user_reported_context": {
            "note": "Answers selected by the user from fixed dropdowns. NOT verified by FieldWise. Refer to them as 'you reported'.",
            "answers": [{"question": c["question"], "answer": c["answer"]} for c in recs["reported_context"]],
        },
        "suggestions_not_shown_because_of_user_answers": [
            {"action": n["action"], "reason": n["reason"]} for n in recs["not_shown"]
        ],
        "warnings": recs["warnings"],
        "approved_source_excerpts": [
            {"title": sources[sid]["title"], "publisher": sources[sid]["publisher"], "excerpt": sources[sid]["excerpt"]}
            for sid in used
        ],
        "explicit_limitations": NOT_TELL + usda.MANIFEST["known_limitations"],
    }


@bp.get("/ai/status")
def status():
    st = ai_status()
    st["model"] = current_app.config["AI_MODEL"] if st["available"] else None
    return jsonify(st)


@bp.post("/audit")
@limiter.limit(lambda: current_app.config["RATELIMIT_AI"])
def audit():
    st = ai_status()
    if not st["available"]:
        raise APIError(st["code"], st["message"], 503)
    body = ExplainRequest.model_validate(request.get_json(silent=True) or {})
    sel = selection.read(body.selection_token)
    from app.routes.recommendations import parse_context

    context_answers = parse_context(body.context)

    ok, reason = turnstile.verify(
        body.turnstile_token, current_app.config["TURNSTILE_SECRET_KEY"], request.remote_addr,
        timeout=current_app.config["TURNSTILE_TIMEOUT"],
    )
    if not ok:
        msg = {
            "turnstile_missing": "Please complete the verification check first.",
            "turnstile_failed": "Verification check failed. Please try again.",
            "turnstile_unavailable": "The verification service is unavailable. Please try again later.",
        }.get(reason, "Verification check failed.")
        raise APIError(reason, msg, 403)

    try:
        recs = engine.generate(selection.to_inputs(sel, context_answers))
    except engine.UnsupportedCrop as exc:
        raise APIError("unsupported_crop", "The AI audit is available for corn and wheat areas only.", 422) from exc
    rec_ids = recs["recommendation_ids"]
    if not rec_ids:
        raise APIError("nothing_to_audit", "There are no suggestions to audit for these answers.", 422)
    context = build_context(sel, recs)

    # Identical inputs -> identical cache key. The key contains no user or location-precise data.
    key_src = json.dumps({"v": "audit-v1", "m": current_app.config["AI_MODEL"], "ctx": context}, sort_keys=True)
    cache_key = "ai:" + hashlib.sha256(key_src.encode()).hexdigest()
    cache = current_app.extensions["fieldwise_cache"]
    hit = cache.get(cache_key, ".json")
    if hit is not None:
        payload = json.loads(hit)
        payload["cached"] = True
        return jsonify(payload)

    try:
        user_text = ai_provider.build_user_payload(context, current_app.config["AI_MAX_INPUT_CHARS"])
        result = get_provider().explain(user_text, rec_ids)
    except ai_provider.AIUnavailable as exc:
        raise APIError(exc.code, exc.message, 503) from exc

    payload = {
        "ruleset_version": recs["ruleset_version"],
        "dataset_year": recs["dataset_year"],
        "model": result.model,
        "recommendation_ids": rec_ids,
        "explanation": result.explanation.model_dump(),
        "disclaimer": (
            "AI-generated audit. The explanations describe FieldWise's rule-based suggestions; the practice review, "
            "additional considerations and adviser questions are the AI's own and are NOT from FieldWise's verified "
            "rules, sources or case studies. It was checked for structure and obvious unsupported claims but may "
            "still contain errors. Nothing here was measured on this land — confirm with a local adviser."
        ),
        "cached": False,
    }
    cache.set(cache_key, json.dumps(payload).encode(), ".json")
    return jsonify(payload)
