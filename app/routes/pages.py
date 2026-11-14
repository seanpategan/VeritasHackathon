"""HTML page and health check."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template

from app.routes.ai import ai_status
from app.rules import engine

bp = Blueprint("pages", __name__)
DATA = Path(__file__).resolve().parent.parent / "data"


@bp.get("/")
def index():
    bookmarks = json.loads((DATA / "bookmarks.json").read_text())["bookmarks"]
    st = ai_status()
    return render_template(
        "index.html",
        bookmarks=bookmarks,
        turnstile_site_key=current_app.config["TURNSTILE_SITE_KEY"] if st["available"] else "",
        ai_status=st,
        context_questions=engine.load_questions(),
    )


@bp.get("/healthz")
def healthz():
    return jsonify({"ok": True})
