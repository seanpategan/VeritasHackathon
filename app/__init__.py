"""FieldWise — Flask application factory."""
from __future__ import annotations

import logging
import os
import secrets

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.cache import DiskCache
from app.config import Config
from app.errors import register_error_handlers

limiter = Limiter(key_func=get_remote_address)


def _shared_fallback_secret(path=None) -> str:
    from pathlib import Path

    path = Path(path) if path else Path(__file__).resolve().parent.parent / "instance" / "secret_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # first worker creates it
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    for _ in range(50):  # another worker may be mid-write
        key = path.read_text().strip()
        if len(key) == 64:
            return key
        import time

        time.sleep(0.01)
    raise RuntimeError("could not read instance/secret_key")


def create_app(config_object: type[Config] | None = None) -> Flask:
    config_object = config_object or Config
    app = Flask(__name__)
    app.config.from_object(config_object)
    if not app.config.get("SECRET_KEY"):
        # Fallback when SECRET_KEY is unset: one key persisted in instance/, shared by every worker on this
        # host, so selection tokens verify across gunicorn workers. Set SECRET_KEY explicitly in production.
        app.config["SECRET_KEY"] = _shared_fallback_secret()
        app.logger.warning("SECRET_KEY is not set; using a generated key stored in instance/secret_key.")

    app.config["RATELIMIT_STORAGE_URI"] = app.config.get("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)
    if app.config["RATELIMIT_STORAGE_URI"].startswith("memory://"):
        app.logger.warning(
            "Rate limiting uses in-memory storage: DEVELOPMENT ONLY (per-process, not shared across workers)."
        )

    app.extensions["fieldwise_cache"] = DiskCache(app.config["CACHE_DIR"])
    app.extensions["ai_explanation_cache"] = {}

    if not app.debug and not app.testing:
        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

    register_error_handlers(app)

    from app.routes.ai import bp as ai_bp
    from app.routes.crops import bp as crops_bp
    from app.routes.pages import bp as pages_bp
    from app.routes.recommendations import bp as recs_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(crops_bp)
    app.register_blueprint(recs_bp)
    app.register_blueprint(ai_bp)

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return resp

    return app
